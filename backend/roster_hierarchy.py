"""Loader for the office's full app-roster hierarchy snapshot.

The committed CSV (backend/data/roster/agent_hierarchy_*.csv) is transcribed
from the office's live app sheet — the one with the SA/GA/MGA/RGA columns the
earlier snapshot dropped. It covers all three RGA books, so the admin
hierarchy audit can resolve an upline for anyone on it, not just the one
office the import scripts recorded.

Row semantics (matching how import_missing_roster.py transcribed the same
layout): each person's row names the SA, GA, MGA and RGA over them. A person
named in one of those columns of their own row holds that position — their
upline is the nearest column above it that names someone else. A person named
in none of them is an Agent whose upline is the lowest non-empty column.

Sheet quirks handled here:
- Connor Cook appears twice (AO0005 / AO0038, same phone+email); the first
  row wins — it carries the fuller chain.
- The sheet misspells some of its own references ("Afnan Alfatlawy" the row,
  "Afnan Alfatlaway" the SA column), so name matching tolerates one edit per
  token — enough for a dropped letter, never enough to confuse two people
  ("Musa" vs "Musaed" stays distinct).
- Annie Ransom is excluded from the app entirely (owner, 2026-08-18).
"""
import csv
import re
from pathlib import Path
from typing import Dict, FrozenSet, Optional

DEFAULT_CSV = Path(__file__).parent / "data" / "roster" / "agent_hierarchy_2026-08-20.csv"

EXCLUDED_NAME_KEYS = [frozenset({"annie", "ransom"})]

# The same human spelled two ways — a nickname in the name column, the formal
# name in the tier columns (or in older imports). Curated from the sheet's own
# otherwise-unmatchable references; a one-edit tolerance can't bridge these.
# Owner-confirmed 2026-08-20: Eddie Leon is the "Edward Leon" the Gojcaj book
# reports to.
ALIASES = [
    ("Eddie Leon", "Edward Leon"),
    ("Monty Alsheeblawy", "Muntather Alsheeblawy"),
]

# (column, io_role, app role) from lowest tier to highest.
_TIERS = [("sa", "SA", "level_2"), ("ga", "GA", "level_2"),
          ("mga", "MGA", "level_3"), ("rga", "RGA", "level_4")]


def name_key(name: str) -> FrozenSet[str]:
    """Order/case/punctuation-insensitive person key — same normalization as
    server._person_name_key and import_missing_roster.norm_name."""
    cleaned = re.sub(r"[^a-z'\- ]", " ", str(name).replace(",", " ").lower())
    return frozenset(t for t in cleaned.split() if t)


def _edit_distance_le_1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(shorter) and shorter[i] == longer[i]:
        i += 1
    return shorter[i:] == longer[i + 1:]


def keys_match(a: FrozenSet[str], b: FrozenSet[str]) -> bool:
    """True when two name keys are the same person allowing one typo per
    token: equal sets, or same token count with every token of one pairable to
    a distinct token of the other at edit distance <= 1."""
    if a == b:
        return True
    if not a or len(a) != len(b):
        return False
    remaining = list(b)
    for tok in a:
        hit = next((r for r in remaining if _edit_distance_le_1(tok, r)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


_ALIAS_KEYS: Dict[FrozenSet[str], set] = {}
for _a, _b in ALIASES:
    _ka, _kb = name_key(_a), name_key(_b)
    _ALIAS_KEYS.setdefault(_ka, {_ka}).add(_kb)
    _ALIAS_KEYS.setdefault(_kb, {_kb}).add(_ka)


def equivalent_keys(key: FrozenSet[str]) -> set:
    return _ALIAS_KEYS.get(key, {key})


def person_match(a: FrozenSet[str], b: FrozenSet[str]) -> bool:
    """keys_match plus the curated alias pairs above."""
    return any(keys_match(x, y) for x in equivalent_keys(a) for y in equivalent_keys(b))


def alias_names(name: str) -> list:
    """Every spelling this person goes by: the given name first, then any
    curated alias partner. For resolving a sheet reference against database
    profiles that may carry either spelling."""
    out = [name]
    for a, b in ALIASES:
        if keys_match(name_key(name), name_key(a)):
            out.append(b)
        elif keys_match(name_key(name), name_key(b)):
            out.append(a)
    return out


def load_hierarchy(path: Path = DEFAULT_CSV) -> Dict[FrozenSet[str], Dict[str, str]]:
    """name_key -> {name, email, phone, tenure, io_role, role, upline_name}."""
    out: Dict[FrozenSet[str], Dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nm = str(row.get("name", "")).strip()
            key = name_key(nm)
            if not key or key in out:
                continue
            if any(keys_match(key, ex) for ex in EXCLUDED_NAME_KEYS):
                continue
            chain = [str(row.get(col, "")).strip() for col, _, _ in _TIERS]
            io_role, role, own_idx = "Agent", "level_1", -1
            for i, (_, io, lvl) in enumerate(_TIERS):
                if chain[i] and person_match(name_key(chain[i]), key):
                    own_idx, io_role, role = i, io, lvl
            upline: Optional[str] = None
            for i in range(own_idx + 1, len(chain)):
                if chain[i] and not person_match(name_key(chain[i]), key):
                    upline = chain[i]
                    break
            out[key] = {
                "name": nm,
                "email": str(row.get("email", "")).strip().lower(),
                "phone": str(row.get("phone", "")).strip(),
                "tenure": str(row.get("tenure", "")).strip(),
                "io_role": io_role,
                "role": role,
                "upline_name": upline or "",
            }
    return out
