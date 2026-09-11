"""Write a WAR-format .xlsx from the app's own production data.

Once agents enter their numbers nightly in the app, the office still wants the
workbook it has always read. This rebuilds it against the real template: the
leadership summary blocks on top, two blank rows, then the data section — same
tabs, same column layout, same header row as the spreadsheets the importer
reads. A generated file can be opened side by side with an old WAR report and
re-imported unchanged.

Every rollup, rate and weekly total is written as a LIVE EXCEL FORMULA rather
than a precomputed number, which is what makes the file usable rather than just
printable: edit an agent's SITS in the workbook and the close ratio, the show
rate, that agent's leader block and the office headline all move with it, the
same way they do in the office's own copy. The formulas are transcribed from
the real report, not invented.

Structural constants come from war_import. Defining the layout twice is how a
column shift silently corrupts one path but not the other, so this module owns
only the summary block, which the importer never reads.

Two deliberate differences from the sample report, both noted at the site:
  * the office headline sums the data range directly instead of chaining
    through the MGA blocks (see _office_block)
  * the leader blocks bound their SUMIF ranges to the data section instead of
    using whole columns (see _leader_block)
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import war_import

# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

# The summary block sits above the data section and uses its OWN column order,
# which is not the data section's: "Appts" (column F up here) reads SETS out of
# column G down there. Each entry is (summary column, row-1 title, metric key).
# Written top-down from the real report — do not re-sort into metric order.
SUMMARY_ALP_COL = "C"
SUMMARY_LEADERSHIP_ALP_COL = "E"
SUMMARY_METRICS: List[Tuple[str, str, str]] = [
    ("F", "Appts", "sets"),
    ("G", "Pres", "sits"),
    ("H", "Sales", "sales"),
    ("I", "POS SITS", "pos_sits"),
    ("J", "POS SA", "pos_sales"),
    ("K", "VET SITS", "vet_sits"),
    ("L", "VET SA", "vet_sales"),
    ("M", "REF OBT", "refs_obtained"),
    ("N", "REF SITS", "ref_sits"),
    ("O", "REF SA", "ref_sales"),
    ("P", "OTS SITS", "ots_sits"),
    ("Q", "OTS SA", "ots_sales"),
    ("R", "N1", "n1"),
]

# The rate row under each totals row. `t` is the totals row, `n` the agent-count
# row two below it. Cells not listed are left blank but still shaded.
#   SHOW RATE  = (Pres + N1) / Appts  -> (SITS + N1) / SETS, metrics.show_rate
#   CLOSE RATIO = Sales / Pres        -> SALES / SITS,       metrics.close_rate
RATIO_ROW: List[Tuple[str, str, str, str]] = [
    # (column, label, formula, number format)
    ("C", "# of Agents", "", "General"),          # filled in per block
    ("E", "ALP per sale", "=IFERROR(C{t}/H{t},0)", "0"),
    ("F", "SHOW RATE", "=IFERROR((G{t}+R{t})/F{t},0)", "0%"),
    ("G", "CLOSE RATIO", "=IFERROR(H{t}/G{t},0)", "0%"),
    ("H", "ALP/\nAGENT", "=IFERROR(C{t}/C{n},0)", "0"),
    ("J", "POS\nCLOSE", "=IFERROR(J{t}/I{t},0)", "0%"),
    ("L", "VET\nCLOSE", "=IFERROR(L{t}/K{t},0)", "0%"),
    ("M", "REF PER\nSIT", "=IFERROR(M{t}/SUM(G{t}+R{t}),0)", "0.0"),
    ("O", "REF CLOSE", "=IFERROR(O{t}/N{t},0)", "0%"),
    ("Q", "OTS CLOSE", "=IFERROR(Q{t}/P{t},0)", "0%"),
]

# Columns the summary block spans, and the widest one, for shading.
SUMMARY_FIRST_COL, SUMMARY_LAST_COL = "B", "R"

# Rows 1-4 are the office block; every leader adds three more; then two blank
# rows separate the summary from the data header.
SUMMARY_BLOCK_HEIGHT = 3
OFFICE_BLOCK_LAST_ROW = 4
BLANK_ROWS_BEFORE_HEADER = 2

# LOST BUSINESS keeps its own header — it is not a WAR data tab and the
# importer never reads it, but the office's copy has these columns.
LOST_BUSINESS_HEADER = [
    " ", "AGENTS NAME", "MGA", "DATE WRITTEN", "ALP",
    "TRIAL OR DECLINE", "REWRITTEN?", "NOTES", "VEREFIED BY",
]

COLUMN_WIDTHS = {
    "A": 20.6, "B": 23.3, "C": 22.7, "D": 3.1, "E": 14.1, "F": 24.6,
    "G": 10.6, "H": 11.7, "I": 11.4, "J": 10.9, "K": 11.7, "L": 11.6,
    "N": 10.9, "O": 13.4, "P": 11.1, "Q": 11.3, "R": 12.1, "S": 11.7,
    "U": 10.7, "V": 10.6,
}
LOST_BUSINESS_WIDTHS = {"A": 30.7, "B": 22.1, "C": 16.3, "D": 17.3,
                        "F": 17.3, "H": 118.0}

TITLE_ROW_HEIGHT = 30.75
ROW_HEIGHT = 12.75

# ---------------------------------------------------------------------------
# styling, lifted from the sample report
# ---------------------------------------------------------------------------

PLUM = PatternFill("solid", fgColor="FF741B47")     # title + data header
LEADER = PatternFill("solid", fgColor="FFA64D79")   # a totals row
BLUSH = PatternFill("solid", fgColor="FFEAD1DC")    # a rate row
WHITE = PatternFill("solid", fgColor="FFFFFFFF")    # data metric cells
GREY = PatternFill("solid", fgColor="FFD9D9D9")     # Close/Show Rate cells

_THIN = Side(style="thin")
BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

HEAD_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFFFF")
LABEL_FONT = Font(name="Arial", size=10)
BOLD_FONT = Font(name="Arial", size=10, bold=True)
DATA_FONT = Font(name="Arial", size=10)
NAME_FONT = Font(name="Calibri", size=11, bold=True)

CENTER = Alignment(horizontal="center", wrap_text=True)
RIGHT = Alignment(horizontal="right")
LEFT_WRAP = Alignment(wrap_text=True)


def _col(index0: int) -> str:
    """war_import's 0-based column index -> an Excel column letter."""
    return get_column_letter(index0 + 1)


