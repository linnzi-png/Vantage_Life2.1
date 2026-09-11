"""WAR-format export: round-trips through the importer, RBAC, CSV."""
import import_war_data
from conftest import auth, make_session


async def _rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def _add(db, agent_id, office, sales_day, **metrics):
    doc = {
        "entry_id": f"pe_{agent_id}_{sales_day}", "agent_id": agent_id, "office": office,
        "sales_day": sales_day, "sets": 0, "sits": 0, "sales": 0, "ots_sits": 0, "ots_sales": 0,
        "n1": 0, "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0, "gross_alp": 0.0, "net_alp": 0.0,
    }
    doc.update(metrics)
    await db.production_entries.insert_one(doc)


async def test_export_round_trips_through_importer(client, seeded_db):
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, sits=3, n1=1, gross_alp=1000.0)
    await _add(seeded_db, "AG_1", "MCM", "2026-07-02", sales=1, sits=2, gross_alp=500.0)
    await _add(seeded_db, "AG_2", "AMP", "2026-07-01", sales=1, sits=1, gross_alp=300.0)
    token = await _rga(seeded_db)

    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-02", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()

    # Feed every performance row back through the importer's make_entry and
    # assert the reconstructed per-agent-per-day metrics match the originals.
    rebuilt = {}
    for tab in data["weekly_tabs"]:
        for perf in tab["performance"]:
            e = import_war_data.make_entry("x", "MCM", tab["date"], perf)
            rebuilt[(tab["date"], perf["agent"])] = e

    a1_d1 = rebuilt[("2026-07-01", "Agent One")]
    assert a1_d1["gross_alp"] == 1000.0 and a1_d1["sales"] == 2 and a1_d1["sits"] == 3 and a1_d1["n1"] == 1
    assert rebuilt[("2026-07-02", "Agent One")]["gross_alp"] == 500.0
    assert rebuilt[("2026-07-01", "Agent Two")]["gross_alp"] == 300.0
    assert data["report_metadata"]["weekly_total_alp"] == 1800.0


async def test_export_defaults_to_current_week(client, seeded_db):
    token = await _rga(seeded_db)
    r = await client.get("/api/vault/export", headers=auth(token))
    assert r.status_code == 200, r.text
    assert "weekly_tabs" in r.json()


async def test_export_requires_level_4(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-02", headers=auth(token))
    assert r.status_code == 403


async def test_export_csv_has_rows(client, seeded_db):
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    token = await _rga_admin(seeded_db)   # the spreadsheet is admin-only
    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-01&format=csv", headers=auth(token))
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    body = r.text
    assert "date,agent,office" in body
    assert "Agent One" in body and "1000" in body


async def test_export_bad_dates_rejected(client, seeded_db):
    token = await _rga(seeded_db)
    assert (await client.get("/api/vault/export?start=07-01-2026&end=2026-07-02", headers=auth(token))).status_code == 400
    assert (await client.get("/api/vault/export?start=2026-07-01", headers=auth(token))).status_code == 400


# ---------------- the agent-by-day spreadsheet is admin-only ----------------

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def _rga_admin(db):
    """Level 4 AND on EXPORT_EMAILS — the reconciliation exports need both."""
    return await make_session(db, role="level_4", agent_id="RGA_1", email=BOOTSTRAP_ADMIN)


async def test_csv_export_is_refused_to_an_rga_not_on_the_export_list(client, seeded_db):
    """The spreadsheet names every agent and their daily numbers in one file,
    a wider view than the JSON summary an RGA already gets."""
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    token = await _rga(seeded_db)          # level_4, not on EXPORT_EMAILS
    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-01&format=csv",
                         headers=auth(token))
    assert r.status_code == 403


async def test_admin_gets_the_workbook_but_not_the_flat_csv(client, seeded_db):
    """Two grants, not one. MJ needs the WAR workbook; the flat per-agent dump
    is narrower and stays on EXPORT_EMAILS."""
    import server
    assert server.EXPORT_EMAILS < server.ADMIN_EMAILS or \
        server.EXPORT_EMAILS != server.ADMIN_EMAILS
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1",
                               email="mj@aopremier.com")   # admin, not on EXPORT_EMAILS
    csv_r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-01&format=csv",
                             headers=auth(token))
    assert csv_r.status_code == 403, "the flat CSV dump stays narrow"

    # The workbook is the report the office has always read — admin is enough.
    xlsx_r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                              headers=auth(token))
    assert xlsx_r.status_code == 200


async def test_json_export_still_works_for_a_non_admin_rga(client, seeded_db):
    """Restricting the spreadsheet must not take away the backup export."""
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    token = await _rga(seeded_db)
    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-01",
                         headers=auth(token))
    assert r.status_code == 200


