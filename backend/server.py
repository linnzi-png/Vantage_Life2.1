"""VantageLife 2.0 — FastAPI Backend
AO Premiere — Real-Time Impact Culture
"""
from fastapi import FastAPI, APIRouter, Request, HTTPException, Response, Depends, Body
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import random
import httpx
import pytz
from pathlib import Path
from pydantic import BaseModel, Field
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
OFFICES = ["MCM", "AMP", "Dearborn", "Heritage", "Siren"]
LEVELS = {
    "level_1": "Agent",
    "level_2": "GA",
    "level_3": "MGA",
    "level_4": "RGA",
}
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

# ---------------- Helpers ----------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_detroit() -> datetime:
    return datetime.now(DETROIT_TZ)


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
        return {"state": "midnight_miracle", "message": "Midnight Miracle window — entries open until 6:00 AM.", "color": "yellow"}
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
    sales_day: Optional[str] = None  # buffered flush only — YYYY-MM-DD; must be within last 7 days


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


def require_level(min_level: int):
    """min_level: 1..4 (higher = more access). level_1 has level=1, level_4 has level=4."""
    async def dep(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        lvl = int(user.get("role", "level_1").split("_")[1])
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


async def upsert_user_and_session(email: str, name: str, picture: Optional[str], session_token: str, role: str = "level_1", agent_id: Optional[str] = None) -> Dict[str, Any]:
    email = email.lower().strip()
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
        # update light fields
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"name": name, "picture": picture or user.get("picture", ""), "role": user.get("role") or role, "agent_id": user.get("agent_id") or agent_id}},
        )
        user = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})

    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(days=7),
    })
    return user


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

    # Default role: level_1 unless allowlisted
    user = await upsert_user_and_session(email=email, name=name, picture=picture, session_token=session_token, role="level_1")
    set_session_cookie(response, session_token)
    return {"user": user, "session_token": session_token}


@api_router.post("/auth/demo-login")
async def demo_login(payload: DemoLoginIn, response: Response):
    """Quick demo login that maps to one of 4 RBAC levels (no Google needed)."""
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
    return {"user": user, "agent": agent, "role_label": LEVELS.get(user.get("role", "level_1"), "Agent")}


@api_router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    tok = await get_session_token(request)
    if tok:
        await db.user_sessions.delete_one({"session_token": tok})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# =========================================================
#                  HIERARCHY & FILTERING
# =========================================================

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
    # Build downline via BFS over upline_id
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


@api_router.get("/dashboard/summary")
async def dashboard_summary(user: Dict[str, Any] = Depends(get_current_user)):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    yest = previous_sales_day_str()
    base = {"sales_day": today}
    base_y = {"sales_day": yest}
    if ids is not None:
        base["agent_id"] = {"$in": ids}
        base_y["agent_id"] = {"$in": ids}
    today_agg = await aggregate_alp(base)
    yest_agg = await aggregate_alp(base_y)
    delta_pct = 0.0
    if yest_agg["gross_alp"] > 0:
        delta_pct = ((today_agg["gross_alp"] - yest_agg["gross_alp"]) / yest_agg["gross_alp"]) * 100.0
    return {
        "sales_day": today,
        "total_alp": today_agg["gross_alp"],
        "total_net_alp": today_agg["net_alp"],
        "total_sits": today_agg["sits"],
        "total_sales": today_agg["sales"],
        "delta_pct_vs_yesterday": round(delta_pct, 1),
        "gate": gate_state(),
        "is_full_agency": ids is None,
    }


@api_router.get("/dashboard/ticker")
async def dashboard_ticker(user: Dict[str, Any] = Depends(get_current_user)):
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
            "ts": e["submitted_at"].isoformat() if isinstance(e["submitted_at"], datetime) else e["submitted_at"],
        })
    return {"items": items}


@api_router.get("/dashboard/platinum-wall")
async def dashboard_platinum_wall(user: Dict[str, Any] = Depends(get_current_user)):
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
        item = {
            "agent_id": agent["agent_id"],
            "name": agent["name"],
            "office": agent["office"],
            "gross_alp": float(r["gross_alp"]),
            "sales": int(r["sales"]),
            "is_rookie": bool(agent.get("is_rookie")),
        }
        if agent.get("is_rookie"):
            if len(rookies) < 3:
                rookies.append(item)
        else:
            if len(vets) < 3:
                vets.append(item)
        if len(vets) >= 3 and len(rookies) >= 3:
            break
    return {"vets": vets, "rookies": rookies}