# Data-section column letters, derived so they cannot drift from the importer.
DATA_COL = {key: _col(i) for key, i in war_import.METRIC_COLUMNS.items()}
AGENT_COL = _col(war_import.AGENT_NAME_COLUMN)
MGA_COL = _col(war_import.CONTEXT_COLUMNS["mga"])
GA_COL = _col(war_import.CONTEXT_COLUMNS["ga"])
CLOSE_COL = _col(war_import.CLOSE_RATE_COLUMN)
SHOW_COL = _col(war_import.SHOW_RATE_COLUMN)
# LDR ("is this person a leader?") is column D. It has no field in PulseIn and
# the app does not track it, so the export leaves it blank and the
# LEADERSHIP ALP rollup that reads it comes out at 0 rather than invented.
LDR_COL = "D"


def _style_span(ws, row: int, first: str, last: str, fill: PatternFill,
                font: Font) -> None:
    for c in range(ord(first), ord(last) + 1):
        cell = ws[f"{chr(c)}{row}"]
        cell.fill = fill
        cell.font = font
        cell.border = BOX


# ---------------------------------------------------------------------------
# summary blocks
# ---------------------------------------------------------------------------

def _title_row(ws) -> None:
    """Row 1: the summary block's own column headings."""
    ws["C1"] = "ALP"
    ws["E1"] = "LEADERSHIP\nALP"
    for col, title, _key in SUMMARY_METRICS:
        ws[f"{col}1"] = title
    _style_span(ws, 1, SUMMARY_FIRST_COL, SUMMARY_LAST_COL, PLUM, HEAD_FONT)
    for c in range(ord(SUMMARY_FIRST_COL), ord(SUMMARY_LAST_COL) + 1):
        ws[f"{chr(c)}1"].alignment = CENTER
    ws.row_dimensions[1].height = TITLE_ROW_HEIGHT


