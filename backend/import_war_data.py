"""
WAR Data Import Script
Loads all backend/data/war/*.json files into MongoDB production_entries.
Run from the backend/ directory:
    pip install pymongo dnspython
    python import_war_data.py
"""
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

MONGO_URL = "mongodb+srv://linnzi_db_user:Wy7fahxb9Gfp9xh2@vantagelife.r5atbyt.mongodb.net/"
DB_NAME = "vantagelife"
WAR_DIR = os.path.join(os.path.dirname(__file__), "data", "war")

DETROIT_OFFSET = timedelta(hours=-4)  # EDT

def detroit_submit_time(date_str: str) -> datetime:
    """Return 8:30 PM Detroit time on the given date as UTC datetime."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    local = d.replace(hour=20, minute=30, tzinfo=timezone(DETROIT_OFFSET))
    return local.astimezone(timezone.utc)


def get_or_create_agent(db, name: str, office: str) -> str:
    """Return existing agent_id or create a new agent profile."""
    existing = db.agent_profiles.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if existing:
        return existing["agent_id"]
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    db.agent_profiles.insert_one({
        "agent_id": agent_id,
        "name": name,
        "office": office,
        "role": "level_1",
        "upline_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"  Created agent: {name} ({agent_id})")
    return agent_id


def make_entry(agent_id: str, office: str, date_str: str, p: dict) -> dict:
    """Build a production_entries document from WAR performance row."""
    gross_alp = float(p.get("alp", p.get("gross_alp", 0)) or 0)
    return {
        "entry_id": f"pe_{uuid.uuid4().hex[:12]}",
        "agent_id": agent_id,
        "office": office,
        "sales_day": date_str,
        "sets": int(p.get("sets", 0) or 0),
        "sits": int(p.get("sits", 0) or 0),
        "sales": int(p.get("sales", 0) or 0),
        "ots_sits": int(p.get("ots_sits", p.get("os_sits", 0)) or 0),
        "ots_sales": int(p.get("ots_sales", p.get("os_sales", 0)) or 0),
        "n1": int(p.get("n1", p.get("n1_count", 0)) or 0),
        "refs_obtained": int(p.get("refs_obtained", p.get("referrals", p.get("ref_obtained", 0))) or 0),
        "ref_sits": int(p.get("ref_sits", 0) or 0),
        "ref_sales": int(p.get("ref_sales", 0) or 0),
        "pos_sits": int(p.get("pos_sits", 0) or 0),
        "pos_sales": int(p.get("pos_sales", 0) or 0),
        "vet_sits": int(p.get("vet_sits", 0) or 0),
        "vet_sales": int(p.get("vet_sales", 0) or 0),
        "gross_alp": gross_alp,
        "net_alp": gross_alp,
        "submitted_at": detroit_submit_time(date_str),
        "submitted_on_time": True,  # historical import — treat as on-time
        "is_adjustment": False,
        "source": "war_import",
    }


def import_daily_format(db, data: dict) -> int:
    """Handle ashley_rust / mj weekly_tabs format (daily breakdown)."""
    meta = data.get("report_metadata", {})
    office = meta.get("rga_office", meta.get("office_branding", "Unknown"))
    inserted = 0
    for tab in data.get("weekly_tabs", []):
        date_str = tab.get("date")
        if not date_str or not tab.get("performance"):
            continue
        for p in tab["performance"]:
            name = p.get("agent", "").strip()
            if not name:
                continue
            # Skip if entry already exists for this agent+date
            existing = db.production_entries.find_one({
                "sales_day": date_str,
                "source": "war_import",
            })
            # More specific check by agent name lookup
            agent_id = get_or_create_agent(db, name, office)
            if db.production_entries.find_one({"agent_id": agent_id, "sales_day": date_str}):
                print(f"  Skipping duplicate: {name} on {date_str}")
                continue
            entry = make_entry(agent_id, office, date_str, p)
            db.production_entries.insert_one(entry)
            inserted += 1
            print(f"  Inserted: {name} | {date_str} | ALP ${entry['gross_alp']:,.0f}")
    return inserted


def import_weekly_summary_format(db, data: dict) -> int:
    """Handle monty weekly summary format (totals only, no daily breakdown)."""
    office = data.get("office", "Unknown")
    week_ending = data.get("week_ending")
    if not week_ending:
        print("  No week_ending date — skipping")
        return 0
    inserted = 0
    for agent_data in data.get("agents", []):
        name = agent_data.get("name", "").strip()
        if not name:
            continue
        metrics = agent_data.get("metrics", {})
        agent_id = get_or_create_agent(db, name, office)
        if db.production_entries.find_one({"agent_id": agent_id, "sales_day": week_ending}):
            print(f"  Skipping duplicate: {name} on {week_ending}")
            continue
        entry = make_entry(agent_id, office, week_ending, metrics)
        db.production_entries.insert_one(entry)
        inserted += 1
        print(f"  Inserted: {name} | {week_ending} | ALP ${entry['gross_alp']:,.0f}")
    return inserted


def main():
    print(f"Connecting to MongoDB...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    total = 0
    files = sorted(f for f in os.listdir(WAR_DIR) if f.endswith(".json"))
    for filename in files:
        path = os.path.join(WAR_DIR, filename)
        print(f"Processing {filename}...")
        with open(path) as f:
            data = json.load(f)

        # Detect format
        if "weekly_tabs" in data:
            count = import_daily_format(db, data)
        elif "agents" in data:
            count = import_weekly_summary_format(db, data)
        else:
            print(f"  Unknown format — skipping")
            count = 0

        print(f"  → {count} entries inserted\n")
        total += count

    print(f"Done. Total entries inserted: {total}")
    client.close()


if __name__ == "__main__":
    main()
