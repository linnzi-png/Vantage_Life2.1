"""
Missing-Roster Import — the 50 people on the office's 2026-08-18 app sheet
that audit_roster_emails.py reported as MISSING from agent_profiles, plus
one email-less leader (Ashlynn Orng) the sheet names as MGA over an existing
subtree. Tier, display title, upline, and tenure are transcribed from the
sheet's SA/GA/MGA/RGA columns (verified against the raw layout row by row).

Ordering is top-down so every upline exists before its downline: roots first
(Joseph Gojcaj and Ashley Rust are their own RGA per the sheet), then MGAs,
then GAs/SAs, then agents. Uplines already in the database (Henry Long,
Maher Altairi, Derron Alexander, ...) are resolved by name at runtime.

Dry-run by default — prints exactly what would be created and how each
upline resolved. Pass --apply to write.

Run from repo root:
    MONGO_URL="mongodb+srv://..." python backend/import_missing_roster.py
    MONGO_URL="mongodb+srv://..." python backend/import_missing_roster.py --apply

Notes transcribed from the sheet:
- Adam Youssef's own row shows no SA self-reference, but three downlines
  (Mahmoud Sammour, Osamah Almaliky, Saqr Algahmi) list him as their SA, so
  he is imported as SA (level_2).
- Ashlynn Orng appears only in the MGA column (no email/phone row of her
  own). She is created email-less so the O'Neil Mbakwe / Wendy Huber /
  Crystal Mekdarasack subtree has its real upline; add her email via the
  audit tool or admin panel when the office has it.
- Annie Ransom's sheet email is williambenline@cavu-ao.com (as written on
  the sheet — flag to the office if that looks like a copy/paste slip).
- Snoor Qaradaghi exists twice in the database; upline resolution prefers
  the profile that holds her login email.
"""
import os
import re
import sys
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB") or os.environ.get("DB_NAME") or "vantagelife"