def _rate_rows(ws, totals_row: int) -> None:
    """The label row and the rate row under one totals row."""
    label_row, ratio_row = totals_row + 1, totals_row + 2
    for col, label, formula, fmt in RATIO_ROW:
        ws[f"{col}{label_row}"] = label
        if formula:
            cell = ws[f"{col}{ratio_row}"]
            cell.value = formula.format(t=totals_row, n=ratio_row)
            cell.number_format = fmt
    _style_span(ws, label_row, SUMMARY_ALP_COL, SUMMARY_LAST_COL, BLUSH, LABEL_FONT)
    _style_span(ws, ratio_row, SUMMARY_ALP_COL, SUMMARY_LAST_COL, BLUSH, BOLD_FONT)
    for col, _l, _f, _fmt in RATIO_ROW:
        ws[f"{col}{label_row}"].alignment = LEFT_WRAP
        ws[f"{col}{ratio_row}"].alignment = RIGHT
    ws.row_dimensions[label_row].height = ROW_HEIGHT
    ws.row_dimensions[ratio_row].height = ROW_HEIGHT


def _office_block(ws, office: str, first: int, last: int) -> None:
    """Rows 1-4: the office headline.

    The sample report reaches this total by chaining through the MGA blocks
    (`=SUM(,C5,)`). That only adds up when every agent on the roster sits under
    a named MGA; ours summarises whatever the app actually holds, and an agent
    whose upline chain has no MGA in it would silently drop out of the office
    headline — the one number someone reconciles first. So this block sums the
    data range directly. Same value on a fully-populated roster, right value on
    any other.
    """
    _title_row(ws)
    ws["B2"] = office
    ws[f"{SUMMARY_ALP_COL}2"] = f"=SUM({DATA_COL['alp']}{first}:{DATA_COL['alp']}{last})"
    ws[f"{SUMMARY_LEADERSHIP_ALP_COL}2"] = (
        f'=SUMIFS({DATA_COL["alp"]}{first}:{DATA_COL["alp"]}{last},'
        f'{LDR_COL}{first}:{LDR_COL}{last},"Y")')
    for col, _title, key in SUMMARY_METRICS:
        ws[f"{col}2"] = f"=SUM({DATA_COL[key]}{first}:{DATA_COL[key]}{last})"

    _style_span(ws, 2, SUMMARY_FIRST_COL, SUMMARY_LAST_COL, LEADER, HEAD_FONT)
    ws["B2"].font = Font(name="Calibri", size=11, bold=True, color="FFFFFFFF")
    ws["B2"].alignment = LEFT_WRAP
    for col in [SUMMARY_ALP_COL, SUMMARY_LEADERSHIP_ALP_COL] + [c for c, _, _ in SUMMARY_METRICS]:
        ws[f"{col}2"].number_format = "0"
        ws[f"{col}2"].alignment = RIGHT
    ws.row_dimensions[2].height = ROW_HEIGHT

    _rate_rows(ws, 2)
    ws[f"{SUMMARY_ALP_COL}4"] = f"=COUNTA({AGENT_COL}{first}:{AGENT_COL}{last})"


def _leader_block(ws, row: int, name: str, match_col: str,
                  first: int, last: int) -> None:
    """One MGA's or GA's rollup: totals row, label row, rate row.

    `match_col` is the data-section column their name appears in — A for an
    MGA, B for a GA — so the same three rows serve both.

    Ranges are bounded to the data section rather than whole columns. A
    whole-column SUMIF on column B would have the criteria cell (the leader's
    own name, up here in the summary) inside its own range; it happens to add
    zero today because the ALP column is blank on summary rows, but it is the
    kind of thing that stops being true the moment a column moves.
    """
    ws[f"B{row}"] = name
    ws[f"{SUMMARY_ALP_COL}{row}"] = (
        f"=SUMIF({match_col}{first}:{match_col}{last},B{row},"
        f"{DATA_COL['alp']}{first}:{DATA_COL['alp']}{last})")
    ws[f"{SUMMARY_LEADERSHIP_ALP_COL}{row}"] = (
        f'=SUMIFS({DATA_COL["alp"]}{first}:{DATA_COL["alp"]}{last},'
        f'{match_col}{first}:{match_col}{last},B{row},'
        f'{LDR_COL}{first}:{LDR_COL}{last},"Y")')
    for col, _title, key in SUMMARY_METRICS:
        ws[f"{col}{row}"] = (
            f"=SUMIF({match_col}{first}:{match_col}{last},B{row},"
            f"{DATA_COL[key]}{first}:{DATA_COL[key]}{last})")

    _style_span(ws, row, SUMMARY_FIRST_COL, SUMMARY_LAST_COL, LEADER, HEAD_FONT)
    ws[f"B{row}"].font = Font(name="Calibri", size=11, bold=True, color="FFFFFFFF")
    ws[f"B{row}"].alignment = LEFT_WRAP
    for col in [SUMMARY_ALP_COL, SUMMARY_LEADERSHIP_ALP_COL] + [c for c, _, _ in SUMMARY_METRICS]:
        ws[f"{col}{row}"].number_format = "0"
        ws[f"{col}{row}"].alignment = RIGHT
    ws.row_dimensions[row].height = ROW_HEIGHT

    _rate_rows(ws, row)
    ws[f"{SUMMARY_ALP_COL}{row + 2}"] = (
        f"=COUNTIFS({match_col}{first}:{match_col}{last},B{row})")


