"""VantageLife 2.0 — FastAPI Backend
AO Premier — Real-Time Impact Culture
"""
from fastapi import FastAPI, APIRouter, Request, HTTPException, Response, Depends, Body
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import re
import uuid
import random
import httpx
import pytz

import metrics
from pathlib import Path
from pydantic import BaseModel, Field
from jose import jwt as apple_jwt
from jose.exceptions import JOSEError
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta, date

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ---------------- Mongo ----------------
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# ---------------- App ----------------
app = FastAPI(title="VantageLife 2.0 API")
api_router = APIRouter(prefix="/api")

DETROIT_TZ = pytz.timezone("America/Detroit")
# Self-service correction window: an agent may submit/adjust their own numbers
# for up to 3 sales days back. Past that, only an upline (MGA/RGA, level_3+)
# can correct it — see can_enter_for() and /api/manager/erase.
MAX_SELF_BUFFER_DAYS = 3
# When an MGA/RGA is entering on a downline agent's behalf (target_agent_id
# set, per can_enter_for), the same buffered-flush cap the app already used
# for everyone (unchanged from the original 7-day window).
MAX_UPLINE_BUFFER_DAYS = 7
_SEED_OFFICES = ["MCM", "AMP", "Dearborn", "Heritage", "Siren"]  # used only for demo seed data
# Display titles for the four RBAC tiers (producer track). Internal role
# keys and access rules are unchanged — titles are display-only. Partner /
# Senior Partner are io_role titles carried by level_3/level_4 holders.
LEVELS = {
    "level_1": "Agent",
    "level_2": "CoExecutive Producer",
    "level_3": "Executive Producer",
    "level_4": "Chief Executive Producer",
    "pending": "Pending Approval",
}
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
# Bootstrap admins: always admins even without an is_admin flag on their users doc.
# Additional admins are granted the is_admin flag from the in-app Admin screen.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "linnzi@aoluxor.com,mj@aopremier.com").split(",")
    if e.strip()
}
APPLE_BUNDLE_ID = "com.aopremiere.vantagelife"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

# ---------------- Helpers ----------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_detroit() -> datetime:
    return datetime.now(DETROIT_TZ)


def iso_utc(d: datetime) -> str:
    """Serialize a stored datetime with an explicit UTC offset.

    Mongo returns datetimes naive (UTC without tzinfo); a bare isoformat()
    then has no offset marker and clients parse it as device-local time,
    shifting every displayed timestamp by the UTC offset."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


def sales_day_for(dt_local: datetime) -> str:
    """Sales day rolls 6 AM → 6 AM in Detroit time. Pulse Gate at 9 PM, Hard Lock at 6 AM."""
    if dt_local.hour < 6:
        d = (dt_local - timedelta(days=1)).date()
    else:
        d = dt_local.date()
    return d.isoformat()


def gate_state(dt_local: Optional[datetime] = None) -> Dict[str, Any]:
    if dt_local is None:
        dt_local = now_detroit()
    h = dt_local.hour
    # Banner states
    if 21 <= h < 24:
        return {"state": "warning", "message": "9:00 PM Deadline Passed. Log your numbers now to avoid leadership escalation.", "color": "yellow"}
    if 0 <= h < 6:
        return {"state": "midnight_cutoff", "message": "Midnight Cutoff Approaching — submit your numbers now.", "color": "yellow"}
    if h == 6 and dt_local.minute < 1:
        return {"state": "open", "message": "Pulse window open.", "color": "green"}
    return {"state": "open", "message": "Pulse window open.", "color": "green"}


# ---------------- Models ----------------
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=now_utc)


class DemoLoginIn(BaseModel):
    level: str  # level_1..level_4


class SessionExchangeIn(BaseModel):
    session_id: str


class AppleLoginIn(BaseModel):
    identity_token: str
    given_name: Optional[str] = None
    family_name: Optional[str] = None


class PulseIn(BaseModel):
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
    market: Optional[str] = None  # selectable office override
    sales_day: Optional[str] = None  # buffered flush only — YYYY-MM-DD; see MAX_SELF_BUFFER_DAYS / MAX_UPLINE_BUFFER_DAYS
    target_agent_id: Optional[str] = None  # set only when an MGA/RGA is entering on behalf of a downline agent


class EraseIn(BaseModel):
    agent_id: str
    sales_day: str  # YYYY-MM-DD
    new_alp: float
    reason: str


# ---------------- Auth ----------------

async def get_session_token(request: Request) -> Optional[str]:
    tok = request.cookies.get("session_token")
    if tok:
        return tok
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def get_current_user(request: Request) -> Dict[str, Any]:
    tok = await get_session_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = await db.user_sessions.find_one({"session_token": tok}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_agent(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Authenticated identity is not enough — block anyone not linked to a real
    AO Premier agent record from reaching business data, regardless of sign-in flow."""
    if not user.get("agent_id") or not str(user.get("role", "")).startswith("level_"):
        raise HTTPException(status_code=403, detail="Not yet linked to an AO Premier agent profile")
    return user


def user_is_admin(user: Dict[str, Any]) -> bool:
    return bool(user.get("is_admin")) or str(user.get("email", "")).lower() in ADMIN_EMAILS


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Admin panel access: bootstrap ADMIN_EMAILS or users granted the is_admin flag.
    Deliberately built on get_current_user (not require_agent) so an admin can
    manage the roster even before their own agent link exists."""
    if not user_is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_level(min_level: int):
    """min_level: 1..4 (higher = more access). level_1 has level=1, level_4 has level=4."""
    async def dep(user: Dict[str, Any] = Depends(require_agent)) -> Dict[str, Any]:
        lvl = int(user["role"].split("_")[1])
        if lvl < min_level:
            raise HTTPException(status_code=403, detail=f"Requires level {min_level}+")
        return user
    return dep


def set_session_cookie(resp: Response, token: str):
    # 7 days; secure + samesite none for cross-domain preview
    resp.set_cookie(
        key="session_token",
        value=token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


async def upsert_user_and_session(email: str, name: str, picture: Optional[str], session_token: str) -> Dict[str, Any]:
    email = email.lower().strip()
    # Authentication (proving who you are via Google/Apple) always succeeds for any
    # verified identity — App Store review must be able to complete Sign in with Apple
    # without error. Authorization (seeing AO Premier data) is gated separately by
    # require_agent: anyone not on the agent roster gets role "pending" and no agent_id,
    # so they land on a harmless pending screen instead of an error during sign-in.
    agent = await db.agent_profiles.find_one({"email": email}, {"_id": 0})
    role = agent["role"] if agent else "pending"
    agent_id = agent["agent_id"] if agent else None

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture or "",
            "role": role,
            "agent_id": agent_id,
            "created_at": now_utc(),
        }
        await db.users.insert_one(user_doc)
        user_doc.pop("_id", None)
        user = user_doc
    else:
        # role/agent_id always re-synced from the agent roster, the source of truth
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"name": name, "picture": picture or user.get("picture", ""), "role": role, "agent_id": agent_id}},
        )
        user = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})

    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(days=7),
    })
    return user


async def verify_apple_token(identity_token: str) -> Dict[str, Any]:
    """Verify a Sign in with Apple identity token against Apple's published JWKs."""
    try:
        header = apple_jwt.get_unverified_header(identity_token)
    except JOSEError:
        raise HTTPException(status_code=401, detail="Invalid Apple identity token format")

    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.get(APPLE_KEYS_URL)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch Apple public keys")
    keys = r.json().get("keys", [])
    matching_key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if not matching_key:
        raise HTTPException(status_code=401, detail="No matching Apple public key found")

    try:
        payload = apple_jwt.decode(
            identity_token,
            matching_key,
            algorithms=["RS256"],
            audience=APPLE_BUNDLE_ID,
            issuer="https://appleid.apple.com",
        )
    except JOSEError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {e}")

    return {"sub": payload["sub"], "email": payload.get("email")}


# =========================================================
#                       AUTH ROUTES
# =========================================================

@api_router.post("/auth/session")
async def auth_session(payload: SessionExchangeIn, response: Response):
    """Exchange Emergent session_id for a session_token and create user."""
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": payload.session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()
    email = data.get("email")
    name = data.get("name") or email
    picture = data.get("picture")
    session_token = data.get("session_token") or f"st_{uuid.uuid4().hex}"

    user = await upsert_user_and_session(email=email, name=name, picture=picture, session_token=session_token)
    set_session_cookie(response, session_token)
    return {"user": user, "session_token": session_token}


@api_router.post("/auth/demo-login")
async def demo_login(payload: DemoLoginIn, response: Response):
    """Quick demo login that maps to one of 4 RBAC levels (no Google needed).

    RELEASE GATE (per Linnzi, 2026-07-03): stays OPEN through TestFlight and
    App Store review. Once the app is approved and released to the App Store,
    disable or auth-gate this endpoint — it is unauthenticated and maps onto
    the first REAL agent of each role, so demo writes attribute to real people."""
    if payload.level not in LEVELS:
        raise HTTPException(status_code=400, detail="Invalid level")
    role_label = LEVELS[payload.level]
    email_map = {
        "level_1": ("demo.agent@vantagelife.dev", "Demo Agent"),
        "level_2": ("demo.ga@vantagelife.dev", "Demo GA"),
        "level_3": ("demo.mga@vantagelife.dev", "Demo MGA"),
        "level_4": ("demo.rga@vantagelife.dev", "Demo RGA"),
    }
    email, name = email_map[payload.level]

    # Map demo user to an existing seeded agent of that role (so views work)
    agent = await db.agent_profiles.find_one({"role": payload.level}, {"_id": 0})
    agent_id = agent["agent_id"] if agent else None

    session_token = f"st_{uuid.uuid4().hex}"
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"role": payload.level, "agent_id": agent_id, "name": name, "picture": ""}},
        )
        user = await db.users.find_one({"email": email}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": "",
            "role": payload.level,
            "agent_id": agent_id,
            "created_at": now_utc(),
        }
        await db.users.insert_one(dict(user))
        user.pop("_id", None)

    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(days=7),
    })
    set_session_cookie(response, session_token)
    return {"user": user, "session_token": session_token, "role_label": role_label}


