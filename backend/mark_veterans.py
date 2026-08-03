"""
Mark Confirmed Veterans

One-time tenure import for the roster spreadsheet ("AO agents for VantageLife 2.0").
Exactly 13 agents were explicitly marked Veteran by leadership; the other 38 rows
have a blank tenure column, and leadership confirmed blank means UNKNOWN — not
rookie, not veteran. Tenure is never inferred, so this script:

  * sets is_rookie = False ONLY on the 13 confirmed veterans below (matched by
    email, the roster's stable key), and
  * touches nobody else — the 38 unknown-tenure agents keep no is_rookie field
    and show as "Tenure unknown" in the Admin screen until leadership records
    each one explicitly (Admin Panel -> person -> TENURE).

Idempotent: re-running skips agents whose tenure is already recorded.
Every change writes an audit_log entry.

Run from repo root (dry run by default; add --apply to write):
    MONGO_URL="mongodb+srv://..." python backend/mark_veterans.py
    MONGO_URL="mongodb+srv://..." python backend/mark_veterans.py --apply
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("DB_NAME", os.environ.get("MONGO_DB", "vantagelife"))

# The 13 confirmed veterans (leadership's explicit list, 2026-07). Emails match
# the roster rows in import_roster.py.
CONFIRMED_VETERAN_EMAILS = {
    "mj@aopremier.com":             "Mohamed (MJ) Aljahmi",
    "monty@aopremier.com":          "Montzer Alwatan",
    "ccook.ao@gmail.com":           "Connor Cook",
    "jennysolis1624@gmail.com":     "Jeannieliza Solis",
    "ali@aopremier.com":            "Ali Musa",
    "aeltanoukhi@gmail.com":        "Ali Eltanoukhi",
    "henry@aopremier.com":          "Henry Long",
    "snoor.qaradaghi@gmail.com":    "Snoor Qaradaghi",
    "landy.sitto.ali@gmail.com":    "Landy Sitto",
    "alex.murshed@gmail.com":       "Aleskandar Murshed",
    "maheraltairi@outlook.com":     "Maher Altairi",
    "mattbostic.ao@gmail.com":      "Matthew Bostic",
    "adamyoussef366@gmail.com":     "Adam Youssef",
}


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (no writes — add --apply to write)'}")
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    now = datetime.now(timezone.utc)
    marked, already, missing = [], [], []

    for email, display_name in CONFIRMED_VETERAN_EMAILS.items():
        agent = db.agent_profiles.find_one({"email": email}, {"_id": 0})
        if not agent:
            missing.append((display_name, email))
            print(f"  [MISSING] {display_name} <{email}> — not on the roster; NOT created (tenure import never creates profiles)")
            continue
        if "is_rookie" in agent:
            already.append(display_name)
            print(f"  [SKIP]    {agent['name']} — tenure already recorded (is_rookie={agent['is_rookie']})")
            continue
        if apply:
            db.agent_profiles.update_one(
                {"agent_id": agent["agent_id"]},
                {"$set": {"is_rookie": False, "updated_at": now}},
            )
            db.audit_log.insert_one({
                "audit_id": f"au_{uuid.uuid4().hex[:10]}",
                "ts": now,
                "action": "set_tenure",
                "agent_id": agent["agent_id"],
                "agent_name": agent["name"],
                "changed_by": "mark_veterans.py",
                "changed_by_name": "Veteran import script (leadership's confirmed-13 list)",
                "original_value": None,
                "new_value": False,
            })
        marked.append(agent["name"])
        print(f"  [{'VETERAN' if apply else 'WOULD MARK'}] {agent['name']} <{email}>")

    unknown_count = db.agent_profiles.count_documents({"is_rookie": {"$exists": False}})
    print(f"\nDone. {len(marked)} marked veteran, {len(already)} already recorded, {len(missing)} not found.")
    print(f"{unknown_count} agents still have NO recorded tenure — deliberately untouched.")
    print("Blank tenure means unknown: record each via Admin Panel -> person -> TENURE.")
    client.close()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
