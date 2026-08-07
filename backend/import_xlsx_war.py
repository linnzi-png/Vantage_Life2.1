"""
XLSX WAR Import Script (terminal backfill)

Reads xlsx WAR spreadsheets and imports daily agent production into MongoDB.
Column layout and row parsing live in war_import.py, shared with the in-app
admin upload endpoint (POST /api/admin/import-war-report) so the two paths
cannot drift apart.

Prefer the in-app Admin → Import War Report screen. Use this script only when
you need a bulk local backfill; it requires direct MongoDB network access, so
it will not run from a cloud container.

    pip install openpyxl pymongo dnspython
    python import_xlsx_war.py /path/to/file1.xlsx /path/to/file2.xlsx ...

Or drop xlsx files in backend/data/xlsx_war/ and run without args:
    python import_xlsx_war.py

Week start is read from each filename ('YYYY-MM-DD_...xlsx'); set WEEK_START
to override it for files that are not named that way.
"""
import argparse
import re
import sys
import os
import uuid
from datetime import datetime, timezone, date
from typing import List, Optional

from pymongo import MongoClient

import war_import

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")

# Optional override; normally the week start comes from the filename.
try:
    WEEK_START_OVERRIDE = date.fromisoformat(os.environ["WEEK_START"])
except (KeyError, ValueError):
    WEEK_START_OVERRIDE = None