@api_router.get("/auth/me")
async def auth_me(user: Dict[str, Any] = Depends(get_current_user)):
    agent = None
    if user.get("agent_id"):
        agent = await db.agent_profiles.find_one({"agent_id": user["agent_id"]}, {"_id": 0})
    # Overlay computed admin status so bootstrap admins (ADMIN_EMAILS) see the
    # Admin entry point even without an is_admin flag on their users doc.
    user["is_admin"] = user_is_admin(user)
    user["can_switch_role"] = bool(user.get("can_switch_role"))
    return {"user": user, "agent": agent, "role_label": LEVELS.get(user.get("role", "level_1"), "Agent")}


@api_router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    tok = await get_session_token(request)
    if tok:
        await db.user_sessions.delete_one({"session_token": tok})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@api_router.post("/auth/apple")
async def auth_apple(payload: AppleLoginIn, response: Response):
    claims = await verify_apple_token(payload.identity_token)
    apple_email = claims.get("email") or f"apple.{claims['sub']}@vantagelife.app"
    name = " ".join(filter(None, [payload.given_name, payload.family_name])) or apple_email
    session_token = f"st_{uuid.uuid4().hex}"
    user = await upsert_user_and_session(email=apple_email, name=name, picture=None, session_token=session_token)
    set_session_cookie(response, session_token)
    return {"user": user, "session_token": session_token}


@api_router.delete("/auth/account")
async def delete_account(response: Response, user: Dict[str, Any] = Depends(get_current_user)):
    await db.user_sessions.delete_many({"user_id": user["user_id"]})
    if user.get("agent_id"):
        await db.production_entries.delete_many({"agent_id": user["agent_id"]})
    await db.users.delete_one({"user_id": user["user_id"]})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# =========================================================
#                  HIERARCHY & FILTERING
# =========================================================

async def downline_agent_ids(agent_id: str) -> List[str]:
    """BFS over agent_profiles.upline_id. Includes agent_id itself plus every
    agent reachable downline from it. Shared by visible_agent_ids (read access,
    level_2+) and can_enter_for (write access, level_3+) so both walk the exact
    same hierarchy definition."""
    visible = {agent_id}
    queue = [agent_id]
    while queue:
        batch = queue
        queue = []
        cursor = db.agent_profiles.find({"upline_id": {"$in": batch}}, {"_id": 0, "agent_id": 1})
        async for doc in cursor:
            aid = doc["agent_id"]
            if aid not in visible:
                visible.add(aid)
                queue.append(aid)
    return list(visible)


async def visible_agent_ids(user: Dict[str, Any]) -> Optional[List[str]]:
    """Return list of agent_ids visible to this user, or None for full access (level_4)."""
    role = user.get("role", "level_1")
    if role == "level_4":
        return None  # full agency
    agent_id = user.get("agent_id")
    if not agent_id:
        return []
    if role == "level_1":
        return [agent_id]
    return await downline_agent_ids(agent_id)


async def can_enter_for(user: Dict[str, Any], target_agent_id: str) -> bool:
    """Nightly Numbers entry permission (distinct from read-visibility above).
    Entry starts one tier higher than viewing: only level_3+ (MGA/RGA) may
    submit on someone else's behalf, and only for their own downline — never
    for a sibling branch or a peer at the same level. Everyone may always
    enter for themselves."""
    own_agent_id = user.get("agent_id")
    if target_agent_id == own_agent_id:
        return True
    role = user.get("role", "level_1")
    if role not in ("level_3", "level_4"):
        return False
    if not own_agent_id:
        return False
    if role == "level_4":
        return True  # full agency, same as visible_agent_ids
    return target_agent_id in await downline_agent_ids(own_agent_id)


# =========================================================
#                       DASHBOARD
# =========================================================

def current_sales_day_str() -> str:
    return sales_day_for(now_detroit())


def previous_sales_day_str() -> str:
    return sales_day_for(now_detroit() - timedelta(days=1))


async def aggregate_alp(filter_q: Dict[str, Any]) -> Dict[str, float]:
    pipeline = [
        {"$match": filter_q},
        {"$group": {
            "_id": None,
            "gross_alp": {"$sum": "$gross_alp"},
            "net_alp": {"$sum": "$net_alp"},
            "sits": {"$sum": "$sits"},
            "sales": {"$sum": "$sales"},
        }},
    ]
    cur = db.production_entries.aggregate(pipeline)
    docs = [d async for d in cur]
    if not docs:
        return {"gross_alp": 0.0, "net_alp": 0.0, "sits": 0, "sales": 0}
    d = docs[0]
    return {"gross_alp": float(d.get("gross_alp", 0) or 0), "net_alp": float(d.get("net_alp", 0) or 0), "sits": int(d.get("sits", 0) or 0), "sales": int(d.get("sales", 0) or 0)}


def resolve_history_day(sales_day: Optional[str]) -> str:
    """Validate an optional read-only history day. Returns the current sales
    day when absent. History may not be in the future; the sales-day boundary
    itself (6 AM Detroit) stays defined solely by sales_day_for()."""
    today = current_sales_day_str()
    if not sales_day:
        return today
    try:
        requested = date.fromisoformat(sales_day)
    except ValueError:
        raise HTTPException(status_code=400, detail="sales_day must be YYYY-MM-DD")
    if requested > date.fromisoformat(today):
        raise HTTPException(status_code=400, detail="sales_day cannot be in the future")
    return requested.isoformat()


@api_router.get("/dashboard/summary")
async def dashboard_summary(sales_day: Optional[str] = None, user: Dict[str, Any] = Depends(require_agent)):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    day = resolve_history_day(sales_day)
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    base = {"sales_day": day}
    base_y = {"sales_day": prev}
    if ids is not None:
        base["agent_id"] = {"$in": ids}
        base_y["agent_id"] = {"$in": ids}
    today_agg = await aggregate_alp(base)
    yest_agg = await aggregate_alp(base_y)
    delta_pct = 0.0
    if yest_agg["gross_alp"] > 0:
        delta_pct = ((today_agg["gross_alp"] - yest_agg["gross_alp"]) / yest_agg["gross_alp"]) * 100.0
    return {
        "sales_day": day,
        "total_alp": today_agg["gross_alp"],
        "total_net_alp": today_agg["net_alp"],
        "total_sits": today_agg["sits"],
        "total_sales": today_agg["sales"],
        "delta_pct_vs_yesterday": round(delta_pct, 1),
        # The gate describes the live entry window; it has no meaning for history.
        "gate": gate_state() if day == today else None,
        "is_full_agency": ids is None,
        "is_history": day != today,
    }


@api_router.get("/dashboard/ticker")
async def dashboard_ticker(user: Dict[str, Any] = Depends(require_agent)):
    """Last 60 minutes of sales activity for the marquee ticker."""
    ids = await visible_agent_ids(user)
    cutoff = now_utc() - timedelta(minutes=60)
    q: Dict[str, Any] = {"submitted_at": {"$gte": cutoff}, "sales": {"$gt": 0}}
    if ids is not None:
        q["agent_id"] = {"$in": ids}
    cur = db.production_entries.find(q, {"_id": 0}).sort("submitted_at", -1).limit(50)
    items = []
    async for e in cur:
        agent = await db.agent_profiles.find_one({"agent_id": e["agent_id"]}, {"_id": 0})
        if not agent:
            continue
        items.append({
            "agent_name": agent["name"],
            "alp": float(e.get("gross_alp", 0)),
            "market": agent.get("office", ""),
            "reps": int(e.get("refs_obtained", 0)),
            "ts": iso_utc(e["submitted_at"]) if isinstance(e["submitted_at"], datetime) else e["submitted_at"],
        })
    return {"items": items}


@api_router.get("/dashboard/platinum-wall")
async def dashboard_platinum_wall(user: Dict[str, Any] = Depends(require_agent)):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    q: Dict[str, Any] = {"sales_day": today}
    if ids is not None:
        q["agent_id"] = {"$in": ids}
    pipeline = [
        {"$match": q},
        {"$group": {"_id": "$agent_id", "gross_alp": {"$sum": "$gross_alp"}, "sales": {"$sum": "$sales"}}},
        {"$sort": {"gross_alp": -1}},
    ]
    cur = db.production_entries.aggregate(pipeline)
    rows = [d async for d in cur]
    vets, rookies = [], []
    for r in rows:
        agent = await db.agent_profiles.find_one({"agent_id": r["_id"]}, {"_id": 0})
        if not agent:
            continue
        # Tenure must be explicitly recorded to appear on the wall. A missing
        # is_rookie field means UNKNOWN — not veteran — so unrecorded agents are
        # excluded from both buckets (shown as "Tenure unknown" in the Admin
        # panel) until leadership sets it, rather than defaulting into VETS.
        tenure = agent.get("is_rookie")
        if tenure is None:
            continue
        item = {
            "agent_id": agent["agent_id"],
            "name": agent["name"],
            "office": agent["office"],
            "gross_alp": float(r["gross_alp"]),
            "sales": int(r["sales"]),
            "is_rookie": bool(tenure),
            "role": agent.get("role", ""),
            "io_role": agent.get("io_role", ""),
            "phone": agent.get("phone", ""),
            "email": agent.get("email", ""),
        }
        if tenure:
            if len(rookies) < 3:
                rookies.append(item)
        else:
            if len(vets) < 3:
                vets.append(item)
        if len(vets) >= 3 and len(rookies) >= 3:
            break
    # Recent Platinum Rule recognition posts (global scope, newest first)
    platinum = [s async for s in db.shoutouts.find(
        {"type": "platinum_rule"}, {"_id": 0}).sort("ts", -1).limit(5)]
    for s in platinum:
        if isinstance(s.get("ts"), datetime):
            s["ts"] = iso_utc(s["ts"])
    return {"vets": vets, "rookies": rookies, "platinum_rule": platinum}


