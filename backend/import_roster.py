"""
Roster Import Script
Imports the full MJ RGA agent roster into MongoDB with correct
upline_id hierarchy links so every tier can see its downline.

Role mapping (IO → app):
  RGA           → level_4
  MGA           → level_3
  GA            → level_2
  SA / Agent / Builder / inTraining → level_1

NOTE: SAs are mapped to level_1 (agent-tier).  They enter their own
Pulse but cannot view team dashboards.  To promote a SA to GA-tier
access, update their record via create_users.py with role "level_2".

Run from repo root:
    pip install pymongo dnspython
    MONGO_URL="mongodb+srv://..." python backend/import_roster.py
"""
import os
import re
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME   = os.environ.get("MONGO_DB", "vantagelife")
OFFICE    = "MJ RGA"

# ── ROSTER ────────────────────────────────────────────────────────────────────────
# (name, phone_digits, email, io_role, app_role, direct_upline_name_or_None)
# Ordered top-down so every upline exists before the agents below it.
ROSTER = [
    # ── Top of hierarchy ──────────────────────────────────────────────────────
    ("ALJAHMI, MOHAMED",      "3135550101", "mj@aopremier.com",                 "RGA",        "level_4", None),
    # ── MGA ────────────────────────────────────────────────────────────────────
    ("ALWATAN, MONTZER",      "3139609390", "Monty@AOpremier.com",              "MGA",        "level_3", "ALJAHMI, MOHAMED"),
    # ── GAs ────────────────────────────────────────────────────────────────────
    ("COOK, CONNOR",          "2163186495", "ccook.ao@gmail.com",               "GA",         "level_2", "ALJAHMI, MOHAMED"),
    ("SOLIS, JEANNIELIZA",    "9157407465", "jennysolis1624@gmail.com",         "GA",         "level_2", "ALJAHMI, MOHAMED"),
    ("MUSA, ALI",             "3132660109", "ali@aopremier.com",                "GA",         "level_2", "ALJAHMI, MOHAMED"),
    # ── SAs (level_1 — team leads; promote to level_2 for GA-tier access) ─
    ("ELTANOUKHI, ALI",       "3136705561", "aeltanoukhi@gmail.com",            "SA",         "level_1", "MUSA, ALI"),
    ("LONG, HENRY",           "7346292467", "Henry@aopremier.com",              "SA",         "level_1", "MUSA, ALI"),
    ("QARADAGHI, SNOOR",      "3137990462", "Snoor.qaradaghi@gmail.com",        "SA",         "level_1", "MUSA, ALI"),
    ("SITTO, LANDY",          "5867448002", "landy.sitto.ali@gmail.com",        "SA",         "level_1", "MUSA, ALI"),
    ("MURSHED, ALESKANDAR",   "3132401920", "alex.murshed@gmail.com",           "SA",         "level_1", "LONG, HENRY"),
    # ── Agents / Builders / inTraining ────────────────────────────────────
    ("Aljahmi, Essa",         "3138985711", "EALJAHMI618@gmail.com",            "Builder",    "level_1", "MUSA, ALI"),
    ("ALJAILANI, GABRIEL",    "7343669060", "galjailani@gmail.com",             "Agent",      "level_1", "ELTANOUKHI, ALI"),
    ("ALJANABY, MSTAFA",      "3132600857", "mstafaaljanaby3@gmail.com",        "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("Almaweri, Aiman",       "7349721228", "reachalex.ao@outlook.com",         "Builder",    "level_1", "MURSHED, ALESKANDAR"),
    ("ALTAIRI, ABDULRAHMAN",  "3137751058", "alaltairi11@gmail.com",            "Agent",      "level_1", "ELTANOUKHI, ALI"),
    ("ALTAIRI, MAHER",        "3132864979", "Maheraltairi@outlook.com",         "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("BERATY, ASHLEY",        "2485340045", "ashberaty@gmail.com",              "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("BORDEN, CHRISTINA",     "4303466667", "christy.borden@yahoo.com",         "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("BOSTIC, MATTHEW",       "6142704381", "mattbostic.ao@gmail.com",          "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("Boussi, Ali",           "3136459783", "abouss2003@gmail.com",             "Builder",    "level_1", "MURSHED, ALESKANDAR"),
    ("BRINDLEY, DOUGLASS",    "6146496866", "douglassbrindley@gmail.com",       "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("CAZARES, HAZEL",        "9152580680", "HAZEL.CAZARES@GMAIL.COM",          "Builder",    "level_1", "ALJAHMI, MOHAMED"),
    ("DEMARAS, CHRISTINE",    "9142757388", "cdemarasao@gmail.com",             "Agent",      "level_1", "ELTANOUKHI, ALI"),
    ("GHASHAM, HUSEIN",       "8328070761", "ghashuss@gmail.com",               "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("Grant, Tyler",          "8338013939", "TylerGrant@Cmail.live",            "Builder",    "level_1", "ELTANOUKHI, ALI"),
    ("Grey, Maya",            "8339724585", "MAYAGREY@CMAIL.LIVE",              "inTraining", "level_1", "SITTO, LANDY"),
    ("Hammer, Thomas",        "8133255177", "Hammerhouse13@gmail.com",          "Builder",    "level_1", "QARADAGHI, SNOOR"),
    ("HINSON, CHELSEA",       "5617688288", "chelseahinson97@gmail.com",        "Agent",      "level_1", "SOLIS, JEANNIELIZA"),
    ("Hope, Crystal",         "4047471246", "chope100@gmail.com",               "Builder",    "level_1", "ELTANOUKHI, ALI"),
    ("KEENER, JOSHUA",        "4233587696", "joshua.keener@epbfi.com",          "Agent",      "level_1", "LONG, HENRY"),
    ("LIKAJ, JUELA",          "3134591515", "ellalikaj@gmail.com",              "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("LISER, NOELLE",         "2406547683", "Noelleliser@gmail.com",            "Agent",      "level_1", "ELTANOUKHI, ALI"),
    ("MAWRI, AHMED",          "3133923787", "adam.globelifeao@GMAIL.COM",       "Agent",      "level_1", "LONG, HENRY"),
    ("McFadden, Gavin",       "4709362340", "gavmcfd@gmail.com",                "inTraining", "level_1", "QARADAGHI, SNOOR"),
    ("Mills, Carla",          "8332368340", "carlamills@cmail.live",            "inTraining", "level_1", "ALJAHMI, MOHAMED"),
    ("MUSAED, BASEL",         "3135302424", "baselmusaed3@gmail.com",           "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("OTHMAN, WALEEDJASHOLIH","3132581609", "willothman.ao@gmail.com",          "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("PRIEBE, CAMRON",        "2482085440", "camron.priebe00@outlook.com",      "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("QARADAGHI, SHIKO",      "3133007880", "qaradaghishko@gmail.com",          "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("Ross, Sebastian",       "8335183089", "sebastianross@cmail.live",         "inTraining", "level_1", "ELTANOUKHI, ALI"),
    ("RUIZ, ANGEL",           "9126634544", "angelmhogg@gmail.com",             "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("SANDERS, HANNAH",       "6787709798", "hsanders.aopremier@gmail.com",     "Agent",      "level_1", "MUSA, ALI"),
    ("Scott, Charlotte",      "8339563512", "Charlottescott@cmail.live",        "inTraining", "level_1", "MUSA, ALI"),
    ("SMITH, JERMAINE",       "4103400824", "Jdsmith625@gmail.com",             "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("SNIDER, LISA",          "7703626273", "lisanicole1110@icloud.com",        "Builder",    "level_1", "MUSA, ALI"),
    ("STIKELEATHER, STEVEN",  "8037579435", "kylestikeleather@gmail.com",       "Agent",      "level_1", "LONG, HENRY"),
    ("Tamer, Hadeel",         "3137488888", "hadeelnedaltamer@gmail.com",       "Builder",    "level_1", "ALJAHMI, MOHAMED"),
    ("TAYLOR, ALINA",         "6893230060", "Alinanunn@yahoo.com",              "Agent",      "level_1", "QARADAGHI, SNOOR"),
    ("Thanos, Melissa",       "6024637828", "melissathanos475@icloud.com",      "Builder",    "level_1", "QARADAGHI, SNOOR"),
    ("TRENTINI, ALMA",        "7372026696", "alma.cuello.ro@gmail.com",         "Agent",      "level_1", "ELTANOUKHI, ALI"),
    ("YOUSSEF, ADAM",         "3133385847", "Adamyoussef366@gmail.com",         "Agent",      "level_1", "ALJAHMI, MOHAMED"),
]
# ────────────────────────────────────────────────────────────────────────────


def find_agent(db, name: str):
    return db.agent_profiles.find_one(
        {"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}},
        {"_id": 0}
    )


def upsert_agent(db, name, phone, email, io_role, app_role, upline_id) -> str:
    existing = find_agent(db, name)
    if existing:
        db.agent_profiles.update_one(
            {"agent_id": existing["agent_id"]},
            {"$set": {
                "name":     name.strip(),
                "phone":    phone,
                "email":    email.lower(),
                "io_role":  io_role,
                "role":     app_role,
                "office":   OFFICE,
                "upline_id": upline_id,
            }},
        )
        print(f"  [UPDATE] {name}")
        return existing["agent_id"]

    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    db.agent_profiles.insert_one({
        "agent_id":  agent_id,
        "name":      name.strip(),
        "office":    OFFICE,
        "role":      app_role,
        "io_role":   io_role,
        "phone":     phone,
        "email":     email.lower(),
        "upline_id": upline_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"  [CREATE] {name}")
    return agent_id


def main():
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    print(f"Connected to '{DB_NAME}'\n")

    # name → agent_id cache (populated as we go, top-down)
    id_map: dict[str, str] = {}

    for name, phone, email, io_role, app_role, upline_name in ROSTER:
        upline_id = None
        if upline_name:
            upline_id = id_map.get(upline_name)
            if upline_id is None:
                # Fall back to a DB lookup so batched/partial imports still link correctly
                upline_agent = find_agent(db, upline_name)
                if upline_agent:
                    upline_id = upline_agent.get("agent_id")
                else:
                    print(f"  [WARN] upline '{upline_name}' not found in DB or id_map for {name} — check order")
        agent_id = upsert_agent(db, name, phone, email, io_role, app_role, upline_id)
        id_map[name] = agent_id

    print(f"\nDone. {len(ROSTER)} agents processed.")
    print("Hierarchy is live — uplines can now see their full downline in the app.")
    client.close()


if __name__ == "__main__":
    main()