def find_agent(db, name: str) -> Optional[str]:
    existing = db.agent_profiles.find_one(
        {"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}}
    )
    return existing["agent_id"] if existing else None


def create_agent(db, name: str, office: str) -> str:
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    db.agent_profiles.insert_one({
        "agent_id": agent_id,
        "name": name.strip(),
        "office": office,
        "role": "level_1",
        "upline_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_import": True,
    })
    print(f"    + Created agent: {name} ({agent_id})")
    return agent_id


def import_xlsx_file(db, path: str, stats: dict, *, dry_run: bool, create_missing: bool) -> None:
    print(f"\nProcessing {os.path.basename(path)} ...")
    week_start = WEEK_START_OVERRIDE or war_import.week_start_from_filename(path)
    if week_start is None:
        print("  !! Could not read week start from filename — set WEEK_START. Skipping.")
        stats["file_errors"] += 1
        return
    if week_start.weekday() != 2:
        print(f"  !! Week start {week_start} is a {week_start.strftime('%A')}, "
              "not a Wednesday. Skipping.")
        stats["file_errors"] += 1
        return

    parsed = war_import.parse_workbook(path, week_start)
    office = parsed["office"]
    print(f"  Office: {office}  Week start: {week_start}")

    ins = rep = prot = skip = 0
    for date_str in sorted(parsed["days"]):
        rows = parsed["days"][date_str]
        for m in rows:
            name = m["name"]
            agent_id = find_agent(db, name)
            if agent_id is None:
                if not create_missing:
                    # Matches the upload endpoint: report rather than orphan. An
                    # agent created without an upline is invisible in every
                    # GA/MGA rollup, since visible_agent_ids() walks upline_id.
                    u = stats["unmatched"].setdefault(
                        name, {"rows": 0, "ga": m.get("ga"), "mga": m.get("mga")})
                    u["rows"] += 1
                    skip += 1
                    continue
                agent_id = (f"agent_dryrun_{name}" if dry_run
                            else create_agent(db, name, office))
                stats["created"].add(name)

            entry = war_import.build_entry(agent_id, office, date_str, m)
            existing = db.production_entries.find_one(
                {"agent_id": agent_id, "sales_day": date_str}
            )
            if dry_run and existing is None:
                # A dry run writes nothing, so an entry "written" by an earlier
                # file in this same run would not be found here — the two days
                # each report shares with the next would be double-counted as
                # new instead of as overlap updates. Track them ourselves so the
                # preview totals match what a live run would actually produce.
                key = (agent_id, date_str)
                if key in stats["simulated"]:
                    existing = {"source": war_import.WAR_IMPORT_SOURCE}
                else:
                    stats["simulated"].add(key)
            if existing is None:
                if not dry_run:
                    db.production_entries.insert_one(entry)
                ins += 1
            elif existing.get("source") == war_import.WAR_IMPORT_SOURCE:
                # Overlap rule: consecutive reports share two days via the
                # "(2)" tabs. The later file is authoritative, so replace.
                if not dry_run:
                    entry["entry_id"] = existing["entry_id"]
                    entry["updated_at"] = datetime.now(timezone.utc)
                    db.production_entries.replace_one(
                        {"entry_id": existing["entry_id"]}, entry)
                rep += 1
            else:
                # Never clobber an agent's own in-app submission.
                print(f"    ~ Protected (agent-submitted): {name} on {date_str}")
                prot += 1

    print(f"  → {ins} new, {rep} updated, {prot} protected, {skip} skipped")
    stats["inserted"] += ins
    stats["replaced"] += rep
    stats["protected"] += prot
    stats["skipped"] += skip


def collect_files(paths: List[str]) -> List[str]:
    """Expand the given paths (files or directories) into a sorted xlsx list.
    Falls back to backend/data/xlsx_war/ when nothing is given."""
    found: List[str] = []
    if not paths:
        paths = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xlsx_war")]
    for p in paths:
        if os.path.isdir(p):
            found += [os.path.join(p, f) for f in os.listdir(p)
                      if f.lower().endswith((".xlsx", ".xlsm"))]
        elif os.path.isfile(p):
            found.append(p)
        else:
            print(f"  !! Not found, skipping: {p}")
    # Chronological order matters: the later report is authoritative on the two
    # days it shares with the previous one, so it must be imported last.
    return sorted(found, key=lambda f: os.path.basename(f))


def main():
    ap = argparse.ArgumentParser(
        description="Import weekly WAR spreadsheets into MongoDB.")
    ap.add_argument("paths", nargs="*",
                    help="xlsx files and/or a directory of them "
                         "(default: backend/data/xlsx_war/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing anything")
    ap.add_argument("--create-missing", action="store_true",
                    help="create agents absent from the roster (they get no "
                         "upline, so they stay invisible in team rollups)")
    args = ap.parse_args()

    files = collect_files(args.paths)
    if not files:
        print("No xlsx files found.")
        sys.exit(1)

    print(f"{len(files)} file(s) to import, in date order:")
    for f in files:
        print(f"  {os.path.basename(f)}")

    print("\nConnecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    mode = "DRY RUN — nothing will be written" if args.dry_run else "LIVE — writing to the database"
    print(f"Connected to '{DB_NAME}'  [{mode}]")

    stats = {"inserted": 0, "replaced": 0, "protected": 0, "skipped": 0,
             "file_errors": 0, "unmatched": {}, "created": set(),
             "simulated": set()}
    for f in files:
        import_xlsx_file(db, f, stats,
                         dry_run=args.dry_run, create_missing=args.create_missing)

    print("\n" + "=" * 62)
    print(f"{'WOULD IMPORT' if args.dry_run else 'IMPORTED'}: "
          f"{stats['inserted']} new entries, "
          f"{stats['replaced']} updated by a later report")
    if stats["protected"]:
        print(f"  {stats['protected']} agent-submitted entries left untouched")
    if stats["created"]:
        print(f"  {len(stats['created'])} agents created (no upline set)")
    if stats["file_errors"]:
        print(f"  {stats['file_errors']} file(s) skipped — see messages above")

    if stats["unmatched"]:
        print(f"\n!! {len(stats['unmatched'])} AGENT(S) NOT ON THE ROSTER — "
              f"{stats['skipped']} rows skipped:")
        for name, u in sorted(stats["unmatched"].items()):
            up = u["ga"] or u["mga"] or "unknown upline"
            print(f"   • {name:28s} under {up}  ({u['rows']} days)")
        print("   Add them in the app (Admin → Add Person) with the correct")
        print("   upline, then re-run. Or pass --create-missing to force it.")

    if args.dry_run:
        print("\nNothing was written. Re-run without --dry-run to apply.")
    print("=" * 62)
    client.close()


if __name__ == "__main__":
    main()
