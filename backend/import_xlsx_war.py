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
import re
import sys
import os
from datetime import datetime, timezone, date

from pymongo import MongoClient

import war_import

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")

# Optional override; normally the week start comes from the filename.
try:
    WEEK_START_OVERRIDE = date.fromisoformat(os.environ["WEEK_START"])
except (KeyError, ValueError):
    WEEK_START_OVERRIDE = None


def get_or_create_agent(db, name: str, office: str) -> str:
    existing = db.agent_profiles.find_one(
        {"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}}
    )
    if existing:
        return existing["agent_id"]
    import uuid
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    db.agent_profiles.insert_one({
        "agent_id": agent_id,
        "name": name.strip(),
        "office": office,
        "role": "level_1",
        "upline_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"    + Created agent: {name} ({agent_id})")
    return agent_id


def import_xlsx_file(db, path: str) -> tuple[int, int, int]:
    print(f"\nProcessing {os.path.basename(path)} ...")
    week_start = WEEK_START_OVERRIDE or war_import.week_start_from_filename(path)
    if week_start is None:
        print("  !! Could not read week start from filename — set WEEK_START. Skipping.")
        return (0, 0, 0)
    if week_start.weekday() != 2:
        print(f"  !! Week start {week_start} is a {week_start.strftime('%A')}, "
              "not a Wednesday. Skipping.")
        return (0, 0, 0)

    parsed = war_import.parse_workbook(path, week_start)
    office = parsed["office"]
    print(f"  Office: {office}  Week start: {week_start}")

    inserted = replaced = protected = 0
    for date_str in sorted(parsed["days"]):
        rows = parsed["days"][date_str]
        print(f"  {date_str}: {len(rows)} agents with activity")
        for m in rows:
            agent_id = get_or_create_agent(db, m["name"], office)
            entry = war_import.build_entry(agent_id, office, date_str, m)
            existing = db.production_entries.find_one(
                {"agent_id": agent_id, "sales_day": date_str}
            )
            if existing is None:
                db.production_entries.insert_one(entry)
                inserted += 1
            elif existing.get("source") == war_import.WAR_IMPORT_SOURCE:
                # Overlap rule: consecutive reports share two days via the
                # "(2)" tabs. The later file is authoritative, so replace.
                entry["entry_id"] = existing["entry_id"]
                entry["updated_at"] = datetime.now(timezone.utc)
                db.production_entries.replace_one({"entry_id": existing["entry_id"]}, entry)
                replaced += 1
            else:
                # Never clobber an agent's own in-app submission.
                print(f"    ~ Protected (agent-submitted): {m['name']} on {date_str}")
                protected += 1

    return (inserted, replaced, protected)


def main():
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        xlsx_dir = os.path.join(os.path.dirname(__file__), "data", "xlsx_war")
        if os.path.isdir(xlsx_dir):
            files = [
                os.path.join(xlsx_dir, f)
                for f in sorted(os.listdir(xlsx_dir))
                if f.endswith(".xlsx")
            ]
        else:
            print("Usage: python import_xlsx_war.py file1.xlsx file2.xlsx ...")
            print("  Or place files in backend/data/xlsx_war/ and run without args.")
            sys.exit(1)

    if not files:
        print("No xlsx files found.")
        sys.exit(1)

    # Chronological order matters: the later report is authoritative on the two
    # days it shares with the previous one, so it must be imported last.
    files = sorted(files, key=lambda f: os.path.basename(f))

    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    tot_i = tot_r = tot_p = 0
    for f in files:
        i, r, p = import_xlsx_file(db, f)
        print(f"  → {i} inserted, {r} replaced, {p} protected")
        tot_i += i
        tot_r += r
        tot_p += p

    print(f"\nDone. {tot_i} inserted, {tot_r} replaced (overlap corrections), "
          f"{tot_p} protected (agent-submitted, left untouched).")
    client.close()


if __name__ == "__main__":
    main()