# (name, email, io_role, app_role, is_rookie(None=unknown), upline_name_or_None)
# Ordered top-down. Upline names resolve against the DB first, then against
# entries created earlier in this same run.
ROSTER = [
    # ── New RGA roots (own book per the sheet: MGA and RGA columns are themselves)
    ("Joseph Gojcaj",       "joseph@aopremier.com",           "RGA",   "level_4", False, None),
    ("Ashley Rust",         "aerust03@gmail.com",             "RGA",   "level_4", False, None),
    # ── MGAs under Joseph Gojcaj
    ("David Fulfer",        "davidfulfer@aopremier.com",      "MGA",   "level_3", False, "Joseph Gojcaj"),
    ("Kenneth Preston",     "kenpreston@aoglobelife.com",     "MGA",   "level_3", False, "Joseph Gojcaj"),
    # Sheet names her as MGA of an existing subtree but carries no email for her.
    ("Ashlynn Orng",        "",                                "MGA",   "level_3", None,  "Joseph Gojcaj"),
    # ── GAs / SAs (level_2 either way — SA is a level_2 title)
    ("Ali Musa",            "ali@aopremier.com",              "GA",    "level_2", False, "Mohamed Aljahmi"),
    ("Jeannieliza Solis",   "jennysolis1624@gmail.com",       "GA",    "level_2", False, "Mohamed Aljahmi"),
    ("Aleskander Murshed",  "alex.murshed@gmail.com",         "SA",    "level_2", False, "Ali Musa"),
    ("Adam Youssef",        "adamyoussef366@gmail.com",       "SA",    "level_2", False, "Ali Musa"),
    # Annie Ransom (AO0119) is deliberately absent: per the owner (2026-08-18)
    # she is fully excluded from the app.
    ("Troy Williams",       "troywilliams50560@gmail.com",    "GA",    "level_2", False, "Ashley Rust"),
    # SA per the owner (2026-08-18), overriding the sheet row's blank SA column.
    ("Landy Sitto",         "landy.sitto.ail@gmail.com",      "SA",    "level_2", False, "Ali Musa"),
    # ── Agents — MJ book (upline = SA/GA column of their sheet row)
    ("Kyle Stikeleather",   "kylestikeleather@gmail.com",     "Agent", "level_1", True,  "Henry Long"),
    ("Ahmed Mawri",         "adam.globelifeao@gmail.com",     "Agent", "level_1", True,  "Henry Long"),
    ("Sarah Coppernoll",    "sobrien672@gmail.com",           "Agent", "level_1", True,  "Henry Long"),
    ("Tony Cacani",         "tonybcacani@gmail.com",          "Agent", "level_1", False, "Snoor Qaradaghi"),
    ("Sam Malushi",         "sammalushi@gmail.com",           "Agent", "level_1", False, "Snoor Qaradaghi"),
    ("Nathanio Perilus",    "nathanioperilus8@gmail.com",     "Agent", "level_1", True,  "Snoor Qaradaghi"),
    ("Brian Kwende",        "kbrian1019@gmail.com",           "Agent", "level_1", True,  "Snoor Qaradaghi"),
    ("Carlee Vastano",      "cvcarlee88@gmail.com",           "Agent", "level_1", True,  "Maher Altairi"),
    ("Kaem Mion",           "kylahmion@gmail.com",            "Agent", "level_1", True,  "Maher Altairi"),
    ("Jay Saffran",         "jaysaffran@gmail.com",           "Agent", "level_1", True,  "Maher Altairi"),
    ("Victoria Luis",       "vluisagent@gmail.com",           "Agent", "level_1", True,  "Maher Altairi"),
    ("Termaine Hudson",     "termainehudson216@gmail.com",    "Agent", "level_1", True,  "Maher Altairi"),
    ("Gabriel Aljailani",   "galjailani@gmail.com",           "Agent", "level_1", True,  "Maher Altairi"),
    ("Mahmoud Sammour",     "msammour1@outlook.com",          "Agent", "level_1", True,  "Adam Youssef"),
    ("Osamah Almaliky",     "oalmaliky@gmail.com",            "Agent", "level_1", True,  "Adam Youssef"),
    ("Saqr Algahmi",        "benefitsrepsam.ao@gmail.com",    "Agent", "level_1", True,  "Adam Youssef"),
    ("Hadi Awada",          "hawada.aogl@gmail.com",          "Agent", "level_1", True,  "Aleskander Murshed"),
    ("Aiman Almaweri",      "reachalex.ao@outlook.com",       "Agent", "level_1", True,  "Aleskander Murshed"),
    ("Emily Ortner",        "emcathmchugh@gmail.com",         "Agent", "level_1", True,  "Ali Eltanoukhi"),
    ("Tyler Litcher",       "lichtertyler@gmail.com",         "Agent", "level_1", False, "Ali Musa"),
    ("Essa Aljahmi",        "ealjahmi618@gmail.com",          "Agent", "level_1", True,  "Ali Musa"),
    # ── Agents — Montzer Alwatan book (tenure column blank on the sheet)
    ("Haider Aziz",         "haideraaziz1@gmail.com",         "Agent", "level_1", None,  "Muntather Alsheeblawy"),
    ("Hassan Almosawi",     "sammosawi33@gmail.com",          "Agent", "level_1", None,  "Mohamad-Ali Alwatan"),
    ("Cristina Alcivar",    "cristina.alcivar.nv@gmail.com",  "Agent", "level_1", None,  "Sunshine Faimalo"),
    # ── Agents — Joseph Gojcaj book
    ("Rebecca Middleton",   "r.middleton0096@gmail.com",      "Agent", "level_1", True,  "Joylynn Harris"),
    ("Keisha Smith",        "kcharles.aop@gmail.com",         "Agent", "level_1", True,  "Javier Sandoval"),
    ("David Daniel",        "dddaniel.aop@gmail.com",         "Agent", "level_1", True,  "Jacob Bandyk"),
    ("Jamell Ramsay",       "jramsay@pappasagencies.com",     "Agent", "level_1", True,  "Derron Alexander"),
    ("William Benline",     "will.benline@gmail.com",         "Agent", "level_1", False, "David Fulfer"),
    ("Emmy Phipps",         "emmy.phippsaop@gmail.com",       "Agent", "level_1", True,  "Ken Hermann"),
    ("Crystal Mekdarasack", "crystalmekdarasack@gmail.com",   "Agent", "level_1", True,  "Ashlynn Orng"),
    # ── Agents — Ashley Rust book
    ("Eldine Mpanzu",       "eldine328@gmail.com",            "Agent", "level_1", False, "Ashley Rust"),
    ("Kara Johnson",        "kara.johnson.ail@gmail.com",     "Agent", "level_1", False, "Karami Kovar"),
    ("Tommica Gibson",      "tommica25@gmail.com",            "Agent", "level_1", True,  "Joy Vann-Austin"),
    ("Tiarra McGhee",       "tiarramcghee.ao@gmail.com",      "Agent", "level_1", True,  "Mikaela Hayes"),
    ("Joshua Cobbs",        "cobbs.joshua170@gmail.com",      "Agent", "level_1", True,  "Abdur-Rahmaan Yaseen"),
    ("Paris McKee",         "parismckee.globelife@gmail.com", "Agent", "level_1", True,  "Abdur-Rahmaan Yaseen"),
    ("Deanna Delgado",      "deannaedelgado@gmail.com",       "Agent", "level_1", True,  "Maria Farley"),
    ("William Green",       "william900green@gmail.com",      "Agent", "level_1", True,  "Maria Farley"),
]

