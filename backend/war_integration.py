"""WAR integration — token-secured HTTPS ingest + reconciliation.

Why this exists: the unattended weekly WAR job runs in a sandbox whose
firewall blocks MongoDB's port 27017 (only 443 gets out), so it cannot write
to Atlas directly the way `import_xlsx_war.py` does. It goes through the
deployed backend over HTTPS instead, and this module is that door.

Two routes under `/api/integrations/war`, both guarded by a shared secret in
the `X-War-Token` header (env `WAR_IMPORT_TOKEN`):

  POST /import      ingest WAR daily rows, idempotent per (agent, day)
  GET  /reconcile   compare WAR rows vs app-entered pulses for a week

Deliberately additive: it does no metric math (all such math lives in
`metrics.py` per project convention), touches no existing route, and does not
participate in RBAC — the token is the whole authorization story here, because
the caller is a machine with no session and no agent identity.
"""
import hmac
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

# Tag applied to every row this endpoint writes. Identical to the value
# `import_xlsx_war.py` uses, so WAR rows from either path are indistinguishable
# downstream — and distinguishable from app pulses, which carry `entered_by`.
WAR_SOURCE = "war_xlsx_import"

# The WAR week starts Wednesday and the workbook carries 9 daily tabs
# (Wed, Thurs, Fri, Sat, Sun, Mon, Tues, Wed(2), Thurs(2)).
WAR_WEEK_DAYS = 9

# Fields on PulseIn that are not one of the 14 nightly metrics. Everything else
# on the model is a metric, in declaration order — see `_metric_fields()`.
# is_nif ("Not In Field") is a shortcut flag on nightly entry, not a metric —
# WarRow (this module's own schema) has no such field, so leaving it out of
# this set makes `_metric_fields()` include a name `entry[field] = getattr(row,
# field)` can't resolve, raising AttributeError on every WAR-integration call.
_NON_METRIC_FIELDS = frozenset(
    {"market", "sales_day", "target_agent_id", "client_entry_id", "is_nif"}
)

# gross_alp is a float; compare money with a cent of tolerance rather than ==.
_ALP_TOLERANCE = 0.01


def _metric_fields() -> Tuple[str, ...]:
    """The 14 nightly metrics, in order, read off the PulseIn schema.

    Project convention forbids hardcoding metric names — the schema in
    `server.py` is the single source of truth, so we derive from it instead of
    restating the list here and letting it drift. Imported lazily: `server`
    imports this module, and by the time `make_war_router()` is called
    PulseIn is long since defined.
    """
    import server

    return tuple(
        name
        for name in server.PulseIn.model_fields
        if name not in _NON_METRIC_FIELDS
    )


def _week_days(week_start: date) -> List[str]:
    """The 9 `sales_day` strings covered by a WAR week."""
    return [
        (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(WAR_WEEK_DAYS)
    ]


def _parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail=f"{field} must be a YYYY-MM-DD date"
        )


def _submitted_at(day: str) -> datetime:
    """Stamp WAR rows at 8:30 PM Detroit, matching `import_xlsx_war.py`.

    A real submit time matters: it lands inside the reporting cycle for that
    sales day and before the 9 PM gate, so imported history doesn't read as
    late. Nothing here changes the gate itself.
    """
    local = datetime.strptime(day, "%Y-%m-%d").replace(
        hour=20, minute=30, tzinfo=ZoneInfo("America/Detroit")
    )
    return local.astimezone(timezone.utc)


class WarRow(BaseModel):
    """One agent's production for one day, as parsed from a WAR daily tab."""

    agent_name: str
    sales_day: str  # YYYY-MM-DD
    sets: int = 0
    sits: int = 0
    sales: int = 0
    ots_sits: int = 0
    ots_sales: int = 0
    n1: int = 0
    refs_obtained: int = 0
    ref_sits: int = 0
    ref_sales: int = 0
    pos_sits: int = 0
    pos_sales: int = 0
    vet_sits: int = 0
    vet_sales: int = 0
    gross_alp: float = 0.0


class WarImportIn(BaseModel):
    week_start: str  # YYYY-MM-DD, a Wednesday
    office: str
    rows: List[WarRow] = Field(default_factory=list)