@api_router.get("/dashboard/offices")
async def dashboard_offices(sales_day: Optional[str] = None, user: Dict[str, Any] = Depends(require_agent)):
    ids = await visible_agent_ids(user)
    today = resolve_history_day(sales_day)
    # Discover offices from the actual agent_profiles so new RGAs appear automatically
    office_filter: Dict[str, Any] = {}
    if ids is not None:
        office_filter["agent_id"] = {"$in": ids}
    offices = [o for o in await db.agent_profiles.distinct("office", office_filter) if o]

    out = []
    for office in sorted(offices):
        agent_q: Dict[str, Any] = {"office": office}
        if ids is not None:
            agent_q["agent_id"] = {"$in": ids}
        office_agent_ids = [d["agent_id"] async for d in db.agent_profiles.find(agent_q, {"_id": 0, "agent_id": 1})]
        if not office_agent_ids:
            out.append({"office": office, "alp": 0, "sales": 0, "avg_deal": 0})
            continue
        agg = await aggregate_alp({"sales_day": today, "agent_id": {"$in": office_agent_ids}})
        avg = (agg["gross_alp"] / agg["sales"]) if agg["sales"] > 0 else 0
        out.append({
            "office": office,
            "alp": round(agg["gross_alp"], 2),
            "sales": agg["sales"],
            "avg_deal": round(avg, 2),
        })
    return {"offices": out}


# =========================================================
#                          PULSE
# =========================================================

@api_router.post("/pulse")
async def submit_pulse(payload: PulseIn, user: Dict[str, Any] = Depends(require_agent)):
    if not user.get("agent_id"):
        raise HTTPException(status_code=400, detail="No linked agent profile")

    target_agent_id = payload.target_agent_id or user["agent_id"]
    is_proxy_entry = target_agent_id != user["agent_id"]
    if is_proxy_entry and not await can_enter_for(user, target_agent_id):
        raise HTTPException(status_code=403, detail="You can only enter numbers for your own downline")

    agent = await db.agent_profiles.find_one({"agent_id": target_agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    now_local = now_detroit()
    max_buffer_days = MAX_UPLINE_BUFFER_DAYS if is_proxy_entry else MAX_SELF_BUFFER_DAYS
    if payload.sales_day:
        # Buffered flush: validate the client-supplied sales_day
        try:
            requested = datetime.strptime(payload.sales_day, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid sales_day format — use YYYY-MM-DD")
        today_date = now_local.date()
        delta = (today_date - requested).days
        if delta < 0:
            raise HTTPException(status_code=400, detail="sales_day cannot be in the future")
        if delta > max_buffer_days:
            if is_proxy_entry:
                raise HTTPException(status_code=400, detail=f"Buffered pulse expired — sales_day is more than {max_buffer_days} days old")
            raise HTTPException(status_code=400, detail=f"That day is outside your {max_buffer_days}-day self-edit window — ask your upline to enter this correction")
        sd = payload.sales_day
    else:
        sd = current_sales_day_str()

    entry = {
        "entry_id": f"pe_{uuid.uuid4().hex[:12]}",
        "agent_id": target_agent_id,
        "office": agent["office"],
        "sales_day": sd,
        "sets": payload.sets,
        "sits": payload.sits,
        "sales": payload.sales,
        "ots_sits": payload.ots_sits,
        "ots_sales": payload.ots_sales,
        "n1": payload.n1,
        "refs_obtained": payload.refs_obtained,
        "ref_sits": payload.ref_sits,
        "ref_sales": payload.ref_sales,
        "pos_sits": payload.pos_sits,
        "pos_sales": payload.pos_sales,
        "vet_sits": payload.vet_sits,
        "vet_sales": payload.vet_sales,
        "gross_alp": payload.gross_alp,
        "net_alp": payload.gross_alp,  # net == gross until eraser modifies
        "submitted_at": now_utc(),
        # Upline-entered data bypasses the 9 PM gate outright, per business rule.
        "submitted_on_time": True if is_proxy_entry else now_local.hour < 21,
        # entered_by is always derived from the authenticated session — never a
        # manual form field the submitter fills in themselves.
        "entered_by": user["user_id"],
        "entered_by_name": user.get("name"),
        "entered_by_role": user.get("role"),
        "is_proxy_entry": is_proxy_entry,
    }
    await db.production_entries.insert_one(entry)
    entry.pop("_id", None)

    # Trigger shoutouts
    await maybe_trigger_shoutouts(agent, entry)

    return {"ok": True, "entry": _ser_entry(entry)}


def _ser_entry(e: Dict[str, Any]) -> Dict[str, Any]:
    e = dict(e)
    e.pop("_id", None)
    if isinstance(e.get("submitted_at"), datetime):
        e["submitted_at"] = iso_utc(e["submitted_at"])
    return e


@api_router.get("/pulse/me/today")
async def pulse_me_today(agent_id: Optional[str] = None, user: Dict[str, Any] = Depends(require_agent)):
    if not user.get("agent_id"):
        return {"entries": [], "totals": {}, "gate": gate_state()}
    target_agent_id = agent_id or user["agent_id"]
    if target_agent_id != user["agent_id"] and not await can_enter_for(user, target_agent_id):
        raise HTTPException(status_code=403, detail="You can only view entry totals for your own downline")
    sd = current_sales_day_str()
    cur = db.production_entries.find({"agent_id": target_agent_id, "sales_day": sd}, {"_id": 0}).sort("submitted_at", -1)
    entries = [_ser_entry(e) async for e in cur]
    agg = await aggregate_alp({"agent_id": target_agent_id, "sales_day": sd})
    return {"entries": entries, "totals": agg, "gate": gate_state(), "sales_day": sd}


@api_router.get("/pulse/me/streak")
async def pulse_streak(agent_id: Optional[str] = None, user: Dict[str, Any] = Depends(require_agent)):
    if not user.get("agent_id"):
        return {"streak": 0}
    target_agent_id = agent_id or user["agent_id"]
    if target_agent_id != user["agent_id"] and not await can_enter_for(user, target_agent_id):
        raise HTTPException(status_code=403, detail="You can only view streak for your own downline")
    streak = 0
    d = now_detroit()
    for i in range(0, 30):
        sd = sales_day_for(d - timedelta(days=i))
        on_time = await db.production_entries.find_one({"agent_id": target_agent_id, "sales_day": sd, "submitted_on_time": True})
        if on_time:
            streak += 1
        else:
            break
    return {"streak": streak}


# =========================================================
#              PUSH NOTIFICATIONS — 9 PM ESCALATION
# =========================================================
# Escalation ladder, exact wording and timing per owner spec (2026-07-26).
# "Everybody but MGA/RGA" per the earlier instruction: only level_1/level_2
# agents are checked for their OWN missing pulse — an MGA/RGA never gets
# escalated on themselves, though they DO appear as reach targets when their
# downline is missing (see ancestor_reach below).
#
# ancestor_reach is how many steps up the agent's own upline_id chain get
# notified alongside them at that stage; None means "every remaining
# ancestor" (the 11:30 PM full-chain stage). The table's example used SA/GA/
# MGA as the first three ancestors, which is simply "walk upline_id from the
# agent" — that generalizes correctly even for agents with no SA in their
# personal chain (e.g. reporting straight to a GA).
ESCALATION_STAGES = [
    {"hour": 21, "minute": 0,  "stage": "reminder",    "ancestor_reach": 0,    "message": "Don't forget to log your numbers - even if you had no sales today."},
    {"hour": 21, "minute": 30, "stage": "overdue",     "ancestor_reach": 1,    "message": "Your 9 PM pulse is late. Submit now to keep your streak."},
    {"hour": 22, "minute": 0,  "stage": "escalated",   "ancestor_reach": 2,    "message": "Pulse not in. Your GA is being notified - submit now."},
    {"hour": 22, "minute": 30, "stage": "final_warn",  "ancestor_reach": 3,    "message": "Pulse not in. Your MGA is being notified. Log your numbers immediately."},
    {"hour": 23, "minute": 0,  "stage": "last_call",   "ancestor_reach": 3,    "message": "Pulse must be submitted before midnight. Leadership has been notified."},
    {"hour": 23, "minute": 30, "stage": "window_closing", "ancestor_reach": None, "message": "Final call! Submit your numbers now, final cutoff in 30 minutes."},
]
# How long after the exact mark a stage is still eligible to fire — covers a
# scheduler tick that lands a little late. notification_log's unique index is
# the real guard against duplicates; this window just bounds how late is
# still "on time" for a stage instead of silently skipping it forever.
STAGE_FIRE_WINDOW_MINUTES = 5


class PushTokenIn(BaseModel):
    push_token: str


@api_router.post("/push/register")
async def register_push_token(payload: PushTokenIn, user: Dict[str, Any] = Depends(require_agent)):
    """Upsert this device's Expo push token against the logged-in user. One
    token per user_id for now — a second device overwrites the first."""
    await db.push_tokens.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"user_id": user["user_id"], "agent_id": user.get("agent_id"),
                  "push_token": payload.push_token, "updated_at": now_utc()}},
        upsert=True,
    )
    return {"ok": True}


@api_router.post("/push/unregister")
async def unregister_push_token(user: Dict[str, Any] = Depends(require_agent)):
    await db.push_tokens.delete_one({"user_id": user["user_id"]})
    return {"ok": True}


