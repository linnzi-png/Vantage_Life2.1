"""
Purge Seed Data Script
Removes all fake/seeded data while preserving real imported production data.

Safe to run multiple times (idempotent).

What it removes:
  - ALL historical_vault documents (all fake)
  - ALL shoutouts (all seeded)
  - ALL audit_log documents (all seeded)
  - production_entries with no 'source' field (seeded) or source not in real set
  - agent_profiles not referenced by any remaining production_entries

What it keeps:
  - production_entries with source = "war_xlsx_import" or "war_import"
  - agent_profiles that own those entries
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

    # 1. Drop historical vault (entirely fake)
    r = db.historical_vault.delete_many({})
    print(f"historical_vault: deleted {r.deleted_count} fake weeks")

    # 2. Drop shoutouts (seeded)
    r = db.shoutouts.delete_many({})
    print(f"shoutouts:        deleted {r.deleted_count} seeded shoutouts")

    # 3. Drop audit log (seeded)
    r = db.audit_log.delete_many({})
    print(f"audit_log:        deleted {r.deleted_count} seeded entries")

    # 4. Drop seeded production_entries (no source field, or source not real)
    r = db.production_entries.delete_many(
        {"source": {"$nin": list(REAL_SOURCES)}}
    )
    print(f"production_entries: deleted {r.deleted_count} seeded entries")

    # 5. Collect agent_ids still referenced by real entries, plus their uplines to preserve hierarchy
    real_agent_ids = set(
        db.production_entries.distinct("agent_id", {"source": {"$in": list(REAL_SOURCES)}})
    )
    active_uplines = set(
        db.agent_profiles.distinct("upline_id", {"agent_id": {"$in": list(real_agent_ids)}})
    )
    agents_to_keep = real_agent_ids.union(active_uplines) - {None}
    print(f"\nReal active agents and uplines to keep: {len(agents_to_keep)}")

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
