"""
Roster Email Audit / Sync Script

Verifies that the login database (agent_profiles) carries the current email
for every agent on the office's "AO Premier Agent List for App" sheet, and
optionally fixes what it finds. Login authorization is keyed by email
(upsert_user_and_session lowercases the incoming Google/Apple email and does
an exact match against agent_profiles.email), so a stale, misspelled, or
non-lowercase stored email strands a real agent on the "Account Pending"
screen even though their sign-in succeeded.

Reads a roster CSV exported from the sheet's final list tab with columns:
    app_id,name,email,tenure

What it reports (and what --fix changes):
  MISMATCH   profile matched by name but the stored email differs
             --fix: replaces the profile email with the sheet email,
             links any waiting "pending" login under the new email, and
             unlinks logins still holding the old email (they re-sync to
             the roster on their next sign-in anyway; this closes the gap)
  NOT LOWER  stored email has uppercase/whitespace — invisible to the
             login lookup   --fix: lowercases/strips it in place
  MISSING    on the sheet but nowhere in agent_profiles — these people can
             sign in but will sit on "Account Pending". NOT auto-created:
             role tier and upline can't be derived from the email sheet,
             and a wrong upline corrupts every team rollup. Add them via
             the in-app Add Person flow or extend import_roster.py.
  AMBIGUOUS  more than one profile plausibly matches a sheet row — never
             auto-fixed, listed for a human decision
  EXTRA      in agent_profiles but not on the sheet (demo seeds, other
             offices, or people the office dropped) — report only

Dry-run by default; nothing is written without --fix.

Run from repo root:
    MONGO_URL="mongodb+srv://..." python backend/audit_roster_emails.py
    MONGO_URL="mongodb+srv://..." python backend/audit_roster_emails.py --fix
    python backend/audit_roster_emails.py path/to/other_roster.csv
"""
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB") or os.environ.get("DB_NAME") or "vantagelife"
DEFAULT_CSV = Path(__file__).parent / "data" / "roster" / "agent_roster_2026-08-18.csv"


def now_utc():
    return datetime.now(timezone.utc)


def norm_name(name: str) -> frozenset:
    """Order-insensitive token set: 'SITTO, LANDY' == 'Landy Sitto'."""
    cleaned = re.sub(r"[^a-z'\- ]", " ", str(name).replace(",", " ").lower())
    return frozenset(t for t in cleaned.split() if t)


def load_roster(csv_path: Path):
    rows = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            email = row["email"].strip().lower()
            name = row["name"].strip()
            if not name or "@" not in email:
                continue
            rows.append({"app_id": row.get("app_id", "").strip(),
                         "name": name, "email": email})
    return rows


def match_profiles(entry, profiles):
    """All profiles matching a roster row: exact name-token match first,
    then subset match (middle-name variants), then match by email."""
    key = norm_name(entry["name"])
    exact = [p for p in profiles if norm_name(p.get("name", "")) == key]
    if exact:
        return exact
    subset = [p for p in profiles
              if len(key) >= 2 and len(norm_name(p.get("name", ""))) >= 2
              and (key <= norm_name(p.get("name", "")) or norm_name(p.get("name", "")) <= key)]
    if subset:
        return subset
    return [p for p in profiles
            if str(p.get("email", "")).strip().lower() == entry["email"]]