async def _ancestor_chain(agent_id: str) -> List[str]:
    """Walk upline_id from agent_id up to the root. Does not include agent_id itself."""
    chain: List[str] = []
    current = agent_id
    seen = {agent_id}
    for _ in range(10):  # hierarchy is 4 tiers deep; 10 is a generous safety cap
        doc = await db.agent_profiles.find_one({"agent_id": current}, {"_id": 0, "upline_id": 1})
        if not doc or not doc.get("upline_id") or doc["upline_id"] in seen:
            break
        chain.append(doc["upline_id"])
        seen.add(doc["upline_id"])
        current = doc["upline_id"]
    return chain


async def send_expo_push(push_tokens: List[str], title: str, body: str) -> None:
    """Send via Expo's push HTTP API. No credentials needed for the standard
    managed workflow — just valid ExponentPushToken[...] strings."""
    if not push_tokens:
        return
    messages = [{"to": t, "title": title, "body": body, "sound": "default"} for t in push_tokens]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client_http:
            await client_http.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
    except Exception as e:
        logger.warning(f"Expo push send failed: {e}")


def _current_escalation_stage(dt_local: datetime) -> Optional[Dict[str, Any]]:
    for stage in ESCALATION_STAGES:
        mark = dt_local.replace(hour=stage["hour"], minute=stage["minute"], second=0, microsecond=0)
        delta_minutes = (dt_local - mark).total_seconds() / 60
        if 0 <= delta_minutes < STAGE_FIRE_WINDOW_MINUTES:
            return stage
    return None


def _format_upline_summary(missing_names):
    """Consolidated roll-call — ONE message per upline recipient naming every
    missing person under them, never one push per missing agent."""
    if len(missing_names) == 1:
        return f"{missing_names[0]} has not submitted numbers."
    return f"The following have not submitted numbers: {', '.join(missing_names)}."


async def _already_logged(agent_id, sales_day, log_stage):
    existing = await db.notification_log.find_one(
        {"agent_id": agent_id, "sales_day": sales_day, "stage": log_stage}, {"_id": 0, "agent_id": 1},
    )
    return existing is not None


async def _log_and_check(agent_id, sales_day, log_stage):
    """Returns True if this is a fresh send (not previously logged)."""
    if await _already_logged(agent_id, sales_day, log_stage):
        return False
    try:
        await db.notification_log.insert_one({
            "agent_id": agent_id, "sales_day": sales_day, "stage": log_stage, "sent_at": now_utc(),
        })
    except Exception:
        return False  # race: another tick logged it between our check and insert
    return True


async def run_pulse_escalation_check():
    """Idempotent per (agent_id, sales_day, log_stage) -- safe to call more than
    once. Checks only level_1/level_2 agents against today's production_entries
    ('everybody but MGA/RGA' rule).

    Two distinct message types per stage:
    - The missing agent gets their own personal reminder -- the exact stage
      wording, sent to them alone.
    - Each in-reach upline gets ONE consolidated roll-call push naming every
      missing person in their downline that stage reaches -- never one push
      per missing agent. MGA/RGA are excluded from this entirely until the
      final (11:30 PM) stage, where the full remaining chain is included.
    """
    now_local = now_detroit()
    stage = _current_escalation_stage(now_local)
    if not stage:
        return {"ok": True, "stage": None, "agent_notified": 0, "upline_notified": 0}

    today = current_sales_day_str()
    submitted_ids = {
        d["agent_id"] async for d in db.production_entries.find({"sales_day": today}, {"_id": 0, "agent_id": 1})
    }
    candidates = [
        a async for a in db.agent_profiles.find({"role": {"$in": ["level_1", "level_2"]}}, {"_id": 0, "agent_id": 1, "name": 1})
        if a["agent_id"] not in submitted_ids
    ]
    roles_by_id = {
        a["agent_id"]: a["role"] async for a in db.agent_profiles.find({}, {"_id": 0, "agent_id": 1, "role": 1})
    }

    # Personal reminder -- agent only, exact stage wording.
    agent_notified = 0
    for a in candidates:
        agent_id = a["agent_id"]
        if not await _log_and_check(agent_id, today, stage["stage"]):
            continue
        tokens = [t["push_token"] async for t in db.push_tokens.find({"agent_id": agent_id}, {"_id": 0, "push_token": 1})]
        await send_expo_push(tokens, "VantageLife", stage["message"])
        agent_notified += 1

    # Consolidated upline roll-call -- one push per upline recipient, naming
    # every missing downline agent this stage reaches for them.
    is_final_stage = stage["ancestor_reach"] is None
    upline_missing = {}
    for a in candidates:
        chain = await _ancestor_chain(a["agent_id"])
        sliced = chain if is_final_stage else chain[: stage["ancestor_reach"]]
        if not is_final_stage:
            sliced = [aid for aid in sliced if roles_by_id.get(aid) not in ("level_3", "level_4")]
        for upline_id in sliced:
            upline_missing.setdefault(upline_id, []).append(a["name"])

    upline_notified = 0
    upline_log_stage = f"{stage['stage']}_upline"
    for upline_id, missing_names in upline_missing.items():
        if not await _log_and_check(upline_id, today, upline_log_stage):
            continue
        tokens = [t["push_token"] async for t in db.push_tokens.find({"agent_id": upline_id}, {"_id": 0, "push_token": 1})]
        await send_expo_push(tokens, "VantageLife", _format_upline_summary(missing_names))
        upline_notified += 1

    return {"ok": True, "stage": stage["stage"], "agent_notified": agent_notified, "upline_notified": upline_notified}


@api_router.post("/admin/run-notification-check")
async def admin_run_notification_check(user: Dict[str, Any] = Depends(require_admin)):
    """Manual trigger for QA -- fires the check immediately regardless of the
    scheduler loop's timing, still gated by the same idempotent log."""
    return await run_pulse_escalation_check()


# =========================================================
#                       MY UPLINE
# =========================================================

@api_router.get("/my-upline")
async def my_upline(user: Dict[str, Any] = Depends(require_agent)):
    agent_id = user.get("agent_id")
    if not agent_id:
        return {"upline": None}
    agent = await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0, "upline_id": 1})
    if not agent or not agent.get("upline_id"):
        return {"upline": None}
    upline = await db.agent_profiles.find_one(
        {"agent_id": agent["upline_id"]},
        {"_id": 0, "name": 1, "phone": 1, "email": 1, "role": 1, "io_role": 1, "office": 1}
    )
    if not upline:
        return {"upline": None}
    return {"upline": upline}


# =========================================================
#                          TEAM
# =========================================================

@api_router.get("/team")
async def team_view(user: Dict[str, Any] = Depends(require_level(2))):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    q: Dict[str, Any] = {"sales_day": today}
    if ids is not None:
        q["agent_id"] = {"$in": ids}
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$agent_id",
            "gross_alp": {"$sum": "$gross_alp"},
            "net_alp": {"$sum": "$net_alp"},
            "sits": {"$sum": "$sits"},
            "sales": {"$sum": "$sales"},
            "n1": {"$sum": "$n1"},
            "refs_obtained": {"$sum": "$refs_obtained"},
        }},
        {"$sort": {"gross_alp": -1}},
    ]
    rows = [d async for d in db.production_entries.aggregate(pipeline)]
    agent_q: Dict[str, Any] = {}
    if ids is not None:
        agent_q["agent_id"] = {"$in": ids}
    agents = {a["agent_id"]: a async for a in db.agent_profiles.find(agent_q, {"_id": 0})}
    out = []
    for r in rows:
        a = agents.get(r["_id"])
        if not a:
            continue
        sales = int(r["sales"])
        sits = int(r["sits"])
        n1 = int(r.get("n1", 0))
        # N1 excluded per business rule: Close Rate = Sales / (Sits - N1)
        es = metrics.eligible_sits(sits, n1)
        close = metrics.close_rate(sales, sits, n1)
        avg_deal = (float(r["gross_alp"]) / sales) if sales > 0 else 0
        alerts = []
        if es >= 3 and close < 50:
            alerts.append("low_close_ratio")
        if sales >= 1 and avg_deal < 1200:
            alerts.append("low_avg_deal")
        out.append({
            "agent_id": a["agent_id"],
            "name": a["name"],
            "office": a["office"],
            "role": a["role"],
            "io_role": a.get("io_role") or "",
            "phone": a.get("phone") or "",
            "email": a.get("email") or "",
            "is_rookie": a.get("is_rookie", False),
            "gross_alp": float(r["gross_alp"]),
            "net_alp": float(r["net_alp"]),
            "sits": sits,
            "sales": sales,
            "close_ratio": round(close, 1),
            "avg_deal": round(avg_deal, 2),
            "alerts": alerts,
        })
    # Add agents with no entries
    listed = {x["agent_id"] for x in out}
    for aid, a in agents.items():
        if aid not in listed:
            out.append({
                "agent_id": aid, "name": a["name"], "office": a["office"], "role": a["role"],
                "io_role": a.get("io_role") or "", "phone": a.get("phone") or "", "email": a.get("email") or "",
                "is_rookie": a.get("is_rookie", False),
                "gross_alp": 0, "net_alp": 0, "sits": 0, "sales": 0,
                "close_ratio": 0, "avg_deal": 0, "alerts": ["no_pulse"],
            })
    return {"team": out, "sales_day": today}


# =========================================================
#                       SHOUTOUTS
# =========================================================