async def test_admin_gets_one_csv_row_per_agent_per_day(client, seeded_db):
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, sits=3, n1=1, gross_alp=1000.0)
    await _add(seeded_db, "AG_1", "MCM", "2026-07-02", sales=1, sits=2, gross_alp=500.0)
    await _add(seeded_db, "AG_2", "AMP", "2026-07-01", sales=1, sits=1, gross_alp=300.0)
    token = await _rga_admin(seeded_db)

    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-02&format=csv",
                         headers=auth(token))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")

    lines = [ln for ln in r.text.strip().splitlines() if ln]
    header = lines[0].split(",")
    assert header[:3] == ["date", "agent", "office"]
    assert "gross_alp" in header and "n1" in header
    assert len(lines) == 4, "header + one row per agent per day"
    # Sorted by date, then descending ALP within the day.
    assert lines[1].startswith("2026-07-01,Agent One,MCM")
    assert lines[2].startswith("2026-07-01,Agent Two,AMP")
    assert lines[3].startswith("2026-07-02,Agent One,MCM")


# ---------------- WAR workbook (.xlsx) ----------------

def _data_start(ws) -> int:
    """First data row of a tab, found the way the importer finds it — by the
    header, not by a row number. The summary block grows with the number of
    leaders, so nothing here may assume a fixed offset."""
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row and row[0] == "MGA" and row[5] == "Agent":
            return i + 1
    raise AssertionError("no data header on this tab")

async def test_xlsx_rebuilds_a_war_workbook_that_reimports(client, seeded_db):
    """The point of the format: a generated file must be readable by the same
    parser that reads the office's real reports, or it is not the same report."""
    import io
    from datetime import date
    import war_import

    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sets=5, sits=4, sales=3,
               n1=1, gross_alp=802.0)
    token = await _rga_admin(seeded_db)

    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "2026-07-01" in r.headers["content-disposition"]

    parsed = war_import.parse_workbook(io.BytesIO(r.content), date(2026, 7, 1))
    # tabs_found is stripped; the constant keys keep the real reports' trailing
    # spaces ("Mon ", "Tues "), which the generated workbook reproduces.
    assert parsed["tabs_found"] == [t.strip() for t in war_import.TAB_DAY_OFFSET]
    row = parsed["days"]["2026-07-01"][0]
    assert row["name"] == "Agent One"
    assert (row["sets"], row["sits"], row["sales"], row["n1"]) == (5, 4, 3, 1)
    assert row["alp"] == 802


async def test_xlsx_lists_the_whole_roster_even_on_a_quiet_day(client, seeded_db):
    """Real reports carry every agent on every tab. A name vanishing on a quiet
    day is what makes two workbooks impossible to compare side by side."""
    import io
    import openpyxl
    import war_export

    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=1, gross_alp=100.0)
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
    ws = wb["Fri"]
    first = _data_start(ws)

    # Friday: nobody produced, but the roster is still listed.
    rows = list(ws.iter_rows(min_row=first, values_only=True))
    assert "Agent One" in [row[5] for row in rows if row[5]]
    assert all(v is None for v in rows[0][6:20])


async def test_xlsx_spans_nine_days_like_a_real_report(client, seeded_db):
    """Wed (2)/Thurs (2) reach into the next week, which is what creates the
    two-day overlap the whole import rule turns on."""
    import io
    from datetime import date
    import war_import

    await _add(seeded_db, "AG_1", "MCM", "2026-07-09", sales=2, gross_alp=900.0)  # Wed (2)
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    parsed = war_import.parse_workbook(io.BytesIO(r.content), date(2026, 7, 1))
    assert "2026-07-09" in parsed["days"], "the 8th day must land on the Wed (2) tab"


async def test_workbook_still_refused_to_a_non_admin_rga(client, seeded_db):
    token = await _rga(seeded_db)          # level_4, not an admin
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    assert r.status_code == 403


async def test_xlsx_requires_a_week_start(client, seeded_db):
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?start=2026-07-01&end=2026-07-02&format=xlsx&office=MCM",
                         headers=auth(token))
    assert r.status_code == 400


async def test_unknown_format_is_rejected(client, seeded_db):
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=pdf",
                         headers=auth(token))
    assert r.status_code == 400


# ---------------- the workbook matches the office's own template ----------------
#
# "Exactly as the WAR report, in the same template" (owner, 2026-09-11). These
# pin the three things that made the old export unrecognisable next to a real
# one: the leadership summary block, the data header sitting below it rather
# than on row 4, and the rates being live formulas instead of frozen numbers.

async def _workbook(client, db, week_start="2026-07-01"):
    import io
    import openpyxl
    token = await _rga_admin(db)
    r = await client.get(f"/api/vault/export?week_start={week_start}&format=xlsx&office=MCM",
                         headers=auth(token))
    assert r.status_code == 200, r.text
    # data_only=False: the formulas are the point, and openpyxl never computes
    # a cached value for a file it wrote itself.
    return openpyxl.load_workbook(io.BytesIO(r.content))


