"""
Audit (and fix) GAs sitting at MGA tier

The Team tab's "Add Team Member" sheet sent role `level_3` for the GA chip, so
every GA onboarded through it was created one tier too high — seeing production
rollups for their whole branch instead of just their own team. The code path is
fixed (frontend/src/components/AddTeamMemberSheet.tsx, PR #101), but that only
stops NEW ones: anyone already created that way is still at level_3.

GA is a level_2 title everywhere else — CLAUDE.md ("level_2 GA (General Agent)";
level_3 is MGA) and import_roster.py, which seeds all three production GAs at
level_2 alongside the SAs.

WHY "level_3 + GA title" IS NOT ENOUGH ON ITS OWN
-------------------------------------------------
Tier and title are edited independently (/admin/set-role, /admin/update-person),
and titles are display-only — CLAUDE.md already has Partner and Senior Partner
riding on level_3/level_4 holders. So an admin may have deliberately promoted a
GA to MGA tier and left the GA title in place. Demoting that person would strip
access they are meant to have, which is a worse outcome than the bug.

Neither role-changing route writes an audit_log entry, so a promotion leaves no
trace of itself. What IS recorded is creation: _roster_add_person writes an
"add_agent" entry carrying the role the agent was created with. That splits the
population usefully, because the bug creates people AT level_3 whereas a
promotion moves them there later:

  LIKELY BUG — created at level_3. The buggy chip's signature. --apply fixes
               these.
  PROMOTED   — created below level_3, so a later deliberate admin action put
               them here. Never auto-demoted; listed so you can see them.
  UNCERTAIN  — no add_agent entry (seeded by import_roster.py, or created
               before that audit existed). Not auto-demoted; opt in per agent
               with --include once you have confirmed it.

Also reported: every OTHER level_3 agent (non-GA title), untouched, so a real
MGA is never silently swept up and a GA under an unexpected title spelling is
visible rather than missed.

What --apply changes, per eligible agent:
  * agent_profiles.role -> "level_2"   (the source of truth)
  * users.role          -> "level_2"   (matched by email, so the change takes
                                        effect without waiting for a re-login —
                                        the same sync /admin/update-person does)
  * one audit_log entry

Titles (io_role) are left alone: the title was never wrong, the tier was.
Upline links are left alone: a GA's placement in the ladder does not change.

Idempotent: an agent already at level_2 is not matched, so re-running is a
no-op. Archived agents are skipped (they cannot sign in).

Run from repo root (dry run by default; add --apply to write):
    PowerShell:
        $env:MONGO_URL = "mongodb+srv://..."
        python backend/audit_ga_tier.py
        python backend/audit_ga_tier.py --apply
        python backend/audit_ga_tier.py --apply --include agent_abc123 agent_def456

    bash / zsh:
        MONGO_URL="mongodb+srv://..." python backend/audit_ga_tier.py
        MONGO_URL="mongodb+srv://..." python backend/audit_ga_tier.py --apply
        MONGO_URL="mongodb+srv://..." python backend/audit_ga_tier.py --apply --include agent_abc123 agent_def456
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

LIKELY_BUG, PROMOTED, UNCERTAIN = "LIKELY BUG", "PROMOTED", "UNCERTAIN"


def is_ga_title(io_role) -> bool:
    return str(io_role or "").strip().lower() in GA_TITLES


def level_of(role) -> int:
    """level_N -> N, and 0 for anything outside that ladder (e.g. finance_admin)."""
    try:
        return int(str(role).split("_")[1])
    except (IndexError, ValueError):
        return 0


def classify(db, agent: dict) -> tuple:
    """(bucket, note) for a level_3 GA-titled agent, from its creation record."""
    entry = db.audit_log.find_one(
        {"action": "add_agent", "agent_id": agent["agent_id"]}, sort=[("ts", 1)]
    )
    if not entry:
        return UNCERTAIN, "no creation record"

    created_role = entry.get("role")
    by = entry.get("changed_by_name") or entry.get("changed_by") or "unknown"
    when = str(entry.get("ts") or "")[:10]

    if created_role == WRONG_ROLE:
        return LIKELY_BUG, f"created at {WRONG_ROLE} by {by} on {when}"
    if level_of(created_role) < level_of(WRONG_ROLE):
        return PROMOTED, f"created at {created_role} on {when}, promoted later"
    return UNCERTAIN, f"created at {created_role} on {when}"


def describe(a: dict, note: str = "") -> str:
    line = (
        f"  {a.get('name', '?'):<26} "
        f"{str(a.get('io_role') or '—'):<7} "
        f"{a.get('role', '?'):<8} "
        f"{str(a.get('email') or 'no email'):<28}"
    )
    return f"{line} {note}" if note else line


def main() -> None:
    argv = sys.argv[1:]
    apply = "--apply" in argv
    included = set()
    if "--include" in argv:
        included = {a for a in argv[argv.index("--include") + 1:] if not a.startswith("--")}

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]

    level_3 = list(db.agent_profiles.find({"role": WRONG_ROLE, **ACTIVE}, {"_id": 0}))
    ga_titled = [a for a in level_3 if is_ga_title(a.get("io_role"))]
    others = [a for a in level_3 if not is_ga_title(a.get("io_role"))]

    buckets = {LIKELY_BUG: [], PROMOTED: [], UNCERTAIN: []}
    for a in ga_titled:
        bucket, note = classify(db, a)
        buckets[bucket].append((a, note))

    header = f"  {'NAME':<26} {'TITLE':<7} {'TIER':<8} {'EMAIL':<28} WHY"
    print(f"\n{len(level_3)} active agent(s) at {WRONG_ROLE} (MGA tier); "
          f"{len(ga_titled)} carry a GA title.\n")

    print(f"[{LIKELY_BUG}] created at {WRONG_ROLE} — the buggy chip's signature: "
          f"{len(buckets[LIKELY_BUG])}")
    if buckets[LIKELY_BUG]:
        print(header)
        for a, note in buckets[LIKELY_BUG]:
            print(describe(a, note))
    else:
        print("  (none)")

    print(f"\n[{PROMOTED}] deliberately raised after creation — NOT demoted: "
          f"{len(buckets[PROMOTED])}")
    if buckets[PROMOTED]:
        print(header)
        for a, note in buckets[PROMOTED]:
            print(describe(a, note))
        print("\n  An admin moved these up on purpose. Leave them unless you know"
              "\n  otherwise; to demote one anyway, name it with --include.")
    else:
        print("  (none)")

    print(f"\n[{UNCERTAIN}] no creation record — NOT demoted: "
          f"{len(buckets[UNCERTAIN])}")
    if buckets[UNCERTAIN]:
        print(header)
        for a, note in buckets[UNCERTAIN]:
            print(describe(a, note))
        print("\n  Predates the audit trail (e.g. seeded by import_roster.py)."
              "\n  Confirm each by hand, then opt in with:"
              "\n    --include " + " ".join(a["agent_id"] for a, _ in buckets[UNCERTAIN]))
    else:
        print("  (none)")

    print(f"\n[OTHER {WRONG_ROLE}] non-GA titles, never touched: {len(others)}")
    if others:
        print(header)
        for a in others:
            print(describe(a))
        print("\n  Confirm each is a real MGA. If one is a GA under a title"
              "\n  spelling this script doesn't know, add it to GA_TITLES.")
    else:
        print("  (none)")

    # --apply touches the bug's own signature, plus anything explicitly named.
    eligible = [a for a, _ in buckets[LIKELY_BUG]]
    eligible += [a for bucket in (PROMOTED, UNCERTAIN)
                 for a, _ in buckets[bucket] if a["agent_id"] in included]

    unknown = included - {a["agent_id"] for a in ga_titled}
    if unknown:
        print(f"\nWARNING: --include named {len(unknown)} agent(s) not in any list "
              f"above; ignored: {', '.join(sorted(unknown))}")

    if not eligible:
        print("\nNothing eligible to change.")
        client.close()
        return

    if not apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply to set "
              f"{len(eligible)} agent(s) to {CORRECT_ROLE}.")
        client.close()
        return

    print(f"\nApplying: {len(eligible)} agent(s) -> {CORRECT_ROLE} ...")
    now = datetime.now(timezone.utc)
    changed = 0
    for a in eligible:
        agent_id = a["agent_id"]
        db.agent_profiles.update_one(
            {"agent_id": agent_id},
            {"$set": {"role": CORRECT_ROLE, "updated_at": now}},
        )
        # Sync any linked login so the tier drops immediately rather than at
        # their next sign-in — mirrors /admin/update-person in server.py.
        email = str(a.get("email") or "").lower().strip()
        if email:
            db.users.update_many({"email": email}, {"$set": {"role": CORRECT_ROLE}})
        db.audit_log.insert_one({
            "audit_id": f"au_{uuid.uuid4().hex[:10]}",
            "ts": now,
            "action": "fix_ga_tier",
            "agent_id": agent_id,
            "agent_name": a.get("name"),
            "from_role": WRONG_ROLE,
            "role": CORRECT_ROLE,
            "reason": "GA created at MGA tier by the Team tab add-member sheet",
            "forced": agent_id in included,
        })
        changed += 1
        print(f"  [OK] {a.get('name')} -> {CORRECT_ROLE}")

    print(f"\nDone. {changed} agent(s) corrected.")
    client.close()


if __name__ == "__main__":
    main()