async def maybe_trigger_shoutouts(agent: Dict[str, Any], entry: Dict[str, Any]):
    sd = entry["sales_day"]
    # Player's Club: $10k+ Gross ALP in a sales day
    agg = await aggregate_alp({"agent_id": agent["agent_id"], "sales_day": sd})
    if agg["gross_alp"] >= 10000:
        existing = await db.shoutouts.find_one({"type": "players_club", "agent_id": agent["agent_id"], "sales_day": sd})
        if not existing:
            await db.shoutouts.insert_one({
                "shoutout_id": f"so_{uuid.uuid4().hex[:10]}",
                "type": "players_club",
                "scope": "global",
                "agent_id": agent["agent_id"],
                "agent_name": agent["name"],
                "office": agent["office"],
                "ga_team_id": agent.get("ga_id"),
                "sales_day": sd,
                "amount": agg["gross_alp"],
                "ts": now_utc(),
            })
    # First Deal Milestone (only first ever sale): scope = ga_team
    total_sales = await db.production_entries.aggregate([
        {"$match": {"agent_id": agent["agent_id"]}},
        {"$group": {"_id": None, "sales": {"$sum": "$sales"}}},
    ]).to_list(1)
    if total_sales and total_sales[0]["sales"] == entry["sales"] and entry["sales"] > 0:
        existing = await db.shoutouts.find_one({"type": "first_deal", "agent_id": agent["agent_id"]})
        if not existing:
            await db.shoutouts.insert_one({
                "shoutout_id": f"so_{uuid.uuid4().hex[:10]}",
                "type": "first_deal",
                "scope": "ga_team",
                "ga_team_id": agent.get("ga_id"),
                "agent_id": agent["agent_id"],
                "agent_name": agent["name"],
                "office": agent["office"],
                "sales_day": sd,
                "ts": now_utc(),
            })
    # Streak: 5+ consecutive on-time pulse submissions
    streak = 0
    d = now_detroit()
    for i in range(0, 30):
        sdi = sales_day_for(d - timedelta(days=i))
        on_time = await db.production_entries.find_one({"agent_id": agent["agent_id"], "sales_day": sdi, "submitted_on_time": True})
        if on_time:
            streak += 1
        else:
            break
    if streak >= 5:
        existing = await db.shoutouts.find_one({"type": "streak", "agent_id": agent["agent_id"], "streak": streak})
        if not existing:
            await db.shoutouts.insert_one({
                "shoutout_id": f"so_{uuid.uuid4().hex[:10]}",
                "type": "streak",
                "scope": "global",
                "agent_id": agent["agent_id"],
                "agent_name": agent["name"],
                "office": agent["office"],
                "ga_team_id": agent.get("ga_id"),
                "sales_day": sd,
                "streak": streak,
                "ts": now_utc(),
            })


@api_router.get("/shoutouts")
async def list_shoutouts(user: Dict[str, Any] = Depends(require_agent)):
    role = user.get("role", "level_1")
    user_agent_id = user.get("agent_id")
    user_agent = None
    if user_agent_id:
        user_agent = await db.agent_profiles.find_one({"agent_id": user_agent_id}, {"_id": 0})

    visible_ids = await visible_agent_ids(user)
    q: Dict[str, Any] = {}
    cur = db.shoutouts.find(q, {"_id": 0}).sort("ts", -1).limit(200)
    out = []
    async for s in cur:
        scope = s.get("scope", "global")
        if scope == "global":
            out.append(s)
            continue
        if scope == "ga_team":
            # Visible only to agents under same GA team OR level 4
            if role == "level_4":
                out.append(s); continue
            if user_agent and (user_agent.get("ga_id") == s.get("ga_team_id") or user_agent_id == s.get("ga_team_id")):
                out.append(s); continue
            # If the user IS the agent, also visible
            if user_agent_id == s.get("agent_id"):
                out.append(s); continue
    # Enrich with contact info so names are tappable (batch lookup, no N+1)
    shoutout_agent_ids = list({s.get("agent_id") for s in out if s.get("agent_id")})
    contacts = {a["agent_id"]: a async for a in db.agent_profiles.find(
        {"agent_id": {"$in": shoutout_agent_ids}},
        {"_id": 0, "agent_id": 1, "role": 1, "io_role": 1, "phone": 1, "email": 1})}
    for s in out:
        c = contacts.get(s.get("agent_id"), {})
        s["role"] = c.get("role", "")
        s["io_role"] = c.get("io_role", "")
        s["phone"] = c.get("phone", "")
        s["email"] = c.get("email", "")
        if isinstance(s.get("ts"), datetime):
            s["ts"] = iso_utc(s["ts"])
    return {"shoutouts": out}


# =========================================================
#              PLATINUM RULE NOMINATIONS
# =========================================================
# The Platinum Rule: do more for others than they would do for themselves.
# Any agent may nominate any other agent. Nominations surface to the
# nominee's upline (GA+). At PLATINUM_ENDORSE_THRESHOLD endorsements the
# nomination flags threshold_met, badging the MGA/RGA inbox; posting to
# the Platinum Wall is a deliberate MGA/RGA (level_3+) action.

PLATINUM_ENDORSE_THRESHOLD = 3


@api_router.get("/agents/directory")
async def agents_directory(user: Dict[str, Any] = Depends(require_agent)):
    """Name-only roster for the nomination picker. Names/offices are already
    org-visible via the ticker and global shoutouts; no production data here."""
    out = [a async for a in db.agent_profiles.find(
        {}, {"_id": 0, "agent_id": 1, "name": 1, "office": 1}).sort("name", 1)]
    return {"agents": out}


class NominationIn(BaseModel):
    nominee_agent_id: str
    reason: str = Field(min_length=10, max_length=500)


async def _nomination_visible_to(user: Dict[str, Any], nomination: Dict[str, Any]) -> bool:
    ids = await visible_agent_ids(user)
    return ids is None or nomination["nominee_agent_id"] in ids


@api_router.post("/nominations")
async def create_nomination(payload: NominationIn, user: Dict[str, Any] = Depends(require_agent)):
    nominee = await db.agent_profiles.find_one({"agent_id": payload.nominee_agent_id}, {"_id": 0})
    if not nominee:
        raise HTTPException(status_code=404, detail="Nominee not found")
    if nominee["agent_id"] == user.get("agent_id"):
        raise HTTPException(status_code=400, detail="You can't nominate yourself")
    doc = {
        "nomination_id": f"nom_{uuid.uuid4().hex[:10]}",
        "nominee_agent_id": nominee["agent_id"],
        "nominee_name": nominee["name"],
        "nominee_office": nominee["office"],
        "nominator_agent_id": user["agent_id"],
        "nominator_name": user.get("name", ""),
        "reason": payload.reason.strip(),
        "status": "open",
        "endorsements": [],
        "created_at": now_utc(),
    }
    await db.nominations.insert_one(doc)
    doc.pop("_id", None)
    doc["created_at"] = iso_utc(doc["created_at"])
    return {"ok": True, "nomination": doc}


@api_router.get("/nominations")
async def list_nominations(status: Optional[str] = None, user: Dict[str, Any] = Depends(require_level(2))):
    ids = await visible_agent_ids(user)
    q: Dict[str, Any] = {}
    if ids is not None:
        q["nominee_agent_id"] = {"$in": ids}
    if status:
        q["status"] = status
    out = [n async for n in db.nominations.find(q, {"_id": 0}).sort("created_at", -1).limit(200)]
    # Attach nominee contact/role so the app can open the agent contact card
    # straight from the inbox. Same audience as /api/team (the nominee's
    # upline, level_2+), which already exposes these fields.
    nominee_ids = list({n["nominee_agent_id"] for n in out})
    profiles = {p["agent_id"]: p async for p in db.agent_profiles.find(
        {"agent_id": {"$in": nominee_ids}},
        {"_id": 0, "agent_id": 1, "role": 1, "io_role": 1, "phone": 1, "email": 1})}
    for n in out:
        p = profiles.get(n["nominee_agent_id"], {})
        n["nominee_role"] = p.get("role", "level_1")
        n["nominee_io_role"] = p.get("io_role") or ""
        n["nominee_phone"] = p.get("phone") or ""
        n["nominee_email"] = p.get("email") or ""
        if isinstance(n.get("created_at"), datetime):
            n["created_at"] = iso_utc(n["created_at"])
        for e in n.get("endorsements", []):
            if isinstance(e.get("ts"), datetime):
                e["ts"] = iso_utc(e["ts"])
    return {"nominations": out, "threshold": PLATINUM_ENDORSE_THRESHOLD}


@api_router.post("/nominations/{nomination_id}/endorse")
async def endorse_nomination(nomination_id: str, user: Dict[str, Any] = Depends(require_level(2))):
    nom = await db.nominations.find_one({"nomination_id": nomination_id}, {"_id": 0})
    if not nom:
        raise HTTPException(status_code=404, detail="Nomination not found")
    if not await _nomination_visible_to(user, nom):
        raise HTTPException(status_code=403, detail="Nominee is not in your team")
    if nom["status"] not in ("open", "threshold_met"):
        raise HTTPException(status_code=400, detail="Nomination is no longer open")
    if any(e["agent_id"] == user["agent_id"] for e in nom.get("endorsements", [])):
        raise HTTPException(status_code=400, detail="You already endorsed this nomination")
    endorsement = {"agent_id": user["agent_id"], "name": user.get("name", ""), "ts": now_utc()}
    endorsements = nom.get("endorsements", []) + [endorsement]
    new_status = "threshold_met" if len(endorsements) >= PLATINUM_ENDORSE_THRESHOLD else nom["status"]
    await db.nominations.update_one(
        {"nomination_id": nomination_id},
        {"$set": {"endorsements": endorsements, "status": new_status}},
    )
    return {"ok": True, "status": new_status, "endorsement_count": len(endorsements),
            "threshold": PLATINUM_ENDORSE_THRESHOLD}


