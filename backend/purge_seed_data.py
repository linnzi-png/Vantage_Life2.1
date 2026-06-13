"""
Purge Seed Data Script
Removes all fake/seeded data while preserving real imported production data.

Safe to run multiple times (idempotent).

What it removes:
  - ALL historical_vault documents (all fake)
  - ALL shoutouts (all seeded)
  - ALL audit_log documents (all seeded)
  - production_entries where source is explicitly set but not in real set
  - agent_profiles not referenced by any remaining production_entries,
    their uplines, or existing user records

What it keeps:
  - production_entries with source = "war_xlsx_import" or "war_import"
  - production_entries with no source field (live app submissions)
  - agent_profiles that own those entries, their uplines, and any profile
    linked from a users record
  - users and user_sessions (untouched)

Run from repo root:
    pip install pymongo dnspython
    MONGO_URL="mongodb+srv://..." python backend/purge_seed_data.py
"""
import os
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")

REAL_SOURCES = {"war_xlsx_import", "war_import"}


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    confirm = input(
        f"WARNING: This will purge all seed data from database '{DB_NAME}'.\n"
        "App-created entries (no source field) are preserved.\n"
        "Are you sure? (yes/no): "
    )
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        client.close()
        return

    # 1. Drop historical vault (entirely fake)
    r = db.historical_vault.delete_many({})
    print(f"historical_vault: deleted {r.deleted_count} fake weeks")

    # 2. Drop shoutouts (seeded)
    r = db.shoutouts.delete_many({})
    print(f"shoutouts:        deleted {r.deleted_count} seeded shoutouts")

    # 3. Drop audit log (seeded)
    r = db.audit_log.delete_many({})
    print(f"audit_log:        deleted {r.deleted_count} seeded entries")

    # 4. Drop seeded production_entries (source explicitly set but not real).
    # Entries without a source field are live app submissions — never delete them.
    r = db.production_entries.delete_many(
        {"source": {"$exists": True, "$nin": list(REAL_SOURCES)}}
    )
    print(f"production_entries: deleted {r.deleted_count} seeded entries")

    # 5. Collect agent_ids still referenced by real entries, plus their uplines
    #    and any profile already linked from a users record to prevent dangling refs.
    real_agent_ids = set(
        db.production_entries.distinct("agent_id", {"source": {"$in": list(REAL_SOURCES)}})
    )
    active_uplines = set(
        db.agent_profiles.distinct("upline_id", {"agent_id": {"$in": list(real_agent_ids)}})
    )
    user_linked_ids = set(
        a for a in db.users.distinct("agent_id") if a
    )
    agents_to_keep = real_agent_ids.union(active_uplines).union(user_linked_ids) - {None}
    print(f"\nProfiles to keep: {len(agents_to_keep)} "
          f"({len(real_agent_ids)} producers, {len(active_uplines)} uplines, "
          f"{len(user_linked_ids)} user-linked)")

    # 6. Drop agent_profiles not in that set
    r = db.agent_profiles.delete_many({"agent_id": {"$nin": list(agents_to_keep)}})
    print(f"agent_profiles: deleted {r.deleted_count} synthetic agents")

    # Summary
    remaining_entries = db.production_entries.count_documents({})
    remaining_agents = db.agent_profiles.count_documents({})
    print(f"\nDone.")
    print(f"  Remaining production_entries : {remaining_entries}")
    print(f"  Remaining agent_profiles     : {remaining_agents}")
    client.close()


if __name__ == "__main__":
    main()
