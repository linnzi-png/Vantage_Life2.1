"""
Create / Update Authorized Users Script
Upserts user records so specific email addresses can log in with a given role.
Also creates and links an agent_profile for each user so they can enter Pulse numbers.

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
DB_NAME = os.environ.get("DB_NAME", "vantagelife")

# ── ADD YOUR USERS HERE ────────────────────────────────────────────
# (email, display_name, role, office, phone)
# role choices: "level_1" (Agent), "level_2" (GA), "level_3" (MGA), "level_4" (RGA)
# office: the RGA office name this person belongs to (e.g. "Gojcaj RGA", "MJ RGA")
# phone: cell number as a string, e.g. "3135550100" (used for notifications)
USERS = [
    ("mj@aopremier.com",  "MJ Aljahmi", "level_4", "MJ RGA",  "3135550101"),
    ("linnzi@aoluxor.com", "Linnzi Ek", "level_4", "MJ RGA",  "3609109934"),
    ("noetimothy1114@gmail.com", "Timothy Noe", "level_2", "Gojcaj RGA", "8589512244"),
]
# ───────────────────────────────────────────────────────────────────────────


VALID_ROLES = {"level_1", "level_2", "level_3", "level_4"}


def get_or_create_agent(db, name: str, role: str, office: str, phone: str, email: str) -> str:
    """Return existing agent_id or create a new agent_profile.

    email is required here (not just on the users record) because sign-in
    re-derives role/agent_id from agent_profiles by email on every login —
    without it, the very next Google sign-in would reset this user back to
    role "pending".
    """
    existing = db.agent_profiles.find_one({"name": name}, {"_id": 0})
    if existing:
        db.agent_profiles.update_one(
            {"name": name},
            {"$set": {"office": office, "role": role, "phone": phone, "email": email}},
        )
        return existing["agent_id"]
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    db.agent_profiles.insert_one({
        "agent_id": agent_id,
        "name": name,
        "office": office,
        "role": role,
        "phone": phone,
        "email": email,
        "upline_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return agent_id


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Could not connect to MongoDB — {e}")
        client.close()
        return
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    for email, name, role, office, phone in USERS:
        email = email.lower().strip()
        if role not in VALID_ROLES:
            print(f"  [SKIP] {email} — invalid role '{role}' (must be one of {sorted(VALID_ROLES)})")
            continue

        # Ensure agent profile exists and get its ID
        agent_id = get_or_create_agent(db, name, role, office, phone, email)

        existing = db.users.find_one({"email": email}, {"_id": 0})
        if existing:
            db.users.update_one(
                {"email": email},
                {"$set": {"role": role, "name": name, "phone": phone, "agent_id": agent_id}},
            )
            print(f"  [UPDATED] {email} → {role} | office: {office} | phone: {phone}")
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "name": name,
                "phone": phone,
                "picture": "",
                "role": role,
                "agent_id": agent_id,
                "created_at": datetime.now(timezone.utc),
            })
            print(f"  [CREATED] {email} → {role} | office: {office} | phone: {phone}")

    print(f"\nDone. {len(USERS)} user(s) processed.")
    print("They can now log in with Google and enter Pulse numbers.")
    client.close()


if __name__ == "__main__":
    main()