def leaders_of(roster: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """[(leader name, the data column their name sits in)], MGAs then GAs.

    One summary block per distinct leader on the roster, in the same order the
    real report lists them: the MGA rollups first, then the GAs beneath them.
    """
    out: List[Tuple[str, str]] = []
    for key, col in (("mga", MGA_COL), ("ga", GA_COL)):
        seen = []
        for person in roster:
            name = (person.get(key) or "").strip()
            if name and name not in seen:
                seen.append(name)
        out.extend((name, col) for name in sorted(seen))
    return out


def header_row_index(leader_count: int) -> int:
    """Row the data-section header lands on, given how many leader blocks.

    Office block (4 rows) + three rows per leader + two blank rows + one.
    The sample report has one MGA and one GA, which puts its header on row 13.
    """
    return (OFFICE_BLOCK_LAST_ROW + SUMMARY_BLOCK_HEIGHT * leader_count
            + BLANK_ROWS_BEFORE_HEADER + 1)


# ---------------------------------------------------------------------------
# data section
# ---------------------------------------------------------------------------

def _write_header(ws, row: int) -> None:
    for i, title in enumerate(war_import.HEADER_ROW, start=1):
        cell = ws.cell(row=row, column=i)
        cell.value = title
        cell.fill = PLUM
        cell.font = HEAD_FONT
        cell.alignment = CENTER
        cell.border = BOX
    ws[f"{CLOSE_COL}{row}"].number_format = "0%"
    ws[f"{SHOW_COL}{row}"].number_format = "0%"
    ws.row_dimensions[row].height = ROW_HEIGHT


def _write_agent_row(ws, row: int, person: Dict[str, Any],
                     m: Optional[Dict[str, Any]]) -> None:
    """One data row: leadership columns, the 14 metrics, then the two rates.

    `m` is None for an agent with nothing that day. Real reports leave those
    cells blank rather than zero, and the importer's activity filter drops
    either, so blank keeps the generated file closest to the original — and the
    rate formulas still sit on the row, returning 0, exactly as they do there.
    """
    for key, col in war_import.CONTEXT_COLUMNS.items():
        ws.cell(row=row, column=col + 1, value=person.get(key))
    name_cell = ws.cell(row=row, column=war_import.AGENT_NAME_COLUMN + 1,
                        value=person["name"])
    name_cell.font = NAME_FONT
    ws.cell(row=row, column=war_import.CONTEXT_COLUMNS["mga"] + 1).font = NAME_FONT

    for key, col in war_import.METRIC_COLUMNS.items():
        cell = ws.cell(row=row, column=col + 1)
        if m is not None:
            cell.value = m.get(key, 0)
        cell.number_format = "#,##0"
        cell.fill = WHITE
        cell.font = DATA_FONT
        cell.alignment = RIGHT
        cell.border = BOX

    # The two rate columns are formulas on every row, produced or not — the
    # same ones the real report carries, and the same rules as metrics.py:
    # close_rate = SALES/SITS (N1 not subtracted, it is already out of SITS),
    # show_rate  = (SITS+N1)/SETS (N1 added back — they did show up).
    sets_c, sits_c, sales_c, n1_c = (DATA_COL["sets"], DATA_COL["sits"],
                                     DATA_COL["sales"], DATA_COL["n1"])
    for col, formula in (
        (CLOSE_COL, f"=IFERROR({sales_c}{row}/{sits_c}{row},0)"),
        (SHOW_COL, f"=IFERROR(SUM({sits_c}{row}+{n1_c}{row})/{sets_c}{row},0)"),
    ):
        cell = ws[f"{col}{row}"]
        cell.value = formula
        cell.number_format = "0%"
        cell.fill = GREY
        cell.font = DATA_FONT
        cell.alignment = RIGHT
        cell.border = BOX
    ws.row_dimensions[row].height = ROW_HEIGHT


def _write_tab(wb, title: str, office: str, roster: List[Dict[str, Any]],
               rows_by_agent: Optional[Dict[str, Dict[str, Any]]],
               source_tabs: Optional[List[str]] = None):
    """Build one tab. Every tab has identical geometry, which is what lets the
    Weekly Totals tab add the same cell across all nine days.

    Pass `source_tabs` instead of `rows_by_agent` to make the metric cells
    cross-sheet sums (that is the Weekly Totals tab); pass `rows_by_agent` for
    a daily tab.
    """
    ws = wb.create_sheet(title)
    leaders = leaders_of(roster)
    head = header_row_index(len(leaders))
    first = head + 1
    last = head + max(len(roster), 1)

    _office_block(ws, office, first, last)
    for i, (name, match_col) in enumerate(leaders):
        _leader_block(ws, OFFICE_BLOCK_LAST_ROW + 1 + SUMMARY_BLOCK_HEIGHT * i,
                      name, match_col, first, last)
    for r in range(OFFICE_BLOCK_LAST_ROW + SUMMARY_BLOCK_HEIGHT * len(leaders) + 1, head):
        ws.row_dimensions[r].height = ROW_HEIGHT

    _write_header(ws, head)
    for i, person in enumerate(roster):
        row = first + i
        _write_agent_row(ws, row, person,
                         None if source_tabs else (rows_by_agent or {}).get(person["name"]))
        if source_tabs:
            for key, col in war_import.METRIC_COLUMNS.items():
                letter = DATA_COL[key]
                ws.cell(row=row, column=col + 1).value = "=(" + "+".join(
                    f"{_ref(tab)}!{letter}{row}" for tab in source_tabs) + ")"

    for col, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[col].width = width
    return ws


def _ref(tab: str) -> str:
    """A sheet name as it must appear inside a formula: quoted if it has a
    space, which "Mon ", "Tues " and "Wed (2)" all do."""
    return f"'{tab}'" if any(ch in tab for ch in " ()") else tab


# ---------------------------------------------------------------------------
# workbook
# ---------------------------------------------------------------------------

def build_workbook(office: str, week_start: date, roster: List[Dict[str, Any]],
                   by_day: Dict[str, Dict[str, Dict[str, Any]]]) -> io.BytesIO:
    """Build the workbook.

    roster:  [{"name", "mga", "ga", "sa", "state"}, ...] — every agent in scope,
             listed on every tab whether or not they produced, as the real
             reports do.
    by_day:  {"YYYY-MM-DD": {agent_name: {metric: value, ..., "alp": float}}}

    Tabs follow war_import.TAB_DAY_OFFSET, so the file spans the same nine days
    as a real report and "Wed (2)"/"Thurs (2)" line up with the next week.

    Weekly Totals adds the same cell across all NINE daily tabs, transcribed
    from the real report, which does the same. That is the office's definition
    of the week and it deliberately includes the two overlap days — the point
    of the overlap is that those days belong to both books (CLAUDE.md, WAR
    overlap), and a total that dropped them would not reconcile against the
    office's own copy.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    tabs = list(war_import.TAB_DAY_OFFSET)
    _write_tab(wb, war_import.TOTALS_TAB, office, roster, None, source_tabs=tabs)
    for tab, offset in war_import.TAB_DAY_OFFSET.items():
        day = (week_start + timedelta(days=offset)).strftime("%Y-%m-%d")
        _write_tab(wb, tab, office, roster, by_day.get(day, {}))

    # Empty but present, so the generated file has the same tab set as a real
    # report. The app does not track lost business; writing rows here would be
    # inventing them.
    lost = wb.create_sheet(war_import.LOST_BUSINESS_TAB)
    for i, title in enumerate(LOST_BUSINESS_HEADER, start=1):
        cell = lost.cell(row=1, column=i, value=title)
        cell.fill = PLUM
        cell.font = HEAD_FONT
        cell.alignment = CENTER
    for col, width in LOST_BUSINESS_WIDTHS.items():
        lost.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
