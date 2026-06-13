"""
Vault Backfill Script
Builds historical_vault entries from real production_entries data.

The vault normally gets populated by the Wednesday reset process.
Run this once to backfill all historical weeks from imported WAR data.

Safe to run multiple times — skips weeks already in the vault.

Run from repo root:
    MONGO_URL="mongodb+srv://..." python backend/backfill_vault.py

Windows PowerShell:
    $env:MONGO_URL = "mongodb+srv://..."
    python backend\backfill_vault.py
"""
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")


def week_start_for(day_str: str) -> str:
    """Return the Wednesday on-or-before the given sales_day (YYYY-MM-DD)."""
    d = date.fromisoformat(day_str)
    # weekday(): Mon=0 ... Wed=2 ... Sun=6
    days_since_wed = (d.weekday() - 2) % 7
    return (d - timedelta(days=days_since_wed)).isoformat()


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    # Load all real production entries
    entries = list(db.production_entries.find(
        {"source": {"$in": ["war_xlsx_import", "war_import"]}},
        {"_id": 0, "sales_day": 1, "office": 1,
         "gross_alp": 1, "net_alp": 1, "sits": 1, "sales": 1, "agent_id": 1}
    ))
    print(f"Found {len(entries)} real production entries\n")

    # Group by week_start
    weeks: dict = defaultdict(lambda: {
        "totals": defaultdict(float),
        "by_office": defaultdict(lambda: defaultdict(float)),
        "agent_ids": set(),
    })

    for e in entries:
        ws = week_start_for(e["sales_day"])
        w = weeks[ws]
        w["totals"]["gross_alp"] += float(e.get("gross_alp") or 0)
        w["totals"]["net_alp"]   += float(e.get("net_alp") or 0)
        w["totals"]["sits"]      += int(e.get("sits") or 0)
        w["totals"]["sales"]     += int(e.get("sales") or 0)
        office = e.get("office", "Unknown")
        w["by_office"][office]["gross_alp"] += float(e.get("gross_alp") or 0)
        w["by_office"][office]["net_alp"]   += float(e.get("net_alp") or 0)
        w["by_office"][office]["sits"]      += int(e.get("sits") or 0)
        w["by_office"][office]["sales"]     += int(e.get("sales") or 0)
        if e.get("agent_id"):
            w["agent_ids"].add(e["agent_id"])

    inserted = 0
    skipped = 0

    for ws, data in sorted(weeks.items()):
        if db.historical_vault.find_one({"week_start": ws}):
            print(f"  [SKIP] {ws} — already in vault")
            skipped += 1
            continue

        active_agents = data["agent_ids"]

        totals = {k: (int(v) if k in ("sits", "sales") else round(v, 2))
                  for k, v in data["totals"].items()}

        by_office = {
            office: {k: (int(v) if k in ("sits", "sales") else round(v, 2))
                     for k, v in metrics.items()}
            for office, metrics in data["by_office"].items()
        }

        doc = {
            "week_id": f"wk_{uuid.uuid4().hex[:8]}",
            "week_start": ws,
            "archived_at": datetime.now(timezone.utc),
            "totals": totals,
            "by_office": by_office,
            "agent_count": len(active_agents),
        }
        db.historical_vault.insert_one(doc)
        print(f"  [OK]   {ws} | ALP ${totals['gross_alp']:,.0f} | "
              f"{totals['sales']} sales | {len(by_office)} offices")
        inserted += 1

    print(f"\nDone. Inserted {inserted} vault weeks, skipped {skipped}.")
    client.close()


if __name__ == "__main__":
    main()
