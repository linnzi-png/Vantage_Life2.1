# WAR Report Import — Runbook

Two ways to load weekly WAR spreadsheets. Both apply the same parsing and the
same overlap rule, because both call `backend/war_import.py`.

- **In the app** — Admin → Import War Reports. No terminal, no database access.
  This is the normal path. See `docs/ADMIN_PANEL.md`.
- **From a terminal** — `backend/import_xlsx_war.py`. Needs direct MongoDB
  network access (port 27017), so it only runs from a machine that can reach
  the cluster. Use it for bulk backfills.

This runbook covers the terminal path.

---

## Before you start

**Rotate the database password first if you have not already.** A live
connection string was committed to `import_all_wars.py` and remains in git
history, so the old credential must be considered public.

You need:
- Python 3.11+
- The repo checked out
- Your `.xlsx` files, each named with the **Wednesday** the report opens on:
  `2026-02-18_MJ_War_Report.xlsx`. The date drives which sales day every tab
  lands on — a wrong date misdates the whole week. Non-Wednesday names are
  rejected rather than guessed at.

Install the two dependencies the importer needs:

```
pip install openpyxl pymongo dnspython
```

---

## Step 1 — Dry run (always do this first)

Nothing is written. This tells you exactly what would change, and — importantly
— which agents in the spreadsheets are missing from your roster.

**Windows (PowerShell):**
```powershell
cd C:\Users\linnz\OneDrive\Documents\Vantage_Life2.1\backend
$env:MONGO_URL = "mongodb+srv://USER:PASSWORD@vantagelife.r5atbyt.mongodb.net/"
python import_xlsx_war.py "C:\path\to\war_reports" --dry-run
```

**macOS / Linux:**
```bash
cd ~/Vantage_Life2.1/backend
export MONGO_URL='mongodb+srv://USER:PASSWORD@vantagelife.r5atbyt.mongodb.net/'
python import_xlsx_war.py ~/path/to/war_reports --dry-run
```

You can pass a directory (as above) or individual files. Either way the
importer sorts them by filename, which is chronological — that ordering matters,
see the overlap rule below.

## Step 2 — Read the output

```
==============================================================
WOULD IMPORT: 875 new entries, 18 updated by a later report

!! 3 AGENT(S) NOT ON THE ROSTER — 41 rows skipped:
   • Jane Doe                     under Ali Musa  (22 days)
   ...
==============================================================
```

- **new entries** — rows that will be inserted.
- **updated by a later report** — the overlap corrections (see below). Expect a
  non-zero number whenever you import consecutive weeks.
- **NOT ON THE ROSTER** — these rows are **skipped**. Add each person in the app
  (Admin → Add Person) with the upline shown, then re-run the dry run until the
  list is empty. Do not reach for `--create-missing` to make the warning go
  away: agents created that way have no upline, and `visible_agent_ids()` walks
  `agent_profiles.upline_id`, so they are invisible in every GA/MGA team rollup.
- **agent-submitted entries left untouched** — a day where someone had already
  entered their own numbers in the app. The importer never overwrites those.

## Step 3 — Import for real

Same command, without the flag:

```powershell
python import_xlsx_war.py "C:\path\to\war_reports"
```

The totals should match the dry run exactly. If they do not, something changed
between the two runs.

## Step 4 — Verify in the app

Open the app and check a week you know. Spot-check one high-volume agent's daily
numbers against the spreadsheet.

---

## The overlap rule

Each WAR report carries **nine** daily tabs (`Wed` → `Thurs (2)`), but reports
are **seven** days apart. So `Wed (2)` and `Thurs (2)` cover the same sales days
as the *next* report's `Wed` and `Thurs`.

**The later file wins.** Re-importing replaces the earlier WAR-sourced entry for
that (agent, day) rather than skipping it as a duplicate, which is what keeps
the following week's corrections instead of dropping them. Concretely, in the
Feb–Aug 2026 MJ set, 893 spreadsheet rows collapse to 875 entries with 18
overlap updates and no duplicated agent-days.

Two consequences:
- **Import in chronological order.** The importer sorts by filename for you, so
  keep the `YYYY-MM-DD_` prefix.
- **Re-running is safe.** The same file imported twice updates in place rather
  than duplicating.

## Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Report what would change; write nothing. Counts overlaps the same way a live run would. |
| `--create-missing` | Create agents absent from the roster. They get **no upline** and stay invisible in team rollups until you set one. Prefer Add Person. |

`MONGO_URL` is required. `MONGO_DB` overrides the database name (default
`vantagelife`). `WEEK_START` overrides the week start for files that are not
named with a date — only useful for a single file at a time.

## Getting a WAR report back out of the app

Historical Vault → any week card:

- **EXPORT** — JSON, round-trips through the importer, serves as the backup.
  Any RGA.
- **AGENT-BY-DAY CSV** — one flat row per agent per day, for eyeballing against
  a report.
- **WAR WORKBOOK (.XLSX)** — the report itself, rebuilt from the app's data:
  same eleven tabs, same 22-column header, office name in the same cell, nine
  daily tabs so `Wed (2)`/`Thurs (2)` still overlap the next week. It re-imports
  through the same parser, which is asserted by a test.

Two different grants. The **workbook** is the report the office has always read,
so any admin (`ADMIN_EMAILS`) can pull it. The **flat CSV** is a wider dump and
is restricted to `EXPORT_EMAILS` (default: one address). Set either on Railway.

Two columns a real report carries are left blank rather than guessed: **Show
Rate**, whose formula has never been specified for this app, and the **LOST
BUSINESS** tab, which the app does not track. Close Rate is filled, via
`metrics.close_rate()`.

## Reconciling the two-day overlap

```
python3 backend/audit_war_overlap.py /path/to/that/offices/reports
```

Read-only — it touches spreadsheets, never the database. It reports, per office:
rows that appear in only the older book (a pre-2 PM sale, kept), only the newer
book (post-2 PM, added), and — the ones worth a human's eye — rows carrying
numbers in **both** books for the same day. The importer keeps only the newer
book's row there, which is right when the newer book restates the older one and
wrong if they are genuinely two halves of a day. The spreadsheets cannot tell
those apart; someone who knows the office can.

Result for MJ (25 reports, 2026-02-18 → 2026-08-05): 18 rows in both books, 15
of them carrying identical numbers, and no older-book ALP exceeding the newer
book's — so replacing loses no money in that office. Gojcaj, Monty and Rust have
not been run.

## Troubleshooting

**`ServerSelectionTimeoutError`** — the machine cannot reach MongoDB on port
27017. Check the Atlas IP allowlist, and note that many corporate networks and
all cloud sandboxes block that port. Run from a machine that can reach it.

**`Week start ... is a Monday, not a Wednesday`** — the filename date is wrong.
Rename the file to the Wednesday the report opens on.

**`Could not read week start from filename`** — the name does not start with
`YYYY-MM-DD`. Rename it, or import that file alone with `WEEK_START` set.

**Everything is skipped as not-on-roster** — the names in the `Agent` column do
not match `agent_profiles.name`. Matching is case-insensitive but otherwise
exact, so trailing initials or middle names in one place and not the other will
miss.
