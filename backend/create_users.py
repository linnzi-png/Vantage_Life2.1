"""
Create / Update Authorized Users Script
Upserts user records so specific email addresses can log in with a given role.

Roles:  level_1 = Agent   level_2 = GA   level_3 = MGA   level_4 = RGA

Add the users you want to USERS below, then run:
    MONGO_URL="mongodb+srv://..." python backend/create_users.py

Windows PowerShell:
    $env:MONGO_URL = "mongodb+srv://..."
    python backend\create_users.py
"""
import os
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "vantagelife")

# ── ADD YOUR USERS HERE ──────────────────────────────────────────────────────
# (email, display_name, role)
# role choices: "level_1" (Agent), "level_2" (GA), "level_3" (MGA), "level_4" (RGA)
USERS = [
    ("alice@example.com", "Alice Smith",  "level_1"),
    ("bob@example.com",   "Bob Johnson",  "level_2"),
]
# ─────────────────────────────────────────────────────────────────────────────


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    for email, name, role in USERS:
        existing = db.users.find_one({"email": email}, {"_id": 0})
        if existing:
            db.users.update_one(
                {"email": email},
                {"$set": {"role": role, "name": name}},
            )
            print(f"  [UPDATED] {email} → {role} ({name})")
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "name": name,
                "picture": "",
                "role": role,
                "agent_id": None,
                "created_at": datetime.now(timezone.utc),
            })
            print(f"  [CREATED] {email} → {role} ({name})")

    print(f"\nDone. {len(USERS)} user(s) processed.")
    print("They can now log in with Google using those email addresses.")
    client.close()


if __name__ == "__main__":
    main()
