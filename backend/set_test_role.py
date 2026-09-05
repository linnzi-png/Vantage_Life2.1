"""
Set a user's role for testing — flip an existing roster member between tiers.

Use this to let one real person (e.g. a QA tester on their own Google login)
walk the system at every access level, one level at a time. It updates BOTH
the agent_profiles record and the users record by email, so the change sticks
across the next Google sign-in (sign-in re-derives role from agent_profiles by
email — if only the users record were changed, the next login would reset it).

The person must already exist in the roster (run create_users.py first).

Roles:  level_1 = Agent   level_2 = GA   level_3 = MGA   level_4 = RGA

Usage:
    PowerShell:
        $env:MONGO_URL = "mongodb+srv://..."
        python backend/set_test_role.py <email> <level>

    bash / zsh:
        MONGO_URL="mongodb+srv://..." python backend/set_test_role.py <email> <level>

Example — make Timothy an RGA for a pass, then drop him to Agent:
    PowerShell:
        $env:MONGO_URL = "mongodb+srv://..."
        python backend/set_test_role.py noetimothy1114@gmail.com level_4
        python backend/set_test_role.py noetimothy1114@gmail.com level_1

    bash / zsh:
        MONGO_URL="mongodb+srv://..." python backend/set_test_role.py noetimothy1114@gmail.com level_4
        MONGO_URL="mongodb+srv://..." python backend/set_test_role.py noetimothy1114@gmail.com level_1

After running, the tester signs out and back in (or reloads the app) so the
client picks up the new level.
"""
import os
import sys
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("DB_NAME", "vantagelife")

VALID_ROLES = {"level_1", "level_2", "level_3", "level_4"}
ROLE_LABELS = {"level_1": "Agent", "level_2": "GA", "level_3": "MGA", "level_4": "RGA"}


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python backend/set_test_role.py <email> <level_1|level_2|level_3|level_4>")
        sys.exit(1)

    email = sys.argv[1].lower().strip()
    role = sys.argv[2].strip()

    if role not in VALID_ROLES:
        print(f"ERROR: invalid role '{role}' — must be one of {sorted(VALID_ROLES)}")
        sys.exit(1)

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Could not connect to MongoDB — {e}")
        client.close()
        sys.exit(1)
    db = client[DB_NAME]

    agent = db.agent_profiles.find_one({"email": email}, {"_id": 0})
    if not agent:
        print(f"ERROR: no agent_profile with email '{email}'. Run create_users.py first.")
        client.close()
        sys.exit(1)

    db.agent_profiles.update_one({"email": email}, {"$set": {"role": role}})
    # Keep the users record in sync and ensure it is linked to the agent_id.
    db.users.update_one(
        {"email": email},
        {"$set": {"role": role, "agent_id": agent.get("agent_id")}},
    )

    label = ROLE_LABELS[role]
    print(f"OK: {agent.get('name', email)} is now {role} ({label}).")
    print("The tester should sign out and back in (or reload the app) to pick up the change.")
    client.close()


if __name__ == "__main__":
    main()