async def test_summary_block_sits_above_the_data_section(client, seeded_db):
    import war_export
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sets=10, sits=6, sales=3,
               n1=2, gross_alp=1000.0)
    ws = (await _workbook(client, seeded_db))["Wed"]

    assert ws["C1"].value == "ALP" and ws["F1"].value == "Appts"
    assert ws["B2"].value == "MCM", "the office name stays where the importer reads it"
    assert ws["C3"].value == "# of Agents" and ws["F3"].value == "SHOW RATE"
    head = _data_start(ws) - 1
    assert head == war_export.header_row_index(len(war_export.leaders_of(
        [{"mga": ws.cell(r, 1).value, "ga": ws.cell(r, 2).value}
         for r in range(head + 1, ws.max_row + 1)])))
    assert head > 4, "the old layout put the header on row 4 with nothing above it"
    assert ws.cell(head, 1).value == "MGA" and ws.cell(head, 22).value == "Show Rate"


async def test_rates_are_live_formulas_not_frozen_numbers(client, seeded_db):
    """The owner asked for formulas: change a SITS cell in Excel and the close
    ratio, the show rate and the leader rollups all have to move with it."""
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sets=10, sits=6, sales=3,
               n1=2, gross_alp=1000.0)
    ws = (await _workbook(client, seeded_db))["Wed"]
    first = _data_start(ws)
    row = next(r for r in range(first, ws.max_row + 1)
               if ws.cell(r, 6).value == "Agent One")

    # Close Rate = SALES/SITS — N1 is NOT subtracted (it is already out of SITS).
    assert ws.cell(row, 21).value == f"=IFERROR(I{row}/H{row},0)"
    # Show Rate = (SITS+N1)/SETS — N1 added back, because they did show up.
    assert ws.cell(row, 22).value == f"=IFERROR(SUM(H{row}+L{row})/G{row},0)"
    assert ws.cell(row, 21).number_format == "0%"

    assert ws["F4"].value == "=IFERROR((G2+R2)/F2,0)", "office SHOW RATE"
    assert ws["G4"].value == "=IFERROR(H2/G2,0)", "office CLOSE RATIO"
    assert ws["C2"].value.startswith("=SUM(T"), "office ALP sums the data range"


async def test_one_summary_block_per_leader(client, seeded_db):
    """MGAs first, then GAs — and each rolls up off the column its own name
    appears in, A for an MGA and B for a GA."""
    import war_export
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=1, gross_alp=100.0)
    ws = (await _workbook(client, seeded_db))["Wed"]
    head = _data_start(ws) - 1
    roster = [{"mga": ws.cell(r, 1).value, "ga": ws.cell(r, 2).value}
              for r in range(head + 1, ws.max_row + 1)]
    leaders = war_export.leaders_of(roster)
    assert leaders, "the seeded office has an upline; it must produce blocks"

    for i, (name, col) in enumerate(leaders):
        row = 5 + 3 * i
        assert ws[f"B{row}"].value == name
        assert ws[f"C{row}"].value.startswith(f"=SUMIF({col}")
        assert ws[f"C{row + 2}"].value.startswith(f"=COUNTIFS({col}")
        assert ws[f"F{row + 1}"].value == "SHOW RATE"
    # MGA blocks are listed before GA blocks, as in the real report.
    cols = [c for _n, c in leaders]
    assert cols == sorted(cols), "A (MGA) blocks come before B (GA) blocks"


async def test_weekly_totals_adds_the_same_cell_across_all_nine_tabs(client, seeded_db):
    """The office's own template totals all nine tabs, overlap days included —
    that is what makes the file reconcile against their copy."""
    import war_import
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=1, gross_alp=100.0)
    wb = await _workbook(client, seeded_db)
    ws = wb[war_import.TOTALS_TAB]
    first = _data_start(ws)
    formula = ws.cell(first, 7).value          # SETS, first agent
    assert formula.startswith("=(")
    for tab in war_import.TAB_DAY_OFFSET:
        ref = f"'{tab}'" if any(ch in tab for ch in " ()") else tab
        assert f"{ref}!G{first}" in formula, f"{tab} missing from the weekly total"


async def test_every_tab_has_identical_geometry(client, seeded_db):
    """Weekly Totals adds Wed!G14 to Thurs!G14 and so on, so a row that means
    one agent on one tab must mean the same agent on all of them."""
    import war_import
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=1, gross_alp=100.0)
    wb = await _workbook(client, seeded_db)
    tabs = [war_import.TOTALS_TAB] + [t for t in war_import.TAB_DAY_OFFSET]
    layouts = {t: (_data_start(wb[t]),
                   [wb[t].cell(r, 6).value for r in range(_data_start(wb[t]),
                                                          wb[t].max_row + 1)])
               for t in tabs}
    assert len(set(str(v) for v in layouts.values())) == 1, layouts


