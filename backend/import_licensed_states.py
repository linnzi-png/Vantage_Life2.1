"""
Licensed-states import (Linnzi, 2026-09-29; batch 4 PR G).

Reads docs/data/licensed_states_seed.csv (name, role_on_sheet, licensed_states,
pending_states, also_known_as) and writes each matched agent's
`licensed_states` and `pending_states` in one office. Matches by exact
normalised name (case, spacing and punctuation ignored) or an `also_known_as`
name within the office; the sheet has no emails. The role on the sheet is
ignored. Never touches `state` (the resident state).

Dry-run by default: prints the diff, every unmatched name, every name that
matches more than one profile, every code that is not a valid state (rejected,
never written) and every active profile in the office that is not on the sheet.
Pass --apply to write. A code on both lists is written as active only.
Idempotent: a person whose lists already match is left alone and not audited.

Writes set `licensed_states`, `pending_states`, `pending_added_at` (the day the
code was first pending; an existing date is kept, new codes get the import
day), `pending_reminder` (existing setting kept, new codes on) and one
audit_log entry per person (`action: "import_licensed_states"`).

Run from repo root:
    PowerShell:
        $env:MONGO_URL = "mongodb+srv://..."
        python backend/import_licensed_states.py
        python backend/import_licensed_states.py --apply
"""
import argparse
import csv
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Mirror of LICENSED_STATE_CODES in server.py; a test keeps the two identical.
VALID_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR",
})
ACTION = "import_licensed_states"
DEFAULT_OFFICE = "MJ RGA"
DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "data", "licensed_states_seed.csv")