@api_router.post("/nominations/{nomination_id}/post-to-wall")
async def post_nomination_to_wall(nomination_id: str, user: Dict[str, Any] = Depends(require_level(3))):
    nom = await db.nominations.find_one({"nomination_id": nomination_id}, {"_id": 0})
    if not nom:
        raise HTTPException(status_code=404, detail="Nomination not found")
    if not await _nomination_visible_to(user, nom):
        raise HTTPException(status_code=403, detail="Nominee is not in your team")
    if nom["status"] != "threshold_met":
        raise HTTPException(status_code=400, detail="Nomination has not reached the endorsement threshold")
    nominee = await db.agent_profiles.find_one({"agent_id": nom["nominee_agent_id"]}, {"_id": 0})
    shoutout = {
        "shoutout_id": f"so_{uuid.uuid4().hex[:10]}",
        "type": "platinum_rule",
        "scope": "global",
        "agent_id": nom["nominee_agent_id"],
        "agent_name": nom["nominee_name"],
        "office": nom["nominee_office"],
        "ga_team_id": (nominee or {}).get("ga_id"),
        "sales_day": current_sales_day_str(),
        "reason": nom["reason"],
        "nominator_name": nom["nominator_name"],
        "endorsement_count": len(nom.get("endorsements", [])),
        "posted_by": user.get("name", ""),
        "ts": now_utc(),
    }
    await db.shoutouts.insert_one(shoutout)
    await db.nominations.update_one(
        {"nomination_id": nomination_id},
        {"$set": {"status": "posted", "posted_at": now_utc(), "posted_by_agent_id": user["agent_id"]}},
    )
    shoutout.pop("_id", None)
    shoutout["ts"] = iso_utc(shoutout["ts"])
    return {"ok": True, "shoutout": shoutout}


# =========================================================
#                  MANAGER COMMAND PANEL
# =========================================================

@api_router.post("/manager/erase")
async def manager_erase(payload: EraseIn, user: Dict[str, Any] = Depends(require_level(3))):
    # Same downline scoping as entry (can_enter_for): an MGA may only correct
    # their own downline; RGA (level_4) has full agency, same as visible_agent_ids.
    if not await can_enter_for(user, payload.agent_id):
        raise HTTPException(status_code=403, detail="You can only correct numbers for your own downline")
    if len(payload.reason.strip()) < 10:
        raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")
    agent = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Sum current net_alp for the day
    agg = await aggregate_alp({"agent_id": payload.agent_id, "sales_day": payload.sales_day})
    original_net = agg["net_alp"]
    # Apply adjustment by recording a synthetic "adjustment" entry to align net total to new value
    delta = payload.new_alp - original_net
    adj = {
        "entry_id": f"adj_{uuid.uuid4().hex[:10]}",
        "agent_id": payload.agent_id,
        "office": agent["office"],
        "sales_day": payload.sales_day,
        "sets": 0, "sits": 0, "sales": 0,
        "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0,
        "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0,
        "gross_alp": 0,                  # gross UNCHANGED on Platinum Wall
        "net_alp": delta,                # net adjusted
        "submitted_at": now_utc(),
        "submitted_on_time": True,
        "is_adjustment": True,
        "reason": payload.reason,
    }
    await db.production_entries.insert_one(adj)
    audit = {
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now_utc(),
        "action": "adjust_alp",
        "agent_id": payload.agent_id,
        "agent_name": agent["name"],
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "original_value": original_net,
        "new_value": payload.new_alp,
        "delta": delta,
        "sales_day": payload.sales_day,
        "reason": payload.reason,
    }
    await db.audit_log.insert_one(audit)
    audit.pop("_id", None)
    audit["ts"] = iso_utc(audit["ts"])
    return {"ok": True, "audit": audit, "delta": delta}


@api_router.get("/manager/audit")
async def manager_audit(user: Dict[str, Any] = Depends(require_level(4))):
    cur = db.audit_log.find({}, {"_id": 0}).sort("ts", -1).limit(200)
    items = []
    async for a in cur:
        if isinstance(a.get("ts"), datetime):
            a["ts"] = iso_utc(a["ts"])
        items.append(a)
    return {"items": items}


# =========================================================
#                    HISTORICAL VAULT
# =========================================================

@api_router.get("/vault/weeks")
async def vault_weeks(user: Dict[str, Any] = Depends(require_level(4))):
    cur = db.historical_vault.find({}, {"_id": 0}).sort("week_start", -1).limit(8)
    items = [d async for d in cur]
    for it in items:
        if isinstance(it.get("archived_at"), datetime):
            it["archived_at"] = iso_utc(it["archived_at"])
    return {"weeks": items}


@api_router.get("/vault/compare")
async def vault_compare(week_a: str, week_b: str, user: Dict[str, Any] = Depends(require_level(4))):
    a = await db.historical_vault.find_one({"week_start": week_a}, {"_id": 0})
    b = await db.historical_vault.find_one({"week_start": week_b}, {"_id": 0})
    if not a or not b:
        raise HTTPException(status_code=404, detail="Week not found")
    metrics = ["gross_alp", "net_alp", "sales", "sits"]
    delta = {}
    for m in metrics:
        av = float(a.get("totals", {}).get(m, 0) or 0)
        bv = float(b.get("totals", {}).get(m, 0) or 0)
        pct = ((bv - av) / av * 100.0) if av else 0.0
        delta[m] = {"a": av, "b": bv, "delta": bv - av, "pct": round(pct, 1)}
    for w in (a, b):
        if isinstance(w.get("archived_at"), datetime):
            w["archived_at"] = iso_utc(w["archived_at"])
    return {"a": a, "b": b, "delta": delta}


@api_router.post("/admin/wednesday-reset")
async def wednesday_reset(user: Dict[str, Any] = Depends(require_level(4))):
    """Archive current week's data into historical_vault, then clear/mark active dataset."""
    now = now_detroit()
    # Business rule: the weekly reset may only run on Wednesday at/after
    # 2:00 PM America/Detroit. Without this guard the endpoint would
    # archive-and-wipe production_entries on any day at any time.
    if now.weekday() != 2 or now.hour < 14:
        raise HTTPException(
            status_code=403,
            detail="Weekly reset is only allowed on Wednesday at or after 2:00 PM (America/Detroit).",
        )
    today = now.date()
    # Determine current week start (Wed-to-Wed): roll back to most recent Wednesday
    weekday = today.weekday()  # Mon=0..Sun=6; Wed=2
    days_since_wed = (weekday - 2) % 7
    week_start = (today - timedelta(days=days_since_wed)).isoformat()
    # Snapshot totals
    totals_pipe = [
        {"$group": {
            "_id": None,
            "gross_alp": {"$sum": "$gross_alp"},
            "net_alp": {"$sum": "$net_alp"},
            "sits": {"$sum": "$sits"},
            "sales": {"$sum": "$sales"},
        }},
    ]
    docs = [d async for d in db.production_entries.aggregate(totals_pipe)]
    totals = {"gross_alp": 0, "net_alp": 0, "sits": 0, "sales": 0}
    if docs:
        d = docs[0]
        totals = {"gross_alp": float(d.get("gross_alp", 0) or 0), "net_alp": float(d.get("net_alp", 0) or 0), "sits": int(d.get("sits", 0) or 0), "sales": int(d.get("sales", 0) or 0)}

    # Per-office breakdown — discover from DB so all RGA offices are included
    by_office = {}
    all_offices = [o for o in await db.agent_profiles.distinct("office") if o]
    for office in all_offices:
        ag_ids = [a["agent_id"] async for a in db.agent_profiles.find({"office": office}, {"_id": 0, "agent_id": 1})]
        a = await aggregate_alp({"agent_id": {"$in": ag_ids}})
        by_office[office] = a

    snapshot = {
        "week_id": f"wk_{uuid.uuid4().hex[:8]}",
        "week_start": week_start,
        "archived_at": now_utc(),
        "totals": totals,
        "by_office": by_office,
        "agent_count": await db.agent_profiles.count_documents({}),
    }
    await db.historical_vault.insert_one(snapshot)
    # Reset by clearing production entries (in real app you'd flag instead of delete)
    await db.production_entries.delete_many({})
    snapshot.pop("_id", None)
    snapshot["archived_at"] = iso_utc(snapshot["archived_at"])
    return {"ok": True, "snapshot": snapshot}


# =========================================================
#                          SEED
# =========================================================

