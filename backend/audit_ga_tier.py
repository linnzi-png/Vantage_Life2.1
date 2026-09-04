"""
Audit (and fix) GAs sitting at MGA tier

The Team tab's "Add Team Member" sheet sent role `level_3` for the GA chip, so
every GA onboarded through it was created one tier too high — seeing production
rollups for their whole branch instead of just their own team. The code path is
fixed (frontend/src/components/AddTeamMemberSheet.tsx, PR #101), but that only
stops NEW ones: anyone already created that way is still at level_3 today.

GA is a level_2 title everywhere else — CLAUDE.md ("level_2 GA (General Agent)";
level_3 is MGA) and import_roster.py, which seeds all three production GAs at
level_2 alongside the SAs.

What this reports:
  * AFFECTED — role level_3 with a GA-ish io_role. These are the over-grants.
  * REVIEW   — every other level_3, listed so you can confirm each is a real
               MGA. Nothing here is touched; it is context for your eyes.

What --apply changes, per affected agent:
  * agent_profiles.role -> "level_2"   (the source of truth)
  * users.role          -> "level_2"   (matched by email, so the change takes
                                        effect without waiting for a re-login —
                                        same sync /admin/update-person does)
  * one audit_log entry

Titles (io_role) are left alone: the title was never wrong, the tier was.
Upline links are left alone: a GA's placement in the ladder does not change.

Idempotent: an agent already at level_2 is not matched, so re-running is a
no-op. Archived agents are skipped (they cannot sign in).

Run from repo root (dry run by default; add --apply to write):
    MONGO_URL="mongodb+srv://..." python backend/audit_ga_tier.py
    MONGO_URL="mongodb+srv://..." python backend/audit_ga_tier.py --apply
"""
import os
import sys
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("DB_NAME", os.environ.get("MONGO_DB", "vantagelife"))

# The tier a GA should hold, and the one the buggy sheet handed out.
CORRECT_ROLE = "level_2"
WRONG_ROLE = "level_3"

# io_role spellings that mean "GA". Matched case-insensitively: the value is
# free text on the profile (see _roster_add_person), so a hand-entered "ga"
# counts. "MGA" must NOT match — an MGA at level_3 is correct — so comparison
# is exact against this set rather than a substring test, which "MGA".find("GA")
# would wrongly satisfy.
GA_TITLES = {"ga", "general agent"}

# Archived profiles cannot sign in, so their role grants nothing (see
# ACTIVE_AGENT / upsert_user_and_session in server.py).
ACTIVE = {"archived": {"$ne": True}}


def is_ga_title(io_role) -> bool:
    return str(io_role or "").strip().lower() in GA_TITLES


def describe(a: dict) -> str:
    return (
        f"  {a.get('name', '?'):<28} "
        f"{str(a.get('io_role') or '—'):<8} "
        f"{a.get('role', '?'):<8} "
        f"{str(a.get('office') or '—'):<12} "
        f"{str(a.get('email') or 'no email')}"
    )


def main() -> None:
    apply = "--apply" in sys.argv

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]

    level_3 = list(db.agent_profiles.find({"role": WRONG_ROLE, **ACTIVE}, {"_id": 0}))
    affected = [a for a in level_3 if is_ga_title(a.get("io_role"))]
    others = [a for a in level_3 if not is_ga_title(a.get("io_role"))]

    header = f"  {'NAME':<28} {'TITLE':<8} {'TIER':<8} {'OFFICE':<12} EMAIL"

    print(f"\n{len(level_3)} active agent(s) at {WRONG_ROLE} (MGA tier).\n")

    print(f"AFFECTED — GA title at MGA tier, should be {CORRECT_ROLE}: {len(affected)}")
    if affected:
        print(header)
        for a in affected:
            print(describe(a))
    else:
        print("  (none — nothing to correct)")

    print(f"\nREVIEW — other {WRONG_ROLE} agents, NOT touched: {len(others)}")
    if others:
        print(header)
        for a in others:
            print(describe(a))
        print("\n  Confirm each of these is a real MGA. If one of them is a GA")
        print("  under a different title spelling, add it to GA_TITLES and re-run.")
    else:
        print("  (none)")

    if not affected:
        print("\nNothing to do.")
        client.close()
        return

    if not apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply to set these "
              f"{len(affected)} agent(s) to {CORRECT_ROLE}.")
        client.close()
        return

    print(f"\nApplying: {len(affected)} agent(s) -> {CORRECT_ROLE} ...")
    now = datetime.now(timezone.utc)
    changed = 0
    for a in affected:
        agent_id = a["agent_id"]
        db.agent_profiles.update_one(
            {"agent_id": agent_id},
            {"$set": {"role": CORRECT_ROLE, "updated_at": now}},
        )
        # Sync any linked login so the tier drops immediately rather than at
        # their next sign-in — mirrors /admin/update-person in server.py.
        email = str(a.get("email") or "").lower().strip()
        if email:
            db.users.update_many(
                {"email": email}, {"$set": {"role": CORRECT_ROLE}}
            )
        db.audit_log.insert_one({
            "audit_id": f"au_{uuid.uuid4().hex[:10]}",
            "ts": now,
            "action": "fix_ga_tier",
            "agent_id": agent_id,
            "agent_name": a.get("name"),
            "from_role": WRONG_ROLE,
            "role": CORRECT_ROLE,
            "reason": "GA created at MGA tier by the Team tab add-member sheet",
        })
        changed += 1
        print(f"  [OK] {a.get('name')} -> {CORRECT_ROLE}")

    print(f"\nDone. {changed} agent(s) corrected.")
    client.close()


if __name__ == "__main__":
    main()