def normalize_name(name: Optional[str]) -> str:
    """Lowercase, drop punctuation, collapse spaces: "Ali  T. Alwatan" and
    "ali t alwatan" are the same name."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).strip()


def split_codes(raw: Optional[str]) -> List[str]:
    return [c for c in re.split(r"[\s,;]+", (raw or "").upper()) if c]


def validate_codes(codes: List[str], valid=VALID_CODES):
    """(accepted sorted unique, rejected sorted unique)."""
    good = sorted({c for c in codes if c in valid})
    bad = sorted({c for c in codes if c not in valid})
    return good, bad


def read_seed(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = (r.get("name") or "").strip()
            if not name:
                continue
            rows.append({
                "name": name,
                "names": [name] + [a.strip() for a in re.split(r"[;|]", r.get("also_known_as") or "") if a.strip()],
                "licensed": split_codes(r.get("licensed_states")),
                "pending": split_codes(r.get("pending_states")),
            })
    return rows


def build_plan(seed: List[Dict[str, Any]], profiles: List[Dict[str, Any]], office: str, today: str) -> Dict[str, Any]:
    """Pure: no database. `profiles` are agent_profiles documents."""
    in_office = [p for p in profiles
                 if normalize_name(p.get("office")) == normalize_name(office) and not p.get("archived")]
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for p in in_office:
        by_name.setdefault(normalize_name(p.get("name")), []).append(p)

    changes, unchanged, unmatched, ambiguous, rejected, overlap = [], [], [], [], [], []
    seen_ids = set()
    for row in seed:
        found: Dict[str, Dict[str, Any]] = {}
        for n in row["names"]:
            for p in by_name.get(normalize_name(n), []):
                found[p["agent_id"]] = p
        if not found:
            unmatched.append(row["name"])
            continue
        if len(found) > 1:
            ambiguous.append({"name": row["name"], "agent_ids": sorted(found)})
            continue
        p = next(iter(found.values()))
        seen_ids.add(p["agent_id"])
        licensed, bad_l = validate_codes(row["licensed"])
        pending, bad_p = validate_codes(row["pending"])
        if bad_l or bad_p:
            rejected.append({"name": row["name"], "codes": sorted(set(bad_l + bad_p))})
        both = sorted(set(licensed) & set(pending))
        if both:
            overlap.append({"name": row["name"], "codes": both})
        pending = [c for c in pending if c not in licensed]
        added = dict(p.get("pending_added_at") or {})
        flags = dict(p.get("pending_reminder") or {})
        new = {
            "licensed_states": licensed,
            "pending_states": pending,
            "pending_added_at": {c: added.get(c) or today for c in pending},
            "pending_reminder": {c: flags.get(c, True) for c in pending},
        }
        old_l = sorted(p.get("licensed_states") or [])
        old_p = sorted(p.get("pending_states") or [])
        if old_l == licensed and old_p == pending:
            unchanged.append(row["name"])
            continue
        changes.append({
            "agent_id": p["agent_id"], "name": p.get("name"), "sheet_name": row["name"],
            "old_licensed": old_l, "old_pending": old_p, "fields": new,
            "added": sorted(set(licensed) - set(old_l)), "removed": sorted(set(old_l) - set(licensed)),
            "pending_added": sorted(set(pending) - set(old_p)), "pending_removed": sorted(set(old_p) - set(pending)),
        })
    not_on_sheet = sorted(p.get("name") or p["agent_id"] for p in in_office if p["agent_id"] not in seen_ids)
    return {"changes": changes, "unchanged": unchanged, "unmatched": unmatched, "ambiguous": ambiguous,
            "rejected": rejected, "overlap": overlap, "not_on_sheet": not_on_sheet}


def apply_plan(db, plan: Dict[str, Any]) -> int:
    """Write each change and its audit entry. `db` is a pymongo Database."""
    now = datetime.now(timezone.utc)
    for c in plan["changes"]:
        db.agent_profiles.update_one(
            {"agent_id": c["agent_id"]},
            {"$set": {**c["fields"], "updated_at": now}},  # never `state`
        )
        db.audit_log.insert_one({
            "audit_id": f"au_{uuid.uuid4().hex[:10]}",
            "ts": now,
            "action": ACTION,
            "agent_id": c["agent_id"],
            "agent_name": c["name"],
            "changed_by": ACTION,
            "changed_by_name": "Licensed states import",
            "original_value": c["old_licensed"],
            "new_value": c["fields"]["licensed_states"],
            "original_pending": c["old_pending"],
            "new_pending": c["fields"]["pending_states"],
        })
    return len(plan["changes"])


def render(plan: Dict[str, Any]) -> str:
    out = []
    for c in plan["changes"]:
        bits = []
        if c["added"]: bits.append("+" + " +".join(c["added"]))
        if c["removed"]: bits.append("-" + " -".join(c["removed"]))
        if c["pending_added"]: bits.append("pending +" + " +".join(c["pending_added"]))
        if c["pending_removed"]: bits.append("pending -" + " -".join(c["pending_removed"]))
        out.append(f"  {c['name']}: {'  '.join(bits)}")
    out.insert(0, f"WILL CHANGE ({len(plan['changes'])}):")
    out.append(f"UNCHANGED ({len(plan['unchanged'])})")
    for key, label in (("unmatched", "NOT FOUND IN THE APP"), ("not_on_sheet", "ON THE APP BUT NOT ON THE SHEET")):
        out.append(f"{label} ({len(plan[key])}): " + (", ".join(plan[key]) or "none"))
    out.append(f"MATCHES MORE THAN ONE PROFILE, SKIPPED ({len(plan['ambiguous'])}): "
               + ("; ".join(f"{a['name']} -> {', '.join(a['agent_ids'])}" for a in plan["ambiguous"]) or "none"))
    out.append(f"INVALID CODES, NOT WRITTEN ({len(plan['rejected'])}): "
               + ("; ".join(f"{r['name']}: {', '.join(r['codes'])}" for r in plan["rejected"]) or "none"))
    out.append(f"ON BOTH LISTS, WRITTEN AS ACTIVE ({len(plan['overlap'])}): "
               + ("; ".join(f"{r['name']}: {', '.join(r['codes'])}" for r in plan["overlap"]) or "none"))
    return "\n".join(out)


def sales_day_today() -> str:
    """The sales day starts at 6 AM Detroit; Detroit is UTC-4/-5, so shift by
    the Detroit offset then back 6 hours."""
    import pytz
    now = datetime.now(pytz.timezone("America/Detroit"))
    return (now - timedelta(hours=6)).date().isoformat()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--office", default=DEFAULT_OFFICE)
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    args = ap.parse_args(argv)

    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
    db = MongoClient(url)[os.environ.get("MONGO_DB") or os.environ.get("DB_NAME") or "vantagelife"]
    profiles = list(db.agent_profiles.find(
        {}, {"_id": 0, "agent_id": 1, "name": 1, "office": 1, "archived": 1, "licensed_states": 1,
             "pending_states": 1, "pending_added_at": 1, "pending_reminder": 1}))
    plan = build_plan(read_seed(args.csv), profiles, args.office, sales_day_today())
    print(render(plan))
    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply to write.")
        return 0
    print(f"\nWrote {apply_plan(db, plan)} profiles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
