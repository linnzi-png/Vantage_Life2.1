"""
Link Users Script
Matches existing users records to agent_profiles by email and writes agent_id back.

Safe to run multiple times — already-linked users are skipped unless --force is passed.

Run from repo root:
    MONGO_URL="mongodb+srv://..." python backend/link_users.py

Windows PowerShell:
    $env:MONGO_URL = "mongodb+srv://..."
    python backend\link_users.py

Pass --force to overwrite existing agent_id links (use if an agent changed email):
    python backend\link_users.py --force
"""
import os
import sys
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")
FORCE = "--force" in sys.argv


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    # Build email → agent_profile lookup (lowercase + stripped keys)
    profiles = list(db.agent_profiles.find({}, {"_id": 0}))
    profile_by_email = {p["email"].strip().lower(): p for p in profiles if p.get("email")}
    print(f"Loaded {len(profile_by_email)} agent profiles\n")

    users = list(db.users.find({}, {"_id": 0}))
    linked = 0
    skipped = 0
    unmatched = 0

    for u in users:
        email = (u.get("email") or "").lower().strip()
        if not email:
            continue

        already_linked = bool(u.get("agent_id"))
        if already_linked and not FORCE:
            skipped += 1
            continue

        profile = profile_by_email.get(email)
        if not profile:
            print(f"  [NO MATCH] {email}")
            unmatched += 1
            continue

        db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": {
                "agent_id": profile["agent_id"],
                "role": profile["role"],
            }},
        )
        action = "RELINKED" if already_linked else "LINKED"
        print(f"  [{action}] {email} → {profile['name']} ({profile['role']}) | agent_id: {profile['agent_id']}")
        linked += 1

    print(f"\nDone. {linked} linked, {skipped} already linked (skipped), {unmatched} no match.")
    if unmatched:
        print("Unmatched users have no agent_profile with that email — add them to import_roster.py and re-run import_roster.py first.")
    client.close()


if __name__ == "__main__":
    main()