@api_router.post("/seed")
async def seed_data(request: Request, payload: Optional[Dict[str, Any]] = Body(default=None)):
    """Seed 174 agents across 5 offices with hierarchy + recent production for ticker.
    Anonymous calls are allowed only when DB is empty (first-time bootstrap).
    Forced re-seed requires level_4 authentication.
    """
    force = bool(payload and payload.get("force"))
    existing = await db.agent_profiles.count_documents({})
    if force:
        # Require RGA auth for destructive force-reseed
        try:
            user = await get_current_user(request)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Authenticated RGA required for force-reseed")
        if user.get("role") != "level_4":
            raise HTTPException(status_code=403, detail="Only RGA can force-reseed")
    if existing > 0 and not force:
        return {"ok": True, "seeded": False, "message": f"Already seeded ({existing} agents)"}
    if force:
        await db.agent_profiles.delete_many({})
        await db.production_entries.delete_many({})
        await db.shoutouts.delete_many({})
        await db.audit_log.delete_many({})
        await db.historical_vault.delete_many({})

    random.seed(42)
    FIRST_NAMES = ["Marcus","Tasha","Jordan","Avery","Ricardo","Sienna","Devin","Priya","Hank","Maya","Theo","Lena","Jasper","Cameron","Brielle","Omar","Zara","Nicolas","Hailey","Kingston","Iris","Tobias","Gianna","Bryson","Laila","Rashid","Adriana","Caleb","Imani","Diego","Sloane","Niko","Selena","Ezra","Halle","Cyrus","Phoebe","Malachi","Esme","Tristan","Aria","Lucian","Maren","Holden","Saoirse","Elias","Wren","Rohan","Lyric","Kade","Magnolia","Soren","Briar","Dax","Vera","Boaz","Calla","Reuben","Indira","Rocco","Lyra","Knox","Mira","Beck","Astrid","Ronan","Iris","Hugo","Nadia","Adler","Juno"]
    LAST_NAMES = ["Reyes","Carter","Nguyen","Patel","Brooks","Rivera","Bauer","Sosa","Donovan","Wagner","Pham","Hayes","Booker","Ortiz","Kim","Bell","Walsh","Morgan","Cole","Hudson","Mendez","Lawson","Greer","Burke","Salinas","Vargas","Holland","Rios","Faulkner","Pearce","Trent","McKenzie","Gallagher","Briggs","Frye","Cassidy","Locke","Sutton","Hartley","Driscoll","Pruitt","Vance","Whitford","Crane","Dunn","Hollis","Tate","Quinn","Rourke","Slade"]
    STATES = ["MI","OH","IL","IN","WI","KY","MN","MO","TN","NY","TX","FL","CA","GA","NC","PA","VA","MA"]

    # Build hierarchy: 1 RGA → 4 MGAs → 8 GAs → ~161 agents = 174 total
    agents: List[Dict[str, Any]] = []
    used_emails = set()

    def mk_agent(role: str, office: str, name: str, upline_id: Optional[str], ga_id: Optional[str], is_rookie: bool = False) -> Dict[str, Any]:
        first, last = name.split(" ", 1) if " " in name else (name, "Smith")
        base_email = f"{first.lower()}.{last.lower()}".replace(" ", "")
        email = f"{base_email}@aopremiere.com"
        n = 1
        while email in used_emails:
            n += 1
            email = f"{base_email}{n}@aopremiere.com"
        used_emails.add(email)
        return {
            "agent_id": f"ag_{uuid.uuid4().hex[:10]}",
            "name": name,
            "license": f"LIC-{random.randint(100000, 999999)}",
            "email": email,
            "phone": f"+1-{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}",
            "resident_state": random.choice(STATES),
            "office": office,
            "role": role,
            "upline_id": upline_id,
            "ga_id": ga_id,
            "is_rookie": is_rookie,
            "joined_at": now_utc() - timedelta(days=random.randint(15, 1000)),
        }

    def name_pool():
        return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

    # 1 RGA
    rga = mk_agent("level_4", "Dearborn", "Vance Holloway", None, None, False)
    agents.append(rga)

    # 4 MGAs across offices
    mga_offices = ["MCM", "AMP", "Heritage", "Siren"]
    mgas: List[Dict[str, Any]] = []
    for off in mga_offices:
        m = mk_agent("level_3", off, name_pool(), rga["agent_id"], None, False)
        mgas.append(m); agents.append(m)

    # 8 GAs (2 per MGA)
    gas: List[Dict[str, Any]] = []
    for mga in mgas:
        for _ in range(2):
            g = mk_agent("level_2", mga["office"], name_pool(), mga["agent_id"], None, False)
            gas.append(g); agents.append(g)

    # 161 Agents distributed across GAs and offices
    agents_count = 174 - len(agents)
    for i in range(agents_count):
        ga = gas[i % len(gas)]
        # vary office: 70% same as GA, 30% any office
        office = ga["office"] if random.random() < 0.7 else random.choice(_SEED_OFFICES)
        is_rookie = random.random() < 0.30
        a = mk_agent("level_1", office, name_pool(), ga["agent_id"], ga["agent_id"], is_rookie)
        agents.append(a)

    await db.agent_profiles.insert_many([dict(a) for a in agents])

    # Seed production entries — last 7 days. Recent 60 min has many for ticker.
    today = now_detroit()
    entries: List[Dict[str, Any]] = []
    for d_offset in range(0, 7):
        day_local = today - timedelta(days=d_offset)
        sd = sales_day_for(day_local)
        for a in agents:
            if a["role"] != "level_1" and a["role"] != "level_2":
                # GAs/MGAs/RGA also produce some
                if random.random() < 0.4:
                    pass
                else:
                    continue
            if random.random() < 0.20:
                continue  # missed day
            sets_ = random.randint(2, 10)
            sits_ = random.randint(1, max(1, min(8, sets_)))
            sales_ = random.randint(0, max(0, sits_))
            ots_sits = random.randint(0, sits_)
            ots_sales = min(sales_, random.randint(0, sales_)) if sales_ else 0
            n1 = random.randint(0, 2)
            refs = random.randint(0, sales_ * 2) if sales_ else 0
            ref_sits = random.randint(0, refs)
            ref_sales = random.randint(0, ref_sits)
            pos_sits = random.randint(0, max(0, sits_ // 2))
            pos_sales = random.randint(0, pos_sits)
            vet_sits = random.randint(0, max(0, sits_ // 3))
            vet_sales = random.randint(0, vet_sits)
            avg_alp = random.choice([800, 1100, 1300, 1600, 2200, 3000, 4500])
            gross = sales_ * avg_alp + (random.randint(-200, 500) if sales_ else 0)
            gross = max(0, gross)

            # For today, sprinkle some entries within last 60 min for the ticker
            if d_offset == 0:
                minutes_back = random.randint(0, 60 if random.random() < 0.7 else 600)
            else:
                minutes_back = random.randint(60, 60 * 24)
            submitted = now_utc() - timedelta(minutes=minutes_back)
            on_time = True if d_offset > 0 else (random.random() < 0.85)

            entries.append({
                "entry_id": f"pe_{uuid.uuid4().hex[:12]}",
                "agent_id": a["agent_id"],
                "office": a["office"],
                "sales_day": sd,
                "sets": sets_, "sits": sits_, "sales": sales_,
                "ots_sits": ots_sits, "ots_sales": ots_sales,
                "n1": n1,
                "refs_obtained": refs, "ref_sits": ref_sits, "ref_sales": ref_sales,
                "pos_sits": pos_sits, "pos_sales": pos_sales,
                "vet_sits": vet_sits, "vet_sales": vet_sales,
                "gross_alp": gross, "net_alp": gross,
                "submitted_at": submitted,
                "submitted_on_time": on_time,
            })
    if entries:
        await db.production_entries.insert_many(entries)

    # Pre-compute some shoutouts based on what we seeded
    for a in agents:
        sd_today = current_sales_day_str()
        agg = await aggregate_alp({"agent_id": a["agent_id"], "sales_day": sd_today})
        if agg["gross_alp"] >= 10000:
            await db.shoutouts.insert_one({
                "shoutout_id": f"so_{uuid.uuid4().hex[:10]}",
                "type": "players_club",
                "scope": "global",
                "agent_id": a["agent_id"],
                "agent_name": a["name"],
                "office": a["office"],
                "ga_team_id": a.get("ga_id"),
                "sales_day": sd_today,
                "amount": agg["gross_alp"],
                "ts": now_utc(),
            })

    # Seed historical vault: 8 archived weeks
    for w in range(1, 9):
        ws = (today.date() - timedelta(days=w * 7)).isoformat()
        gross = random.randint(180000, 450000)
        net = int(gross * random.uniform(0.85, 1.0))
        sales = random.randint(80, 240)
        sits = random.randint(150, 380)
        per_office = {}
        rem = gross
        for o in _SEED_OFFICES[:-1]:
            slice_ = int(rem * random.uniform(0.1, 0.35))
            per_office[o] = {"gross_alp": slice_, "net_alp": int(slice_ * 0.92), "sales": random.randint(10, 50), "sits": random.randint(20, 80)}
            rem -= slice_
        per_office[_SEED_OFFICES[-1]] = {"gross_alp": max(0, rem), "net_alp": int(max(0, rem) * 0.92), "sales": random.randint(10, 50), "sits": random.randint(20, 80)}
        await db.historical_vault.insert_one({
            "week_id": f"wk_{uuid.uuid4().hex[:8]}",
            "week_start": ws,
            "archived_at": now_utc() - timedelta(days=w * 7),
            "totals": {"gross_alp": gross, "net_alp": net, "sales": sales, "sits": sits},
            "by_office": per_office,
            "agent_count": 174,
        })

    return {"ok": True, "seeded": True, "agents": len(agents), "entries": len(entries)}


# =========================================================
#                       ADMIN PANEL
# =========================================================
# In-app replacement for the create_users.py / import_roster.py terminal
# scripts: role changes, onboarding, and permission grants behind require_admin.
# CRITICAL INVARIANT: sign-in re-derives role/agent_id from agent_profiles by
# email on every login, so every role write below updates agent_profiles (the
# source of truth) AND the users doc (so the change is visible immediately,
# without waiting for the next sign-in).

VALID_ROLES = {"level_1", "level_2", "level_3", "level_4"}


class AdminSetRoleIn(BaseModel):
    agent_id: str
    role: str  # level_1..level_4


class AdminAddPersonIn(BaseModel):
    name: str
    email: str
    phone: str = ""
    office: str = "MJ RGA"
    role: str  # level_1..level_4
    io_role: Optional[str] = None  # display title: SA, GA, MGA, RGA, Partner, ...
    upline_agent_id: Optional[str] = None
    # Tenure drives the Platinum Wall vet/rookie split and the Team "R" badge.
    # Optional in the schema ONLY so a missing value gets a clear 400 message the
    # form can surface (a bare 422 detail is a list, which the frontend api()
    # helper can't render). Tenure is never defaulted or inferred.
    is_rookie: Optional[bool] = None
    # Resident state — two-letter code (e.g. "MI"), for the WAR-sheet-parity
    # backup export's RESIDENT STATE column. Optional: not every legacy agent
    # has this recorded yet; use /admin/set-state to fill it in later.
    state: Optional[str] = None


class AdminSetTenureIn(BaseModel):
    agent_id: str
    is_rookie: bool  # True = Rookie, False = Veteran; required — always an explicit choice


class AdminSetStateIn(BaseModel):
    agent_id: str
    state: str  # two-letter resident state code, e.g. "MI"


class AdminSetFlagsIn(BaseModel):
    email: str
    is_admin: Optional[bool] = None
    can_switch_role: Optional[bool] = None


class SelfRoleIn(BaseModel):
    role: str  # level_1..level_4


@api_router.get("/admin/people")
async def admin_people(user: Dict[str, Any] = Depends(require_admin)):
    """Full roster with login-link status and permission flags, for the Admin screen."""
    agents = [a async for a in db.agent_profiles.find(
        {}, {"_id": 0, "agent_id": 1, "name": 1, "email": 1, "phone": 1,
             "office": 1, "role": 1, "io_role": 1, "upline_id": 1, "is_rookie": 1,
             "state": 1},
    ).sort("name", 1)]
    flags_by_email: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({}, {"_id": 0, "email": 1, "is_admin": 1, "can_switch_role": 1}):
        flags_by_email[str(u.get("email", "")).lower()] = u
    for a in agents:
        u = flags_by_email.get(str(a.get("email", "")).lower())
        a["has_login"] = u is not None
        a["is_admin"] = bool(u and u.get("is_admin")) or str(a.get("email", "")).lower() in ADMIN_EMAILS
        a["can_switch_role"] = bool(u and u.get("can_switch_role"))
    return {"people": agents}


@api_router.post("/admin/set-role")
async def admin_set_role(payload: AdminSetRoleIn, user: Dict[str, Any] = Depends(require_admin)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    agent = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.agent_profiles.update_one(
        {"agent_id": payload.agent_id},
        {"$set": {"role": payload.role, "updated_at": now_utc()}},
    )
    # Sync any linked login so the change takes effect without a re-login.
    email = str(agent.get("email", "")).lower()
    if email:
        await db.users.update_many({"email": email}, {"$set": {"role": payload.role, "agent_id": payload.agent_id}})
    return {"ok": True, "agent_id": payload.agent_id, "role": payload.role}


@api_router.post("/admin/add-person")
async def admin_add_person(payload: AdminAddPersonIn, user: Dict[str, Any] = Depends(require_admin)):
    """Onboard a person: creates their agent_profile keyed by email so their very
    first Google/Apple sign-in links to the right role automatically."""
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if payload.is_rookie is None:
        raise HTTPException(status_code=400, detail="Tenure is required — choose Veteran or Rookie")
    email = payload.email.lower().strip()
    name = payload.name.strip()
    if not email or "@" not in email or not name:
        raise HTTPException(status_code=400, detail="Name and a valid email are required")
    if payload.role != "level_4" and not payload.upline_agent_id:
        # Team rollups walk agent_profiles.upline_id (visible_agent_ids BFS) — an
        # agent created without an upline is invisible in every GA/MGA team view.
        raise HTTPException(status_code=400, detail="Upline is required for everyone below RGA tier")
    if payload.upline_agent_id:
        upline = await db.agent_profiles.find_one({"agent_id": payload.upline_agent_id}, {"_id": 0, "agent_id": 1})
        if not upline:
            raise HTTPException(status_code=404, detail="Upline agent not found")
    existing = await db.agent_profiles.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail=f"{existing.get('name', 'Someone')} already has this email on the roster")
    now = now_utc()
    profile = {
        "agent_id": f"agent_{uuid.uuid4().hex[:10]}",
        "name": name,
        "email": email,
        "phone": re.sub(r"\D", "", payload.phone or ""),
        "office": payload.office.strip() or "MJ RGA",
        "role": payload.role,
        "upline_id": payload.upline_agent_id,
        "is_rookie": payload.is_rookie,
        "created_at": now,
        "joined_at": now,
    }
    if payload.io_role:
        profile["io_role"] = payload.io_role.strip()
    if payload.state:
        profile["state"] = payload.state.strip().upper()
    await db.agent_profiles.insert_one(profile)
    profile.pop("_id", None)
    # If they signed in before being rostered they hold a "pending" users doc — link it now.
    await db.users.update_many({"email": email}, {"$set": {"role": payload.role, "agent_id": profile["agent_id"]}})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "add_agent",
        "agent_id": profile["agent_id"],
        "agent_name": name,
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "role": payload.role,
        "is_rookie": payload.is_rookie,
        "upline_id": payload.upline_agent_id,
    })
    return {"ok": True, "agent": profile}


@api_router.post("/admin/set-tenure")
async def admin_set_tenure(payload: AdminSetTenureIn, user: Dict[str, Any] = Depends(require_admin)):
    """Set Veteran/Rookie tenure on an existing agent. This is the resolution path
    for rostered agents whose tenure was never recorded (profiles created before
    tenure became mandatory have no is_rookie field and show as Unknown in the
    Admin screen). One agent at a time, always an explicit choice — never bulk."""
    agent = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.agent_profiles.update_one(
        {"agent_id": payload.agent_id},
        {"$set": {"is_rookie": payload.is_rookie, "updated_at": now_utc()}},
    )
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now_utc(),
        "action": "set_tenure",
        "agent_id": payload.agent_id,
        "agent_name": agent.get("name"),
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "original_value": agent.get("is_rookie"),  # None = was unknown
        "new_value": payload.is_rookie,
    })
    return {"ok": True, "agent_id": payload.agent_id, "is_rookie": payload.is_rookie}


