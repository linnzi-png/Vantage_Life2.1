#!/usr/bin/env python3
"""Reconcile the two-day overlap between consecutive WAR reports.

Consecutive reports overlap by two days: the "Wed (2)" / "Thurs (2)" tabs of one
report cover the same calendar days as the next report's "Wed" / "Thurs". The
Wednesday 2 PM cutoff splits that Wednesday between them — a sale in the older
book's "Wed (2)" was made BEFORE 2 PM Eastern, and one that only appears in the
newer book's "Wed" was made AFTER. They are two halves of one day, not competing
records, so a name present in only one book is normal and not an error.

What is worth a human's eye is a name carrying numbers in BOTH books for the same
day. The importer keeps only the newer book's row (replace, not add), so if those
really are two halves of one day the earlier half is being dropped — and if the
newer book is instead restating the earlier one, replacing is right and adding
would double-count. The spreadsheets cannot tell the two apart; this script finds
them so someone who knows the office can.

Read-only: it touches spreadsheets, never the database.

Usage:
    python3 audit_war_overlap.py /path/to/war_reports
    python3 audit_war_overlap.py /path/to/war_reports --json

Exit status is 1 when any day carries the same agent in both books, so it can
gate a CI step.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

import openpyxl

import war_import


def read_report(path: str, week_start: date) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{day: {agent_name: {"metrics": {...}, "active": bool}}} for one workbook."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet_map = {s.strip(): s for s in wb.sheetnames}
        out: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for tab, offset in war_import.TAB_DAY_OFFSET.items():
            actual = sheet_map.get(tab.strip())
            if actual is None:
                continue
            active, silent = war_import.parse_daily_tab_split(wb[actual])
            day = (week_start + timedelta(days=offset)).strftime("%Y-%m-%d")
            out[day] = {r["name"]: {"metrics": r, "active": True} for r in active}
            for name in silent:
                out[day].setdefault(name, {"metrics": {}, "active": False})
        return out
    finally:
        wb.close()


def office_of(filename: str) -> str:
    """'2026-08-05_MJ_War_Report.xlsx' -> 'MJ'."""
    stem = os.path.basename(filename).rsplit(".", 1)[0]
    parts = stem.split("_")
    return parts[1] if len(parts) > 1 else "Unknown"


def audit(paths: List[str]) -> Dict[str, Any]:
    by_office: Dict[str, Dict[date, str]] = {}
    unnamed: List[str] = []
    for p in paths:
        ws = war_import.week_start_from_filename(os.path.basename(p))
        if ws is None:
            unnamed.append(os.path.basename(p))
            continue
        by_office.setdefault(office_of(p), {})[ws] = p

    offices: Dict[str, Any] = {}
    for office, files in sorted(by_office.items()):
        starts = sorted(files)
        reports = {ws: read_report(files[ws], ws) for ws in starts}

        both: List[Dict[str, Any]] = []     # in both books — needs a human
        prior_only = 0                      # pre-2 PM only — normal
        master_only = 0                     # post-2 PM only — normal
        gaps: List[str] = []

        for earlier, later in zip(starts, starts[1:]):
            if (later - earlier).days != 7:
                gaps.append(f"{earlier} -> {later} ({(later - earlier).days} days)")
                continue
            for offset in (0, 1):          # the master's Wed and Thurs
                day = (later + timedelta(days=offset)).strftime("%Y-%m-%d")
                master = reports[later].get(day, {})
                prior = reports[earlier].get(day, {})
                for name, rec in prior.items():
                    if not rec["active"]:
                        continue
                    if not master.get(name, {}).get("active"):
                        prior_only += 1
                        continue
                    pm, mm = rec["metrics"], master[name]["metrics"]
                    same = all(war_import.safe_float(pm.get(k)) ==
                               war_import.safe_float(mm.get(k))
                               for k in war_import.METRIC_COLUMNS)
                    both.append({
                        "sales_day": day,
                        "agent": name,
                        "identical": same,
                        "prior_sales": war_import.safe_int(pm.get("sales")),
                        "prior_alp": war_import.safe_float(pm.get("alp")),
                        "master_sales": war_import.safe_int(mm.get("sales")),
                        "master_alp": war_import.safe_float(mm.get("alp")),
                        "prior_file": os.path.basename(files[earlier]),
                        "master_file": os.path.basename(files[later]),
                    })
                for name, rec in master.items():
                    if rec["active"] and not prior.get(name, {}).get("active"):
                        master_only += 1

        offices[office] = {
            "reports": len(starts),
            "span": [starts[0].isoformat(), starts[-1].isoformat()] if starts else [],
            "prior_book_only": prior_only,
            "master_book_only": master_only,
            "gaps": gaps,
            "in_both": sorted(both, key=lambda r: (r["sales_day"], r["agent"])),
            # What replace actually drops: older-book ALP the newer book does
            # not carry. Summing the older row's whole ALP would overstate it —
            # a row can differ on a secondary metric while the money matches.
            "alp_dropped": round(
                sum(max(0.0, r["prior_alp"] - r["master_alp"]) for r in both), 2),
        }
    return {"offices": offices, "unparseable_filenames": unnamed}


def render(result: Dict[str, Any]) -> int:
    flagged = 0
    for office, r in result["offices"].items():
        span = " .. ".join(r["span"]) if r["span"] else "-"
        print(f"\n{office}  —  {r['reports']} reports, {span}")
        print(f"  in the older book only (pre-2 PM)  : {r['prior_book_only']}   normal, kept")
        print(f"  in the newer book only (post-2 PM) : {r['master_book_only']}   normal, added")
        for g in r["gaps"]:
            print(f"  !! not 7 days apart: {g}")

        if not r["in_both"]:
            print("  no agent appears in both books on an overlap day — nothing to review")
            continue
        flagged += len(r["in_both"])
        dupes = [x for x in r["in_both"] if x["identical"]]
        diffs = [x for x in r["in_both"] if not x["identical"]]
        print(f"\n  {len(r['in_both'])} row(s) present in BOTH books — review these:")
        print(f"    {'DAY':12} {'AGENT':24} {'OLDER':>16} {'NEWER':>16}  ")
        for x in r["in_both"]:
            tag = "same numbers" if x["identical"] else "DIFFERENT"
            print(f"    {x['sales_day']:12} {x['agent']:24} "
                  f"{x['prior_sales']:>3} / ${x['prior_alp']:>10,.0f} "
                  f"{x['master_sales']:>3} / ${x['master_alp']:>10,.0f}  {tag}")
        if dupes:
            print(f"\n  {len(dupes)} carry the SAME numbers in both books. Most likely the newer")
            print("  book restates the older one, in which case the import is already right.")
        if diffs:
            print(f"\n  {len(diffs)} carry DIFFERENT numbers.")
            print("  The import keeps only the newer book's row.")
        if r["alp_dropped"]:
            print(f"\n  ${r['alp_dropped']:,.0f} of older-book ALP exceeds the newer book's and is")
            print("  therefore not counted. Worth confirming with the office.")
        else:
            print("\n  No older-book ALP exceeds the newer book's, so replacing loses no money.")

    for f in result["unparseable_filenames"]:
        print(f"\n!! skipped (no YYYY-MM-DD prefix): {f}")
    return 1 if flagged else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="folder of *_War_Report.xlsx files")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.directory, "*.xlsx")))
    if not paths:
        print(f"No .xlsx files in {args.directory}", file=sys.stderr)
        return 2

    result = audit(paths)
    if args.json:
        print(json.dumps(result, indent=2))
        return 1 if any(o["in_both"] for o in result["offices"].values()) else 0
    return render(result)


if __name__ == "__main__":
    raise SystemExit(main())