def make_war_router(
    db_or_getter: Union[Any, Callable[[], Any]],
    prefix: str = "/api/integrations/war",
) -> APIRouter:
    """Build the WAR integration router.

    `db_or_getter` may be a Motor database or a zero-argument callable
    returning one. The callable form keeps the router honest under test, where
    `server.db` is monkeypatched to an in-memory mock after import time.
    """
    router = APIRouter(prefix=prefix, tags=["war-integration"])
    metric_fields = _metric_fields()

    def get_db():
        return db_or_getter() if callable(db_or_getter) else db_or_getter

    def require_token(token: Optional[str]) -> None:
        """Gate both routes on the shared secret.

        503 when unconfigured, so a missing Railway variable is diagnosable
        rather than looking like a bad credential. Constant-time compare so a
        wrong token leaks nothing through timing.
        """
        expected = os.environ.get("WAR_IMPORT_TOKEN", "").strip()
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="WAR integration is disabled (WAR_IMPORT_TOKEN not set)",
            )
        if not token or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid WAR token")

    async def resolve_agent_id(db, name: str, office: str) -> str:
        """Match an agent by name (case-insensitive), creating one if absent.

        Mirrors `import_xlsx_war.py`: a WAR sheet is the roster of record for
        production, so a name we haven't seen becomes a level_1 profile with no
        upline. It gets no user account and no session, so it grants nobody
        access to anything — RBAC still reads `role`/`upline_id` as always.
        """
        clean = name.strip()
        existing = await db.agent_profiles.find_one(
            {"name": {"$regex": f"^{re.escape(clean)}$", "$options": "i"}}
        )
        if existing:
            return existing["agent_id"]

        agent_id = f"agent_{uuid.uuid4().hex[:10]}"
        await db.agent_profiles.insert_one(
            {
                "agent_id": agent_id,
                "name": clean,
                "office": office,
                "role": "level_1",
                "upline_id": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return agent_id

    @router.post("/import")
    async def war_import(
        payload: WarImportIn,
        x_war_token: Optional[str] = Header(default=None, alias="X-War-Token"),
    ) -> Dict[str, Any]:
        require_token(x_war_token)
        db = get_db()

        week_start = _parse_day(payload.week_start, "week_start")
        valid_days = set(_week_days(week_start))

        # Validate every row before writing any of them — a parser that emits
        # an out-of-week date is a bug worth failing loudly on, and a partial
        # import would be tedious to unpick by hand.
        for i, row in enumerate(payload.rows):
            _parse_day(row.sales_day, f"rows[{i}].sales_day")
            if row.sales_day not in valid_days:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"rows[{i}].sales_day {row.sales_day} is outside the "
                        f"{WAR_WEEK_DAYS}-day week starting {payload.week_start}"
                    ),
                )

        inserted = 0
        skipped = 0
        for row in payload.rows:
            agent_id = await resolve_agent_id(db, row.agent_name, payload.office)

            # Dedup is scoped to WAR rows so a re-run is a no-op, while leaving
            # any app-entered pulse for the same agent/day untouched — holding
            # both side by side is exactly what /reconcile reads.
            duplicate = await db.production_entries.find_one(
                {
                    "agent_id": agent_id,
                    "sales_day": row.sales_day,
                    "source": WAR_SOURCE,
                }
            )
            if duplicate:
                skipped += 1
                continue

            entry = {
                "entry_id": f"pe_{uuid.uuid4().hex[:12]}",
                "agent_id": agent_id,
                "office": payload.office,
                "sales_day": row.sales_day,
                "submitted_at": _submitted_at(row.sales_day),
                "submitted_on_time": True,
                "is_adjustment": False,
                "source": WAR_SOURCE,
            }
            for field in metric_fields:
                entry[field] = getattr(row, field)
            entry["net_alp"] = entry["gross_alp"]  # net == gross until an eraser adjusts

            await db.production_entries.insert_one(entry)
            inserted += 1

        return {
            "week_start": payload.week_start,
            "office": payload.office,
            "rows_received": len(payload.rows),
            "inserted": inserted,
            "skipped": skipped,
        }

    @router.get("/reconcile")
    async def war_reconcile(
        week_start: str = Query(..., description="YYYY-MM-DD, the WAR week's Wednesday"),
        max_discrepancies: int = Query(500, ge=1, le=5000),
        x_war_token: Optional[str] = Header(default=None, alias="X-War-Token"),
    ) -> Dict[str, Any]:
        require_token(x_war_token)
        db = get_db()

        start = _parse_day(week_start, "week_start")
        days = _week_days(start)

        # Read-only. Sums per (agent, day) because either side may legitimately
        # hold more than one row for a day — the app appends corrections rather
        # than overwriting.
        war: Dict[Tuple[str, str], Dict[str, float]] = {}
        app: Dict[Tuple[str, str], Dict[str, float]] = {}

        cursor = db.production_entries.find(
            {"sales_day": {"$in": days}}, {"_id": 0}
        )
        async for doc in cursor:
            key = (doc.get("agent_id"), doc.get("sales_day"))
            if doc.get("source") == WAR_SOURCE:
                bucket = war
            elif doc.get("entered_by") and not doc.get("is_adjustment"):
                bucket = app
            else:
                # Adjustments and anything untagged are out of scope: an eraser
                # row restates net_alp and would double-count against WAR.
                continue
            totals = bucket.setdefault(key, {f: 0 for f in metric_fields})
            for field in metric_fields:
                totals[field] += doc.get(field) or 0

        names = {
            d["agent_id"]: d.get("name")
            async for d in db.agent_profiles.find(
                {}, {"_id": 0, "agent_id": 1, "name": 1}
            )
        }

        def matches(field: str, a: float, b: float) -> bool:
            if field == "gross_alp":
                return abs(a - b) <= _ALP_TOLERANCE
            return a == b

        cells_compared = 0
        cells_matched = 0
        agent_days_fully_matched = 0
        discrepancies: List[Dict[str, Any]] = []
        discrepancy_count = 0

        both = sorted(set(war) & set(app), key=lambda k: (k[1], names.get(k[0]) or k[0]))
        war_only = sorted(set(war) - set(app), key=lambda k: (k[1], names.get(k[0]) or k[0]))
        app_only = sorted(set(app) - set(war), key=lambda k: (k[1], names.get(k[0]) or k[0]))

        def record(agent_id, day, field, war_val, app_val, in_war, in_app) -> None:
            nonlocal discrepancy_count
            discrepancy_count += 1
            if len(discrepancies) < max_discrepancies:
                discrepancies.append(
                    {
                        "agent": names.get(agent_id) or agent_id,
                        "agent_id": agent_id,
                        "sales_day": day,
                        "metric": field,
                        "war": war_val,
                        "app": app_val,
                        "delta": round(war_val - app_val, 2),
                        "in_war": in_war,
                        "in_app": in_app,
                    }
                )

        for key in both:
            agent_id, day = key
            fully_matched = True
            for field in metric_fields:
                war_val = war[key][field]
                app_val = app[key][field]
                cells_compared += 1
                if matches(field, war_val, app_val):
                    cells_matched += 1
                else:
                    fully_matched = False
                    record(agent_id, day, field, war_val, app_val, True, True)
            if fully_matched:
                agent_days_fully_matched += 1

        # One-sided agent-days aren't "compared" — there's nothing to compare
        # against — so they stay out of the cell counts and are reported on
        # their own terms, one entry per metric that actually carries a number.
        for key in war_only:
            agent_id, day = key
            for field in metric_fields:
                war_val = war[key][field]
                if war_val:
                    record(agent_id, day, field, war_val, 0, True, False)

        for key in app_only:
            agent_id, day = key
            for field in metric_fields:
                app_val = app[key][field]
                if app_val:
                    record(agent_id, day, field, 0, app_val, False, True)

        return {
            "week_start": week_start,
            "days": days,
            "metrics": list(metric_fields),
            "cells_compared": cells_compared,
            "cells_matched": cells_matched,
            "match_rate_pct": (
                round(cells_matched / cells_compared * 100, 2) if cells_compared else 0.0
            ),
            "agent_days_compared": len(both),
            "agent_days_fully_matched": agent_days_fully_matched,
            "war_only_agent_days": len(war_only),
            "app_only_agent_days": len(app_only),
            "discrepancy_count": discrepancy_count,
            "discrepancies": discrepancies,
            "discrepancies_truncated": discrepancy_count > len(discrepancies),
        }

    return router
