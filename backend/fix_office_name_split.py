"""
Office Name Split Repair Script

An office gets renamed from time to time (an RGA's office is named after
them, and RGAs get renamed/corrected). When that happens, agent_profiles.office
is updated for every current agent, but two other places still carry the OLD
name and never get told about the rename:

  production_entries.office   -- a flat string field on every Nightly Numbers
                                  entry submitted before the rename.
  historical_vault.by_office  -- the archived weekly snapshot's per-office
                                  totals, keyed by office NAME (a non-standard
                                  schema: office is a dict key here, not a
                                  field -- see learnings-and-tooling).

Nothing in server.py currently re-normalizes an old office name to the new
one (there is no _OFFICE_ALIASES map), so every daily/weekly/monthly and
Platinum Wall aggregation that resolves "this agent's office" and queries by
it only ever sees the slice of history filed under whichever name is
current. Everything before the rename silently disappears from those views.

Case fixed here: "Montzer Alwatan RGA" -> "Alwatan RGA" (renamed ~2026-08).
Found 2026-09-11 while investigating a report that an Alwatan RGA agent saw
no numbers anywhere on her dashboard.

This exact case (1,096 production_entries docs, 25 historical_vault weeks)
was ALREADY applied directly against the production Atlas cluster on
2026-09-11, verified by checksum (count/gross_alp/net_alp/sits/sales summed
identically before and after). This script is committed after the fact so
the fix has a reviewable, re-runnable record instead of living only in a
chat transcript. Re-running it now is a safe no-op -- see the dry-run output.

Dry-run by default; nothing is written without --fix. Safe to re-run: once
a name has been fully migrated, later runs find nothing left to do.

Usage (run from repo root):
    PowerShell:
        $env:MONGO_URL = "mongodb+srv://..."
        python backend/fix_office_name_split.py "Montzer Alwatan RGA" "Alwatan RGA"
        python backend/fix_office_name_split.py "Montzer Alwatan RGA" "Alwatan RGA" --fix

    bash / zsh:
        MONGO_URL="mongodb+srv://..." python backend/fix_office_name_split.py \
            "Montzer Alwatan RGA" "Alwatan RGA" --fix

If a historical_vault week already has totals filed under BOTH the old and
new name (possible if a rename happens mid-week), the two buckets are summed
together under the new name rather than one silently overwriting the other.
"""
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB") or os.environ.get("DB_NAME") or "vantagelife"

VAULT_METRIC_FIELDS = ["gross_alp", "net_alp", "sits", "sales"]


def now_utc():
    return datetime.now(timezone.utc)


def office_checksum(db, office: str) -> dict:
    """count/gross_alp/net_alp/sits/sales for one office name across both
    production_entries and historical_vault -- used to prove a rename didn't
    lose or double-count anything."""
    pe = list(db.production_entries.aggregate([
        {"$match": {"office": office}},
        {"$group": {"_id": None, "count": {"$sum": 1},
                     "gross_alp": {"$sum": "$gross_alp"}, "net_alp": {"$sum": "$net_alp"},
                     "sits": {"$sum": "$sits"}, "sales": {"$sum": "$sales"}}},
    ]))
    hv = list(db.historical_vault.aggregate([
        {"$match": {f"by_office.{office}": {"$exists": True}}},
        {"$group": {"_id": None, "weeks": {"$sum": 1},
                     "gross_alp": {"$sum": f"$by_office.{office}.gross_alp"},
                     "net_alp": {"$sum": f"$by_office.{office}.net_alp"},
                     "sits": {"$sum": f"$by_office.{office}.sits"},
                     "sales": {"$sum": f"$by_office.{office}.sales"}}},
    ]))
    return {"production_entries": pe[0] if pe else None, "historical_vault": hv[0] if hv else None}


def fix_production_entries(db, old: str, new: str, fix: bool) -> int:
    matched = db.production_entries.count_documents({"office": old})
    if fix and matched:
        result = db.production_entries.update_many({"office": old}, {"$set": {"office": new}})
        return result.modified_count
    return matched


def fix_historical_vault(db, old: str, new: str, fix: bool) -> dict:
    """Rename the by_office key on every week that has `old`. If a week
    already has both `old` and `new`, sum the metric fields into `new`
    before dropping `old` instead of letting $rename silently clobber it."""
    old_key, new_key = f"by_office.{old}", f"by_office.{new}"
    cursor = db.historical_vault.find({old_key: {"$exists": True}}, {"by_office": 1})
    renamed, merged = 0, 0
    for doc in cursor:
        by_office = doc.get("by_office", {})
        has_new = new in by_office
        if not fix:
            merged += 1 if has_new else 0
            renamed += 0 if has_new else 1
            continue
        if has_new:
            combined = {f: (by_office[old].get(f, 0) or 0) + (by_office[new].get(f, 0) or 0)
                        for f in VAULT_METRIC_FIELDS}
            db.historical_vault.update_one(
                {"_id": doc["_id"]},
                {"$set": {new_key: combined}, "$unset": {old_key: ""}})
            merged += 1
        else:
            # $set + $unset rather than $rename: functionally identical for a
            # single dotted key, and avoids a real MongoDB edge case with
            # $rename on keys containing spaces that some drivers/tools
            # mishandle.
            db.historical_vault.update_one(
                {"_id": doc["_id"]},
                {"$set": {new_key: by_office[old]}, "$unset": {old_key: ""}})
            renamed += 1
    return {"renamed": renamed, "merged": merged}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix = "--fix" in sys.argv
    if len(args) != 2:
        raise SystemExit(
            "Usage: python backend/fix_office_name_split.py <old_office_name> <new_office_name> [--fix]")
    old, new = args
    if old == new:
        raise SystemExit("old and new office names are identical -- nothing to do")

    print("Connecting to MongoDB ...")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]

    before_old = office_checksum(db, old)
    before_new = office_checksum(db, new)
    print(f"\nBEFORE\n  {old!r}: {before_old}\n  {new!r}: {before_new}")

    pe_n = fix_production_entries(db, old, new, fix)
    hv = fix_historical_vault(db, old, new, fix)

    mode = "Fixed" if fix else "Would fix (dry-run, pass --fix to apply)"
    print(f"\n{mode}:")
    print(f"  production_entries: {pe_n} doc(s) {'renamed' if fix else 'to rename'}")
    print(f"  historical_vault:   {hv['renamed']} week(s) {'renamed' if fix else 'to rename'} cleanly, "
          f"{hv['merged']} week(s) {'merged' if fix else 'that need merging (both names present)'}")

    if fix:
        db.audit_log.insert_one({
            "ts": now_utc(),
            "action": "fix_office_name_split",
            "changed_by": "cli:fix_office_name_split",
            "old_office": old,
            "new_office": new,
            "production_entries_modified": pe_n,
            "historical_vault_renamed": hv["renamed"],
            "historical_vault_merged": hv["merged"],
        })
        after_new = office_checksum(db, new)
        after_old = office_checksum(db, old)
        print(f"\nAFTER\n  {old!r}: {after_old}\n  {new!r}: {after_new}")
        if after_old["production_entries"] or after_old["historical_vault"]:
            print(f"\nWARNING: {old!r} still has data after the fix -- investigate before trusting this run.")
        else:
            print(f"\n{old!r} fully retired. All data now under {new!r}.")
    elif pe_n == 0 and hv["renamed"] == 0 and hv["merged"] == 0:
        print(f"\nNothing to do -- no data found under {old!r}. Already migrated, or the name was never used.")


if __name__ == "__main__":
    main()