# Office for the two new roots (everyone else inherits from their upline).
# These match the office names the database already uses for their teams.
ROOT_OFFICE = {"Joseph Gojcaj": "Gojcaj RGA", "Ashley Rust": "Rust RGA"}

# Sheet name → the name the database actually stores for the same person.
ALIASES = {"Mohamed Aljahmi": "MJ Aljahmi"}

# Office renames applied before importing (per owner, 2026-08-18). Same scope
# as /admin/merge-office: agent_profiles only — everything downstream resolves
# offices through the roster.
RENAME_OFFICES = {"Montzer Alwatan RGA": "Alwatan RGA"}


def now_utc():
    return datetime.now(timezone.utc)


def norm_name(name):
    cleaned = re.sub(r"[^a-z'\- ]", " ", str(name).replace(",", " ").lower())
    return frozenset(t for t in cleaned.split() if t)


def find_upline(db, created, name):
    """Resolve an upline by name: profiles created this run first, then the DB.
    On multiple DB matches, prefer the profile holding a login email."""
    keys = {norm_name(name)}
    if name in ALIASES:
        keys.add(norm_name(ALIASES[name]))
    for p in created:
        if norm_name(p["name"]) in keys:
            return p, "created this run"
    matches = [p for p in db.agent_profiles.find({}, {"_id": 0})
               if norm_name(p.get("name", "")) in keys]
    if not matches:
        return None, "NOT FOUND"
    if len(matches) > 1:
        with_email = [p for p in matches if str(p.get("email", "")).strip()]
        pick = (with_email or matches)[0]
        return pick, f"{len(matches)} matches — picked the one with a login email"
    return matches[0], "db"


def run(db, roster, apply=False):
    for src, dst in RENAME_OFFICES.items():
        n = db.agent_profiles.count_documents({"office": src})
        if not n:
            continue
        tag = "RENAME OFFICE" if apply else "would rename office"
        print(f"{tag}: {src!r} -> {dst!r} ({n} profiles)")
        if apply:
            db.agent_profiles.update_many(
                {"office": src}, {"$set": {"office": dst, "updated_at": now_utc()}})

    created, skipped, blocked = [], [], []
    for name, email, io_role, role, is_rookie, upline_name in roster:
        email = email.strip().lower()
        existing = None
        key = norm_name(name)
        for p in db.agent_profiles.find({}, {"_id": 0, "agent_id": 1, "name": 1, "email": 1}):
            if norm_name(p.get("name", "")) == key or (email and str(p.get("email", "")).strip().lower() == email):
                existing = p
                break
        if existing:
            skipped.append((name, f"already exists as {existing.get('name')} ({existing['agent_id']})"))
            continue

        upline, how = (None, "root")
        if upline_name:
            upline, how = find_upline(db, created, upline_name)
            if upline is None:
                blocked.append((name, f"upline {upline_name!r} not found — NOT created"))
                continue

        office = ROOT_OFFICE.get(name) or (upline.get("office") if upline else "") or ""
        profile = {
            "agent_id": f"agent_{uuid.uuid4().hex[:10]}",
            "name": name,
            "email": email,
            "phone": "",
            "office": office,
            "role": role,
            "io_role": io_role,
            "upline_id": upline["agent_id"] if upline else None,
            "created_at": now_utc(),
            "joined_at": now_utc(),
        }
        if is_rookie is not None:
            profile["is_rookie"] = is_rookie
        created.append(profile)
        tag = "CREATE" if apply else "would create"
        rk = {True: "Rookie", False: "Vet", None: "tenure unknown"}[is_rookie]
        print(f"{tag}: {name:22s} {role} ({io_role}, {rk})  office={office or '?':12s} "
              f"upline={upline_name or 'none (root)'} [{how}]")
        if apply:
            db.agent_profiles.insert_one(dict(profile))
            if email:
                # If they signed in before being rostered, link that login now.
                db.users.update_many(
                    {"email": email},
                    {"$set": {"role": role, "agent_id": profile["agent_id"]}})
            db.audit_log.insert_one({
                "ts": now_utc(),
                "action": "add_agent",
                "agent_id": profile["agent_id"],
                "agent_name": name,
                "changed_by": "cli:import_missing_roster",
                "role": role,
                "upline_id": profile["upline_id"],
            })
    return created, skipped, blocked


def main():
    apply = "--apply" in sys.argv
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]

    created, skipped, blocked = run(db, ROSTER, apply=apply)

    print(f"\n{'Created' if apply else 'Would create'}: {len(created)}")
    print(f"Skipped (already in DB): {len(skipped)}")
    for n, why in skipped:
        print(f"  {n}: {why}")
    print(f"Blocked (upline missing): {len(blocked)}")
    for n, why in blocked:
        print(f"  {n}: {why}")
    if not apply:
        print("\nDry-run only — re-run with --apply to create the profiles above.")


if __name__ == "__main__":
    main()
