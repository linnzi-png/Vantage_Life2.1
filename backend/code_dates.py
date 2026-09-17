"""Code dates and the rookie rule.

An agent's *code date* is the day they were contracted. Per owner
(2026-09-17): a **rookie** is anyone coded within the last 12 months, rolling —
on their one-year code anniversary they become a veteran, with no action from
anyone. So the durable fact stored on agent_profiles is `code_date`; the
`is_rookie` flag is derived from it and refreshed whenever the roster is
imported. Readers that need today's answer call rookie_on().

The source is the RGA's code-date workbook. Layouts vary between exports, so
the parser looks for a header row that carries a "Code Date" column and a
person column ("Agent", "MGA", "Name", ...) rather than fixed cell positions,
and reads every sheet — the leaders' tab lists MGAs under a different header
than the producers' tab.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import openpyxl

ROOKIE_WINDOW = timedelta(days=365)

# Header cells, lower-cased, that mark the person column. Checked in order;
# the first present wins. "Leader" is deliberately absent — on the leaders'
# tab it names the SGA above everyone, not the row's person.
_NAME_HEADERS = ("agent", "mga", "name", "producer")
_DATE_HEADERS = ("code date", "coded", "code dt")


def rookie_on(code_date: Optional[str], on: date) -> Optional[bool]:
    """True if `code_date` (ISO) falls inside the rolling window ending `on`;
    None when there is no code date to judge by, so the caller can fall back
    to whatever flag it already holds."""
    if not code_date:
        return None
    try:
        cd = date.fromisoformat(str(code_date)[:10])
    except ValueError:
        return None
    return cd > on - ROOKIE_WINDOW


def _as_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _find_columns(row: Tuple[Any, ...]) -> Optional[Tuple[int, int]]:
    """(name_col, date_col) if this row is a header row, else None."""
    cells = [str(c).strip().lower() if c is not None else "" for c in row]
    date_col = next((i for i, c in enumerate(cells) if c in _DATE_HEADERS), None)
    if date_col is None:
        return None
    for h in _NAME_HEADERS:
        if h in cells:
            return cells.index(h), date_col
    return None


def parse_workbook(fh: BinaryIO) -> List[Dict[str, Any]]:
    """Every (name, code_date) pair across all sheets, in file order.
    Rows without a readable date are skipped; the caller reports them."""
    wb = openpyxl.load_workbook(fh, data_only=True, read_only=True)
    out: List[Dict[str, Any]] = []
    for ws in wb.worksheets:
        cols: Optional[Tuple[int, int]] = None
        for row in ws.iter_rows(values_only=True):
            if cols is None:
                cols = _find_columns(row)
                continue
            name_i, date_i = cols
            name = row[name_i] if name_i < len(row) else None
            if not name or not str(name).strip():
                continue
            cd = _as_date(row[date_i] if date_i < len(row) else None)
            out.append({"sheet": ws.title, "name": re.sub(r"\s+", " ", str(name)).strip(),
                        "code_date": cd.isoformat() if cd else None})
    return out