@api_router.post("/admin/set-state")
async def admin_set_state(payload: AdminSetStateIn, user: Dict[str, Any] = Depends(require_admin)):
    """Set resident state on an existing agent. Same resolution-path shape as
    /admin/set-tenure — for legacy agents rostered before the state field
    existed, and needed for the WAR-sheet-parity backup export."""
    agent = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    state = payload.state.strip().upper()
    if len(state) != 2:
        raise HTTPException(status_code=400, detail="State must be a two-letter code, e.g. 'MI'")
    await db.agent_profiles.update_one(
        {"agent_id": payload.agent_id},
        {"$set": {"state": state, "updated_at": now_utc()}},
    )
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now_utc(),
        "action": "set_state",
        "agent_id": payload.agent_id,
        "agent_name": agent.get("name"),
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "original_value": agent.get("state"),
        "new_value": state,
    })
    return {"ok": True, "agent_id": payload.agent_id, "state": state}


@api_router.post("/admin/set-flags")
async def admin_set_flags(payload: AdminSetFlagsIn, user: Dict[str, Any] = Depends(require_admin)):
    """Grant/revoke the is_admin and can_switch_role flags on a login account."""
    email = payload.email.lower().strip()
    updates: Dict[str, Any] = {}
    if payload.is_admin is not None:
        updates["is_admin"] = payload.is_admin
    if payload.can_switch_role is not None:
        updates["can_switch_role"] = payload.can_switch_role
    if not updates:
        raise HTTPException(status_code=400, detail="No flags provided")
    result = await db.users.update_many({"email": email}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="No login found for that email — have them sign in once, then grant the flag.",
        )
    return {"ok": True, "email": email, **updates}


@api_router.post("/me/role")
async def self_set_role(payload: SelfRoleIn, user: Dict[str, Any] = Depends(require_agent)):
    """Self-service tier switcher for designated break-testers (can_switch_role flag).
    Changes the caller's OWN real account only — writes both users.role and their
    agent_profiles.role so the change survives the login re-derivation."""
    if not user.get("can_switch_role"):
        raise HTTPException(status_code=403, detail="Role switching is not enabled for this account")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    await db.agent_profiles.update_one(
        {"agent_id": user["agent_id"]},
        {"$set": {"role": payload.role, "updated_at": now_utc()}},
    )
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"role": payload.role}})
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"ok": True, "user": fresh, "role_label": LEVELS.get(payload.role, payload.role)}


# Mount router & app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    # allow_origins=["*"] combined with credentials is unreliable on the pinned
    # Starlette version (0.37.2, via fastapi==0.110.1): it only echoes back the
    # request's actual origin — required by browsers whenever credentials are
    # used — if the request already carries a Cookie header. The very first
    # cross-origin login has no cookie yet, so it fell back to the literal "*",
    # which browsers reject outright for credentialed requests.
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def on_startup():
    # Ensure indexes
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at")
    await db.users.create_index("email", unique=True)
    await db.agent_profiles.create_index("agent_id", unique=True)
    await db.agent_profiles.create_index("upline_id")
    await db.agent_profiles.create_index("office")
    await db.production_entries.create_index([("agent_id", 1), ("sales_day", 1)])
    await db.production_entries.create_index("submitted_at")
    await db.push_tokens.create_index("user_id", unique=True)
    # Idempotency guard for the escalation scheduler: a duplicate-key error on
    # this index is exactly how run_pulse_escalation_check() detects "already
    # sent this stage today" and skips re-notifying.
    await db.notification_log.create_index([("agent_id", 1), ("sales_day", 1), ("stage", 1)], unique=True)
    # Auto-seed on first run
    count = await db.agent_profiles.count_documents({})
    if count == 0:
        try:
            await _bootstrap_seed()
            logger.info("Auto-seeded mock data on first run.")
        except Exception as e:
            logger.error(f"Auto-seed failed: {e}")
    app.state.escalation_task = asyncio.create_task(_escalation_loop())


async def _escalation_loop():
    """Ticks once a minute so each of the six 30-minute stages gets caught
    inside its STAGE_FIRE_WINDOW_MINUTES window; the notification_log unique
    index (not this loop's timing) is what actually prevents double-sends."""
    while True:
        try:
            await run_pulse_escalation_check()
        except Exception as e:
            logger.error(f"Escalation check failed: {e}")
        await asyncio.sleep(60)


async def _bootstrap_seed():
    """Internal seed used at startup (no auth)."""
    # delegates to seed_data without request context; mimics empty-db path
    class _DummyReq:
        cookies = {}
        headers = {}
    await seed_data(_DummyReq(), payload=None)  # type: ignore


@app.on_event("shutdown")
async def shutdown_db_client():
    task = getattr(app.state, "escalation_task", None)
    if task:
        task.cancel()
    client.close()