async def test_generated_workbook_still_reimports(client, seeded_db):
    """All the styling and formulas in the world are worthless if the office's
    own parser can no longer read the file back."""
    import io
    from datetime import date
    import war_import

    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sets=9, sits=5, sales=4,
               n1=1, gross_alp=1450.0)
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    parsed = war_import.parse_workbook(io.BytesIO(r.content), date(2026, 7, 1))
    # extract_office_name title-cases ALL-CAPS names ("RUST RGA" -> "Rust RGA"),
    # so a three-letter office code comes back title-cased too. Long-standing
    # importer behaviour, unrelated to the layout.
    assert parsed["office"] == "Mcm"
    row = parsed["days"]["2026-07-01"][0]
    assert (row["sets"], row["sits"], row["sales"], row["n1"]) == (9, 5, 4, 1)
    assert row["alp"] == 1450


# ---------------- every office, not just the biggest one ----------------
#
# The workbook used to be built for whichever office carried the most rows that
# week, so the other offices simply were not in the export (owner, 2026-09-11:
# "it also needs to cover all four offices"). A WAR workbook covers one office
# by construction — the tabs are named "Wed", "Thurs" and so on — so the whole
# organisation comes back as a zip of one workbook per office.

async def _zip(client, db, week_start="2026-07-01"):
    import io
    import zipfile
    token = await _rga_admin(db)
    r = await client.get(f"/api/vault/export?week_start={week_start}&format=xlsx",
                         headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


async def test_xlsx_without_an_office_returns_every_office(client, seeded_db):
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    zf = await _zip(client, seeded_db)
    assert sorted(zf.namelist()) == [
        "2026-07-01_AMP_War_Report.xlsx",
        "2026-07-01_MCM_War_Report.xlsx",
    ]


async def test_a_quiet_office_still_gets_its_workbook(client, seeded_db):
    """Offices come off the roster, not off the week's production. An office
    that sold nothing is a fact worth exporting, not a reason to omit it."""
    import io
    import openpyxl
    # Only MCM produced this week; AMP did nothing at all.
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    zf = await _zip(client, seeded_db)

    amp = openpyxl.load_workbook(io.BytesIO(zf.read("2026-07-01_AMP_War_Report.xlsx")))
    ws = amp["Wed"]
    assert ws["B2"].value == "AMP"
    names = [ws.cell(r, 6).value for r in range(_data_start(ws), ws.max_row + 1)]
    assert "Agent Two" in names, "AMP's roster is still listed"


async def test_each_workbook_carries_only_its_own_office(client, seeded_db):
    """The whole point of one file per office: MCM's numbers must not land in
    AMP's book, or neither one reconciles."""
    import io
    import openpyxl
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", sales=2, gross_alp=1000.0)
    await _add(seeded_db, "AG_2", "AMP", "2026-07-01", sales=5, gross_alp=4000.0)
    zf = await _zip(client, seeded_db)

    for office, agent, alp in (("MCM", "Agent One", 1000), ("AMP", "Agent Two", 4000)):
        ws = openpyxl.load_workbook(
            io.BytesIO(zf.read(f"2026-07-01_{office}_War_Report.xlsx")))["Wed"]
        rows = {ws.cell(r, 6).value: ws.cell(r, 20).value
                for r in range(_data_start(ws), ws.max_row + 1)}
        assert rows.get(agent) == alp
        other = "Agent Two" if agent == "Agent One" else "Agent One"
        assert other not in rows, f"{other} does not belong in {office}'s book"


async def test_the_response_shape_follows_the_request_not_the_data(client, seeded_db):
    """Naming an office always gives a bare workbook and omitting it always
    gives a zip — a caller must never have to sniff the content type."""
    token = await _rga_admin(seeded_db)
    one = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=AMP",
                           headers=auth(token))
    assert "spreadsheetml" in one.headers["content-type"]
    assert "AMP_War_Report.xlsx" in one.headers["content-disposition"]

    every = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx",
                             headers=auth(token))
    assert every.headers["content-type"] == "application/zip"
    assert "2026-07-01_War_Reports.zip" in every.headers["content-disposition"]


async def test_an_unknown_office_is_refused_rather_than_silently_empty(client, seeded_db):
    """Asking for an office that does not exist used to hand back a workbook
    with a header and no agents, which reads like a week with no production."""
    token = await _rga_admin(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=Nowhere",
                         headers=auth(token))
    assert r.status_code == 404
    assert "AMP" in r.json()["detail"] and "MCM" in r.json()["detail"]