@api_router.get("/dashboard/offices")
async def dashboard_offices(user: Dict[str, Any] = Depends(get_current_user)):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    out = []
    for office in OFFICES:
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
async def submit_pulse(payload: PulseIn, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("agent_id"):
        raise HTTPException(status_code=400, detail="No linked agent profile")
    agent = await db.agent_profiles.find_one({"agent_id": user["agent_id"]}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    now_local = now_detroit()
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
        if delta > 7:
            raise HTTPException(status_code=400, detail="Buffered pulse expired — sales_day is more than 7 days old")
        sd = payload.sales_day
    else:
        sd = current_sales_day_str()

    entry = {
        "entry_id": f"pe_{uuid.uuid4().hex[:12]}",
        "agent_id": user["agent_id"],
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
        "submitted_on_time": now_local.hour < 21,  # before 9 PM
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
        e["submitted_at"] = e["submitted_at"].isoformat()
    return e


@api_router.get("/pulse/me/today")
async def pulse_me_today(user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("agent_id"):
        return {"entries": [], "totals": {}, "gate": gate_state()}
    sd = current_sales_day_str()
    cur = db.production_entries.find({"agent_id": user["agent_id"], "sales_day": sd}, {"_id": 0}).sort("submitted_at", -1)
    entries = [_ser_entry(e) async for e in cur]
    agg = await aggregate_alp({"agent_id": user["agent_id"], "sales_day": sd})
    return {"entries": entries, "totals": agg, "gate": gate_state(), "sales_day": sd}


@api_router.get("/pulse/me/streak")
async def pulse_streak(user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("agent_id"):
        return {"streak": 0}
    streak = 0
    d = now_detroit()
    for i in range(0, 30):
        sd = sales_day_for(d - timedelta(days=i))
        on_time = await db.production_entries.find_one({"agent_id": user["agent_id"], "sales_day": sd, "submitted_on_time": True})
        if on_time:
            streak += 1
        else:
            break
    return {"streak": streak}


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
        close = (sales / sits * 100) if sits > 0 else 0
        avg_deal = (float(r["gross_alp"]) / sales) if sales > 0 else 0
        alerts = []
        if sits >= 3 and close < 50:
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
async def list_shoutouts(user: Dict[str, Any] = Depends(get_current_user)):
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
    for s in out:
        if isinstance(s.get("ts"), datetime):
            s["ts"] = s["ts"].isoformat()
    return {"shoutouts": out}


# =========================================================
#                  MANAGER COMMAND PANEL
# =========================================================

@api_router.post("/manager/erase")
async def manager_erase(payload: EraseIn, user: Dict[str, Any] = Depends(require_level(4))):
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
    audit["ts"] = audit["ts"].isoformat()
    return {"ok": True, "audit": audit, "delta": delta}


@api_router.get("/manager/audit")
async def manager_audit(user: Dict[str, Any] = Depends(require_level(4))):
    cur = db.audit_log.find({}, {"_id": 0}).sort("ts", -1).limit(200)
    items = []
    async for a in cur:
        if isinstance(a.get("ts"), datetime):
            a["ts"] = a["ts"].isoformat()
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
            it["archived_at"] = it["archived_at"].isoformat()
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
            w["archived_at"] = w["archived_at"].isoformat()
    return {"a": a, "b": b, "delta": delta}


@api_router.post("/admin/wednesday-reset")
async def wednesday_reset(user: Dict[str, Any] = Depends(require_level(4))):
    """Archive current week's data into historical_vault, then clear/mark active dataset."""
    today = now_detroit().date()
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

    # Per-office breakdown
    by_office = {}
    for office in OFFICES:
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
    snapshot["archived_at"] = snapshot["archived_at"].isoformat()
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
        office = ga["office"] if random.random() < 0.7 else random.choice(OFFICES)
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
        for o in OFFICES[:-1]:
            slice_ = int(rem * random.uniform(0.1, 0.35))
            per_office[o] = {"gross_alp": slice_, "net_alp": int(slice_ * 0.92), "sales": random.randint(10, 50), "sits": random.randint(20, 80)}
            rem -= slice_
        per_office[OFFICES[-1]] = {"gross_alp": max(0, rem), "net_alp": int(max(0, rem) * 0.92), "sales": random.randint(10, 50), "sits": random.randint(20, 80)}
        await db.historical_vault.insert_one({
            "week_id": f"wk_{uuid.uuid4().hex[:8]}",
            "week_start": ws,
            "archived_at": now_utc() - timedelta(days=w * 7),
            "totals": {"gross_alp": gross, "net_alp": net, "sales": sales, "sits": sits},
            "by_office": per_office,
            "agent_count": 174,
        })

    return {"ok": True, "seeded": True, "agents": len(agents), "entries": len(entries)}


# Mount router & app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
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
    # Auto-seed on first run
    count = await db.agent_profiles.count_documents({})
    if count == 0:
        try:
            await _bootstrap_seed()
            logger.info("Auto-seeded mock data on first run.")
        except Exception as e:
            logger.error(f"Auto-seed failed: {e}")


async def _bootstrap_seed():
    """Internal seed used at startup (no auth)."""
    # delegates to seed_data without request context; mimics empty-db path
    class _DummyReq:
        cookies = {}
        headers = {}
    await seed_data(_DummyReq(), payload=None)  # type: ignore


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