def audit(db, roster, fix=False, changed_by="cli:audit_roster_emails"):
    profiles = list(db.agent_profiles.find({}, {"_id": 0}))
    findings = {"ok": [], "mismatch": [], "not_lower": [], "missing": [],
                "ambiguous": [], "extra": []}
    matched_agent_ids = set()

    # Stored emails the login lookup can never hit (it lowercases its side).
    for p in profiles:
        raw = str(p.get("email", ""))
        if raw != raw.strip().lower():
            findings["not_lower"].append(dict(p))  # snapshot before any fix
            if fix:
                db.agent_profiles.update_one(
                    {"agent_id": p["agent_id"]},
                    {"$set": {"email": raw.strip().lower(), "updated_at": now_utc()}})
                p["email"] = raw.strip().lower()

    for entry in roster:
        hits = match_profiles(entry, profiles)
        if not hits:
            findings["missing"].append(entry)
            continue
        if len(hits) > 1:
            # Same person duplicated is fine only if every hit already carries
            # the sheet email; otherwise a human has to pick.
            if all(str(h.get("email", "")).strip().lower() == entry["email"] for h in hits):
                findings["ok"].append(entry)
                matched_agent_ids.update(h["agent_id"] for h in hits)
            else:
                findings["ambiguous"].append((entry, hits))
                matched_agent_ids.update(h["agent_id"] for h in hits)
            continue
        profile = hits[0]
        matched_agent_ids.add(profile["agent_id"])
        stored = str(profile.get("email", "")).strip().lower()
        if stored == entry["email"]:
            findings["ok"].append(entry)
            continue
        findings["mismatch"].append((entry, profile))
        if fix:
            db.agent_profiles.update_one(
                {"agent_id": profile["agent_id"]},
                {"$set": {"email": entry["email"], "updated_at": now_utc()}})
            # Someone who already signed in with the real email is sitting in
            # users as "pending" — link them to their profile right now.
            db.users.update_many(
                {"email": entry["email"]},
                {"$set": {"role": profile["role"], "agent_id": profile["agent_id"]}})
            # A login still keyed to the stale email no longer maps to any
            # roster row — drop it back to pending (mirrors what the next
            # sign-in's roster re-sync would do).
            if stored and not db.agent_profiles.find_one({"email": stored}):
                db.users.update_many(
                    {"email": stored, "agent_id": profile["agent_id"]},
                    {"$set": {"role": "pending", "agent_id": None}})
            db.audit_log.insert_one({
                "ts": now_utc(),
                "action": "sync_email",
                "agent_id": profile["agent_id"],
                "agent_name": profile.get("name"),
                "changed_by": changed_by,
                "original_value": profile.get("email"),
                "new_value": entry["email"],
            })

    findings["extra"] = [p for p in profiles if p["agent_id"] not in matched_agent_ids]
    return findings


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix = "--fix" in sys.argv
    csv_path = Path(args[0]) if args else DEFAULT_CSV
    roster = load_roster(csv_path)
    print(f"Roster: {len(roster)} people from {csv_path}")

    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]

    f = audit(db, roster, fix=fix)
    mode = "FIXED" if fix else "would fix (dry-run, pass --fix to apply)"

    print(f"\nOK (email already current): {len(f['ok'])}")

    print(f"\nEMAIL MISMATCHES — {mode}: {len(f['mismatch'])}")
    for entry, profile in f["mismatch"]:
        print(f"  {entry['name']:30s} db: {profile.get('email','')}  ->  sheet: {entry['email']}")

    print(f"\nNON-LOWERCASE STORED EMAILS — {mode}: {len(f['not_lower'])}")
    for p in f["not_lower"]:
        print(f"  {p.get('name',''):30s} {p.get('email','')}")

    print(f"\nMISSING FROM DATABASE (will land on Account Pending): {len(f['missing'])}")
    for entry in f["missing"]:
        print(f"  {entry['app_id']:8s} {entry['name']:30s} {entry['email']}")

    print(f"\nAMBIGUOUS (multiple profiles match — resolve by hand): {len(f['ambiguous'])}")
    for entry, hits in f["ambiguous"]:
        opts = "; ".join(f"{h.get('name')}<{h.get('email')}>" for h in hits)
        print(f"  {entry['name']} sheet:{entry['email']}  candidates: {opts}")

    print(f"\nIN DATABASE BUT NOT ON SHEET (report only): {len(f['extra'])}")
    for p in f["extra"]:
        print(f"  {p.get('name',''):30s} {p.get('email','')}  role={p.get('role','')}")

    if not fix and (f["mismatch"] or f["not_lower"]):
        print("\nDry-run only — re-run with --fix to apply the email corrections above.")


if __name__ == "__main__":
    main()
