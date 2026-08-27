"""VantageLife 2.0 — FastAPI Backend
AO Premier — Real-Time Impact Culture
"""
from fastapi import (
    FastAPI, APIRouter, Request, HTTPException, Response, Depends, Body,
    UploadFile, File, Form,
)
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import csv
import io
import logging
import re
import uuid
import random
import httpx
import pytz

import metrics
import war_import
import war_export
import audit_roster_emails as roster_audit
import import_roster as roster_2026_07
import import_missing_roster as roster_2026_08
import roster_hierarchy
from pathlib import Path
from pydantic import BaseModel, Field
from jose import jwt as apple_jwt
from jose.exceptions import JOSEError
from typing import List, Optional, Dict, Any, Tuple
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
# When an upline is entering on a downline agent's behalf (target_agent_id
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
# Who may pull the flat per-agent CSV. That view is a plain dump of every agent
# and their daily numbers, so the list is deliberately narrower than
# ADMIN_EMAILS. The WAR workbook is NOT gated on this — it is the report the
# office has always read, and MJ needs it (admin is enough).
EXPORT_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("EXPORT_EMAILS", "linnzi@aoluxor.com").split(",")
    if e.strip()
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

# Direct Google sign-in (replacing the Emergent auth proxy). Comma-separated
# OAuth client IDs this backend accepts as token audience — the iOS client and
# the web client. Empty (unset) means /auth/google is not yet configured and
# returns 503; the Emergent /auth/session path keeps working through the
# transition.
GOOGLE_CLIENT_IDS = {
    c.strip() for c in os.environ.get("GOOGLE_CLIENT_IDS", "").split(",") if c.strip()
}
GOOGLE_KEYS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

# Bucket for agents whose roster record has no office. They still produce, so
# dropping them makes office tiles disagree with the agency total; naming the
# bucket also makes the gap visible enough to fix in the Admin panel.
UNASSIGNED_OFFICE = "Unassigned"

# Performance-alert thresholds (owner spec). The minimums exist so a low-volume
# night cannot trip a flag — a single missed sit is not a coaching signal.
LOW_CLOSE_RATIO_PCT = 50
MIN_SITS_FOR_RATIO_ALERT = 5
LOW_AVG_DEAL_USD = 1200
MIN_SALES_FOR_DEAL_ALERT = 3

# Browser origins allowed to make credentialed calls. Both the Vercel-hosted
# deployments and the custom production domain must be listed: the frontend is
# served from www.app.aovantagelife.com in production, and an origin missing
# here fails every fetch in the browser while the API itself looks healthy.
# Subdomains are matched explicitly rather than with ".*" so an attacker-owned
# host like "evil-vercel.app" cannot satisfy the pattern.
_CORS_BASE_REGEX = (
    r"https://([a-z0-9-]+\.)*vercel\.app"
    r"|https://([a-z0-9-]+\.)*aovantagelife\.com"
    r"|http://localhost(:\d+)?"
)
_CORS_EXTRA = os.environ.get("CORS_EXTRA_ORIGIN_REGEX", "").strip()
CORS_ORIGIN_REGEX = f"{_CORS_BASE_REGEX}|{_CORS_EXTRA}" if _CORS_EXTRA else _CORS_BASE_REGEX

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


def role_level(role: Any) -> int:
    """Numeric tier for a level_N role string; anything unparseable is tier 1.
    Permission comparisons use tiers, never io_role titles — a person can hold
    MGA and RGA titles at once, and only the level_N tier is authoritative."""
    try:
        return int(str(role).split("_")[1])
    except (IndexError, ValueError):
        return 1


# Removal archives a profile instead of deleting it (sales history must keep
# aggregating into the hierarchy's records), so every *active-roster* query
# must exclude archived profiles explicitly. Entry/history aggregations and
# name/office lookup maps deliberately do NOT filter — archived agents'
# production remains attributed and renderable forever.
ACTIVE_AGENT: Dict[str, Any] = {"archived": {"$ne": True}}


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
        # Simple urgency prompt only — no buffer/time/delayed-posting wording
        # (per owner, feedback #16); entries in this window post immediately.
        return {"state": "midnight_cutoff", "message": "Submit your numbers now.", "color": "yellow"}
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


class GoogleLoginIn(BaseModel):
    id_token: str


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
    client_entry_id: Optional[str] = None  # client idempotency key — a retried submit with the same key must not double-count
    is_nif: bool = False  # "Not In Field" shortcut — an all-zero day submitted on purpose, not a missed entry


class EraseIn(BaseModel):
    agent_id: str
    sales_day: str  # YYYY-MM-DD
    new_alp: float
    reason: str


class SelfCorrectIn(BaseModel):
    """Self-correction: the agent restates their day's TRUE totals for all 14
    fields; the server computes deltas vs. what's currently summed. Unlike the
    Manager Eraser, gross_alp is corrected too and flows to the Platinum Wall
    (per owner, 2026-08-22). Reason is optional (contrast Eraser's mandatory
    10+ chars)."""
    sales_day: str  # YYYY-MM-DD — must be within MAX_SELF_BUFFER_DAYS
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
    reason: Optional[str] = None
    client_entry_id: Optional[str] = None


# ---------------- Auth ----------------

async def get_session_token(request: Request) -> Optional[str]:
    tok = request.cookies.get("session_token")
    if tok:
        return tok
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


# Sessions last 7 days, so login time alone can lag real activity by a week;
# the admin Login Scoreboard needs "still opening the app", not "still has a
# cookie". Refreshing at most every 10 minutes keeps it one write per user per
# interval instead of one per request.
LAST_SEEN_TOUCH_INTERVAL = timedelta(minutes=10)


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
    last_seen = user.get("last_seen_at")
    if isinstance(last_seen, str):
        last_seen = datetime.fromisoformat(last_seen)
    if last_seen and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if not last_seen or now_utc() - last_seen >= LAST_SEEN_TOUCH_INTERVAL:
        user["last_seen_at"] = now_utc()
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"last_seen_at": user["last_seen_at"]}})
    return user


async def require_agent(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Authenticated identity is not enough — block anyone not linked to a real
    AO Premier agent record from reaching business data, regardless of sign-in flow."""
    if not user.get("agent_id") or not str(user.get("role", "")).startswith("level_"):
        raise HTTPException(status_code=403, detail="Not yet linked to an AO Premier agent profile")
    return user


def user_is_admin(user: Dict[str, Any]) -> bool:
    return bool(user.get("is_admin")) or str(user.get("email", "")).lower() in ADMIN_EMAILS


def user_may_export(user: Dict[str, Any]) -> bool:
    """Reconciliation exports are restricted to EXPORT_EMAILS, not to admins
    generally — see the constant for why."""
    return str(user.get("email", "")).lower() in EXPORT_EMAILS


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
    # Archived (removed-from-team) profiles must not re-link: their sign-in
    # lands on the pending screen exactly like someone never rostered.
    agent = await db.agent_profiles.find_one({"email": email, **ACTIVE_AGENT}, {"_id": 0})
    role = agent["role"] if agent else "pending"
    agent_id = agent["agent_id"] if agent else None

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        now = now_utc()
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture or "",
            "role": role,
            "agent_id": agent_id,
            "created_at": now,
            "first_login_at": now,
            "last_seen_at": now,
        }
        await db.users.insert_one(user_doc)
        user_doc.pop("_id", None)
        user = user_doc
    else:
        # role/agent_id always re-synced from the agent roster, the source of truth
        updates = {
            "name": name,
            "picture": picture or user.get("picture", ""),
            "role": role,
            "agent_id": agent_id,
            "last_seen_at": now_utc(),
        }
        if not user.get("first_login_at"):
            # Accounts created before first_login_at existed: their account was
            # created by their first sign-in, so created_at is that moment.
            updates["first_login_at"] = user.get("created_at") or now_utc()
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": updates})
        user = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})

    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(days=7),
    })
    return user


_apple_jwks_cache: Dict[str, Any] = {"keys": [], "fetched_at": None, "last_attempt_at": None}
APPLE_JWKS_TTL = timedelta(hours=6)
# /auth/apple is unauthenticated, so unknown-kid forced refreshes are
# attacker-triggerable; the cooldown caps outbound traffic to Apple.
APPLE_JWKS_FORCE_COOLDOWN = timedelta(minutes=5)


async def _fetch_apple_jwks(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch Apple's JWKs, serving a cached copy so a transient Apple outage
    can't fail an otherwise-valid sign-in (App Store review runs live)."""
    fresh = (
        _apple_jwks_cache["fetched_at"] is not None
        and now_utc() - _apple_jwks_cache["fetched_at"] < APPLE_JWKS_TTL
    )
    if fresh and not force:
        return _apple_jwks_cache["keys"]
    if (
        force
        and _apple_jwks_cache["last_attempt_at"] is not None
        and now_utc() - _apple_jwks_cache["last_attempt_at"] < APPLE_JWKS_FORCE_COOLDOWN
    ):
        return _apple_jwks_cache["keys"]
    _apple_jwks_cache["last_attempt_at"] = now_utc()
    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.get(APPLE_KEYS_URL)
            if r.status_code == 200:
                # r.json() can raise on a malformed 200 body — treated like any
                # other fetch failure so the retry / cached-key fallback runs.
                keys = r.json().get("keys", [])
                if keys:
                    _apple_jwks_cache["keys"] = keys
                    _apple_jwks_cache["fetched_at"] = now_utc()
                    return keys
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            last_err = e
    if _apple_jwks_cache["keys"]:
        return _apple_jwks_cache["keys"]
    logging.error("Apple JWKS fetch failed: %s", last_err)
    raise HTTPException(status_code=503, detail="Apple sign-in is temporarily unavailable. Please try again.")


async def verify_apple_token(identity_token: str) -> Dict[str, Any]:
    """Verify a Sign in with Apple identity token against Apple's published JWKs."""
    try:
        header = apple_jwt.get_unverified_header(identity_token)
    except JOSEError:
        raise HTTPException(status_code=401, detail="Invalid Apple identity token format")

    keys = await _fetch_apple_jwks()
    matching_key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if not matching_key:
        # Apple rotates keys — the cached set may be stale for a brand-new kid.
        keys = await _fetch_apple_jwks(force=True)
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


_google_jwks_cache: Dict[str, Any] = {"keys": [], "fetched_at": None, "last_attempt_at": None}
# Same caching/cooldown story as the Apple twin above: /auth/google is
# unauthenticated, so unknown-kid forced refreshes are attacker-triggerable.
GOOGLE_JWKS_TTL = timedelta(hours=6)
GOOGLE_JWKS_FORCE_COOLDOWN = timedelta(minutes=5)


async def _fetch_google_jwks(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch Google's JWKs, serving a cached copy so a transient Google outage
    can't fail an otherwise-valid sign-in. Mirrors _fetch_apple_jwks."""
    fresh = (
        _google_jwks_cache["fetched_at"] is not None
        and now_utc() - _google_jwks_cache["fetched_at"] < GOOGLE_JWKS_TTL
    )
    if fresh and not force:
        return _google_jwks_cache["keys"]
    if (
        force
        and _google_jwks_cache["last_attempt_at"] is not None
        and now_utc() - _google_jwks_cache["last_attempt_at"] < GOOGLE_JWKS_FORCE_COOLDOWN
    ):
        return _google_jwks_cache["keys"]
    _google_jwks_cache["last_attempt_at"] = now_utc()
    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.get(GOOGLE_KEYS_URL)
            if r.status_code == 200:
                keys = r.json().get("keys", [])
                if keys:
                    _google_jwks_cache["keys"] = keys
                    _google_jwks_cache["fetched_at"] = now_utc()
                    return keys
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            last_err = e
    if _google_jwks_cache["keys"]:
        return _google_jwks_cache["keys"]
    logging.error("Google JWKS fetch failed: %s", last_err)
    raise HTTPException(status_code=503, detail="Google sign-in is temporarily unavailable. Please try again.")


async def verify_google_token(id_token: str) -> Dict[str, Any]:
    """Verify a Google ID token against Google's published JWKs.

    aud and iss are checked by hand rather than via jwt.decode kwargs: the
    token is valid for ANY of our client IDs (iOS or web) and Google issues
    under two issuer strings, and jose's decode() takes a single value for
    each. exp/signature are still enforced by decode()."""
    if not GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this server")
    try:
        header = apple_jwt.get_unverified_header(id_token)
    except JOSEError:
        raise HTTPException(status_code=401, detail="Invalid Google ID token format")

    keys = await _fetch_google_jwks()
    matching_key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if not matching_key:
        # Google rotates keys daily — the cached set may be stale for a new kid.
        keys = await _fetch_google_jwks(force=True)
        matching_key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if not matching_key:
        raise HTTPException(status_code=401, detail="No matching Google public key found")

    try:
        payload = apple_jwt.decode(
            id_token,
            matching_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JOSEError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {e}")

    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(status_code=401, detail="Invalid Google token issuer")
    aud = payload.get("aud")
    if aud not in GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")
    email = payload.get("email")
    if not email or not payload.get("email_verified"):
        # Authorization is keyed entirely by email — an unverified address
        # could impersonate a rostered agent.
        raise HTTPException(status_code=401, detail="Google account email is not verified")
    return {
        "sub": payload["sub"],
        "email": email,
        "name": payload.get("name"),
        "picture": payload.get("picture"),
    }


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
    # Separate from is_admin on purpose: the reconciliation exports are a
    # narrower grant than the admin panel, so the UI must not infer one from
    # the other and offer a button the server will refuse.
    user["can_export"] = user_may_export(user)
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


@api_router.post("/auth/google")
async def auth_google(payload: GoogleLoginIn, response: Response):
    """Direct Google sign-in: the app obtains an ID token from Google itself
    and we verify it here — no Emergent proxy in the path. Same two-step
    authentication/authorization contract as Apple: any verified Google
    identity signs in successfully; roster matching happens separately in
    upsert_user_and_session."""
    claims = await verify_google_token(payload.id_token)
    name = claims.get("name") or claims["email"]
    session_token = f"st_{uuid.uuid4().hex}"
    user = await upsert_user_and_session(
        email=claims["email"], name=name, picture=claims.get("picture"), session_token=session_token)
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
    level_2+) and can_enter_for (write access, level_2+) so both walk the exact
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
    Any upline (level_2+ — SA/GA, MGA, RGA) may submit on someone else's
    behalf, and only for their own downline — never for a sibling branch or
    a peer at the same level. Everyone may always enter for themselves.
    (Per owner 2026-07-28: entry starts at level_2, same tier as viewing.)"""
    own_agent_id = user.get("agent_id")
    if target_agent_id == own_agent_id:
        return True
    role = user.get("role", "level_1")
    if role not in ("level_2", "level_3", "level_4"):
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


# The 13 integer metric fields (everything in PulseIn except gross_alp).
# Order matches the canonical 14-metric order; gross_alp is handled as a float
# alongside net_alp wherever this list is used.
PULSE_INT_FIELDS = [
    "sets", "sits", "sales", "ots_sits", "ots_sales", "n1",
    "refs_obtained", "ref_sits", "ref_sales", "pos_sits", "pos_sales",
    "vet_sits", "vet_sales",
]


async def aggregate_full_pulse(filter_q: Dict[str, Any]) -> Dict[str, float]:
    """Same shape of job as aggregate_alp, but sums ALL 14 raw fields (plus
    net_alp) — needed to show current totals before a self-correction and to
    compute per-field deltas."""
    group: Dict[str, Any] = {"_id": None}
    for f in PULSE_INT_FIELDS:
        group[f] = {"$sum": f"${f}"}
    group["gross_alp"] = {"$sum": "$gross_alp"}
    group["net_alp"] = {"$sum": "$net_alp"}
    pipeline = [{"$match": filter_q}, {"$group": group}]
    cur = db.production_entries.aggregate(pipeline)
    docs = [d async for d in cur]
    out: Dict[str, float] = {f: 0 for f in PULSE_INT_FIELDS}
    out["gross_alp"] = 0.0
    out["net_alp"] = 0.0
    if not docs:
        return out
    d = docs[0]
    for f in PULSE_INT_FIELDS:
        out[f] = int(d.get(f, 0) or 0)
    out["gross_alp"] = float(d.get("gross_alp", 0) or 0)
    out["net_alp"] = float(d.get("net_alp", 0) or 0)
    return out


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


def scoreboard_prev_window(period: str) -> Dict[str, Any]:
    """sales_day match for the window immediately before the current one, so
    weekly/monthly views can show a period-over-period delta. Not for 'daily'.

    Matches sales_day for the same reason scoreboard_window does — the previous
    period has to mean the days production belongs to, or the delta compares
    against whatever happened to be submitted then."""
    now = now_detroit()
    if period == "weekly":
        cur = most_recent_wed_2pm(now)
        prev = cur - timedelta(days=7)
    else:  # monthly — first day of the previous calendar month
        cur = month_start_detroit(now)
        prev = month_start_detroit(cur - timedelta(days=1))
    # Inclusive start, exclusive end — the day the current window opens belongs
    # to the current window, not the previous one.
    return {"sales_day": {"$gte": prev.date().isoformat(), "$lt": cur.date().isoformat()}}


@api_router.get("/dashboard/summary")
async def dashboard_summary(
    sales_day: Optional[str] = None,
    period: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_agent),
):
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()

    # Weekly/monthly: a rolling window (delta vs the previous window). Daily and
    # the no-period default keep the exact single-day + vs-yesterday behavior.
    if period and period != "daily":
        base, _ = scoreboard_window(period)  # validates; raises 400 on unknown
        base_prev = scoreboard_prev_window(period)
        if ids is not None:
            base["agent_id"] = {"$in": ids}
            base_prev["agent_id"] = {"$in": ids}
        cur_agg = await aggregate_alp(base)
        prev_agg = await aggregate_alp(base_prev)
        delta_pct = ((cur_agg["gross_alp"] - prev_agg["gross_alp"]) / prev_agg["gross_alp"] * 100.0) if prev_agg["gross_alp"] > 0 else 0.0
        return {
            "sales_day": today,
            "period": period,
            "total_alp": cur_agg["gross_alp"],
            "total_net_alp": cur_agg["net_alp"],
            "total_sits": cur_agg["sits"],
            "total_sales": cur_agg["sales"],
            "delta_pct_vs_yesterday": round(delta_pct, 1),  # vs previous window
            "gate": None,
            "is_full_agency": ids is None,
            "is_history": False,
        }

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
        "period": "daily",
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
async def dashboard_platinum_wall(
    sales_day: Optional[str] = None,
    period: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_agent),
):
    """Top 3 producers by tenure for the selected window.

    Takes the same sales_day/period params as /dashboard/summary. It used to be
    pinned to the current sales day with no way to ask for anything else, so
    every historical day and every rolling window came back empty — the wall was
    the one dashboard section the period selector could not reach.
    """
    ids = await visible_agent_ids(user)
    # scoreboard_window resolves daily (optionally historical) and the rolling
    # weekly/monthly ranges identically to the summary above it.
    q, _ = scoreboard_window(period or "daily", sales_day)
    if ids is not None:
        q["agent_id"] = {"$in": ids}
    pipeline = [
        {"$match": q},
        {"$group": {"_id": "$agent_id", "gross_alp": {"$sum": "$gross_alp"}, "sales": {"$sum": "$sales"}}},
        {"$sort": {"gross_alp": -1}},
    ]
    cur = db.production_entries.aggregate(pipeline)
    rows = [d async for d in cur]
    vets, rookies, unranked = [], [], []
    for r in rows:
        agent = await db.agent_profiles.find_one({"agent_id": r["_id"]}, {"_id": 0})
        if not agent:
            continue
        # Tenure must be explicitly recorded to rank as a vet or a rookie: a
        # missing is_rookie means UNKNOWN, not veteran. Those agents used to be
        # dropped entirely, which hid top producers — most of the roster has no
        # tenure set, so the wall looked broken. They now surface in their own
        # bucket instead, which also makes the gap visible enough to fix.
        tenure = agent.get("is_rookie")
        item = {
            "agent_id": agent["agent_id"],
            "name": agent["name"],
            "office": agent.get("office", ""),
            "gross_alp": float(r["gross_alp"]),
            "sales": int(r["sales"]),
            "is_rookie": bool(tenure) if tenure is not None else None,
            "role": agent.get("role", ""),
            "io_role": agent.get("io_role", ""),
            "phone": agent.get("phone", ""),
            "email": agent.get("email", ""),
        }
        if tenure is None:
            bucket = unranked
        elif tenure:
            bucket = rookies
        else:
            bucket = vets
        if len(bucket) < 3:
            bucket.append(item)
        if len(vets) >= 3 and len(rookies) >= 3 and len(unranked) >= 3:
            break
    # Recent Platinum Rule recognition posts (global scope, newest first)
    platinum = [s async for s in db.shoutouts.find(
        {"type": "platinum_rule"}, {"_id": 0}).sort("ts", -1).limit(5)]
    for s in platinum:
        if isinstance(s.get("ts"), datetime):
            s["ts"] = iso_utc(s["ts"])
    return {"vets": vets, "rookies": rookies, "unranked": unranked,
            "platinum_rule": platinum, "period": period or "daily"}


@api_router.get("/dashboard/offices")
async def dashboard_offices(
    sales_day: Optional[str] = None,
    period: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_agent),
):
    ids = await visible_agent_ids(user)
    # Weekly/monthly use a rolling window; daily/default keeps the single-day
    # (optionally historical) behavior.
    window, _ = scoreboard_window(period or "daily", sales_day)
    # Discover offices from agent_profiles so new RGAs appear automatically.
    # An agent with a blank office is bucketed under UNASSIGNED_OFFICE rather
    # than dropped: their production still counts toward the summary above, so
    # discarding them here made the office tiles silently under-sum the headline.
    profile_q: Dict[str, Any] = {}
    if ids is not None:
        profile_q["agent_id"] = {"$in": ids}
    ids_by_office: Dict[str, List[str]] = {}
    async for a in db.agent_profiles.find(profile_q, {"_id": 0, "agent_id": 1, "office": 1}):
        ids_by_office.setdefault(a.get("office") or UNASSIGNED_OFFICE, []).append(a["agent_id"])

    out = []
    for office in sorted(ids_by_office):
        office_agent_ids = ids_by_office[office]
        if not office_agent_ids:
            out.append({"office": office, "alp": 0, "sales": 0, "avg_deal": 0})
            continue
        agg = await aggregate_alp({**window, "agent_id": {"$in": office_agent_ids}})
        avg = (agg["gross_alp"] / agg["sales"]) if agg["sales"] > 0 else 0
        out.append({
            "office": office,
            "alp": round(agg["gross_alp"], 2),
            "sales": agg["sales"],
            "avg_deal": round(avg, 2),
        })
    return {"offices": out, "period": period or "daily"}


# =========================================================
#                          PULSE
# =========================================================

def validate_buffered_sales_day(sales_day: Optional[str], is_proxy_entry: bool, now_local: datetime) -> str:
    """Shared bounds check for any client-supplied sales_day on a write
    (buffered flush, backfill, self-correction). Same window and exact error
    messages as the original inline /api/pulse check — single source of truth,
    per the 'reuse, don't duplicate' rule."""
    if not sales_day:
        return current_sales_day_str()
    max_buffer_days = MAX_UPLINE_BUFFER_DAYS if is_proxy_entry else MAX_SELF_BUFFER_DAYS
    try:
        requested = datetime.strptime(sales_day, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid sales_day format — use YYYY-MM-DD")
    delta = (now_local.date() - requested).days
    if delta < 0:
        raise HTTPException(status_code=400, detail="sales_day cannot be in the future")
    if delta > max_buffer_days:
        if is_proxy_entry:
            raise HTTPException(status_code=400, detail=f"Buffered pulse expired — sales_day is more than {max_buffer_days} days old")
        raise HTTPException(status_code=400, detail=f"That day is outside your {max_buffer_days}-day self-edit window — ask your upline to enter this correction")
    return sales_day


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
    if agent.get("archived"):
        raise HTTPException(status_code=400, detail="This agent was removed from the team — numbers can't be entered for them")

    if payload.client_entry_id:
        # A timed-out or retried submit whose insert already committed must
        # not double-count sales/ALP — return the original entry instead.
        existing = await db.production_entries.find_one(
            {"agent_id": target_agent_id, "client_entry_id": payload.client_entry_id}, {"_id": 0}
        )
        if existing:
            return {"ok": True, "entry": _ser_entry(existing), "duplicate": True}

    now_local = now_detroit()
    sd = validate_buffered_sales_day(payload.sales_day, is_proxy_entry, now_local)

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
        # Self entries: on time only when logged before 9 PM for the currently
        # open sales day. A backfill of a PAST day is never on time — per owner
        # (2026-08-22), a first-time entry for a missed day does not repair the
        # streak (only a self-correction of an existing day does).
        "submitted_on_time": True if is_proxy_entry else (sd == current_sales_day_str() and now_local.hour < 21),
        # entered_by is always derived from the authenticated session — never a
        # manual form field the submitter fills in themselves.
        "entered_by": user["user_id"],
        "entered_by_name": user.get("name"),
        "entered_by_role": user.get("role"),
        "is_proxy_entry": is_proxy_entry,
        "client_entry_id": payload.client_entry_id,
        # True only when submitted via the "NIF" (Not In Field) shortcut — an
        # intentional all-zero day, distinct from an agent who worked and simply
        # produced nothing. Metrics/aggregates treat it like any other zero-value
        # entry; this flag exists purely so the UI can label it correctly.
        "is_nif": payload.is_nif,
        # Row-origin tag (go-live source-tagging convention, issue #12): every
        # row the app writes going forward is tagged "app" at write-time, so
        # reconcile/audits can tell app rows from WAR imports without heuristics.
        "source": "app",
    }
    await db.production_entries.insert_one(entry)
    entry.pop("_id", None)

    # Trigger shoutouts
    await maybe_trigger_shoutouts(agent, entry)

    # Confirmation check-in to the direct upline -- self entries only. Proxy
    # entries skip it (the upline typed the numbers themselves).
    if not is_proxy_entry:
        await notify_upline_of_submission(agent, sd)

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


@api_router.get("/pulse/me/day")
async def pulse_me_day(sales_day: Optional[str] = None, user: Dict[str, Any] = Depends(require_agent)):
    """Mirrors /pulse/me/today but parameterized by sales_day — feeds the
    self-correction screen with current summed totals for all 14 fields.
    Self only: corrections have no proxy path (uplines have their own)."""
    if not user.get("agent_id"):
        return {"entries": [], "totals": {}, "sales_day": None}
    sd = resolve_history_day(sales_day)
    q = {"agent_id": user["agent_id"], "sales_day": sd}
    cur = db.production_entries.find(q, {"_id": 0}).sort("submitted_at", -1)
    entries = [_ser_entry(e) async for e in cur]
    totals = await aggregate_full_pulse(q)
    return {"entries": entries, "totals": totals, "sales_day": sd}


@api_router.post("/pulse/correct")
async def pulse_correct(payload: SelfCorrectIn, user: Dict[str, Any] = Depends(require_agent)):
    """Self-correction (owner decisions, 2026-08-22): the agent restates the
    TRUE totals for a day within MAX_SELF_BUFFER_DAYS; one is_adjustment /
    is_self_correction row carries the per-field deltas.

    Diverges from the Manager Eraser deliberately:
    - gross_alp is corrected too — flows to the Platinum Wall via the existing
      live aggregation (net_alp moves by the SAME delta, preserving any prior
      manager-adjustment offset).
    - reason is optional.
    - submitted_on_time: True — per owner, correcting an existing day repairs
      the streak. A day with NO entries cannot be corrected (400) — first-time
      backfill goes through /api/pulse and does NOT repair the streak.
    - Only the Player's Club check re-runs afterwards (idempotent); Streak and
      First Deal shoutouts never fire off a correction.
    """
    if not user.get("agent_id"):
        raise HTTPException(status_code=400, detail="No linked agent profile")
    agent_id = user["agent_id"]  # self only — no target_agent_id accepted
    agent = await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if payload.client_entry_id:
        existing = await db.production_entries.find_one(
            {"agent_id": agent_id, "client_entry_id": payload.client_entry_id}, {"_id": 0}
        )
        if existing:
            return {"ok": True, "entry": _ser_entry(existing), "duplicate": True}

    sd = validate_buffered_sales_day(payload.sales_day, False, now_detroit())

    q = {"agent_id": agent_id, "sales_day": sd}
    existing_count = await db.production_entries.count_documents(q)
    if existing_count == 0:
        # Owner rule (§3b): a correction only ever adjusts an existing day. A
        # missed day is a fresh backfill through /api/pulse, which keeps its
        # normal on-time semantics and does not repair the streak.
        raise HTTPException(status_code=400, detail="No entries exist for that day — log a regular pulse instead of a correction")

    totals = await aggregate_full_pulse(q)
    deltas: Dict[str, float] = {}
    for f in PULSE_INT_FIELDS:
        deltas[f] = int(getattr(payload, f)) - int(totals[f])
    gross_delta = float(payload.gross_alp) - float(totals["gross_alp"])
    if all(v == 0 for v in deltas.values()) and gross_delta == 0:
        return {"ok": True, "no_change": True}

    adj = {
        "entry_id": f"adj_{uuid.uuid4().hex[:10]}",
        "agent_id": agent_id,
        "office": agent["office"],
        "sales_day": sd,
        **deltas,                    # each field is a DELTA vs. current total
        "gross_alp": gross_delta,    # real delta — NOT zeroed like the Eraser
        "net_alp": gross_delta,      # same delta: preserves any manager offset
        "submitted_at": now_utc(),
        "submitted_on_time": True,   # per owner: a correction repairs the streak
        "is_adjustment": True,
        "is_self_correction": True,
        "entered_by": user["user_id"],
        "entered_by_name": user.get("name"),
        "entered_by_role": user.get("role"),
        "reason": payload.reason,
        "client_entry_id": payload.client_entry_id,
        "source": "app",             # issue #12 row-origin tag, same as /api/pulse
    }
    await db.production_entries.insert_one(adj)
    adj.pop("_id", None)

    audit = {
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now_utc(),
        "action": "self_correct_pulse",
        "agent_id": agent_id,
        "agent_name": agent["name"],
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "sales_day": sd,
        "changes": {
            **{f: {"from": int(totals[f]), "to": int(getattr(payload, f)), "delta": deltas[f]}
               for f in PULSE_INT_FIELDS if deltas[f] != 0},
            **({"gross_alp": {"from": totals["gross_alp"], "to": float(payload.gross_alp), "delta": gross_delta}}
               if gross_delta != 0 else {}),
        },
        # Optional here (unlike the Eraser) — but the log line should still
        # read consistently, so absence is spelled out rather than blank.
        "reason": (payload.reason or "").strip() or "(no reason given)",
    }
    await db.audit_log.insert_one(audit)
    audit.pop("_id", None)

    # Only the Player's Club check re-runs — it's idempotent (no-ops if the
    # shoutout already exists) and never retracts one if the corrected total
    # drops back under $10k. Streak / First Deal are never correction-triggered.
    await maybe_trigger_players_club(agent, sd)

    audit["ts"] = iso_utc(audit["ts"])
    return {"ok": True, "entry": _ser_entry(adj), "audit": audit}


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


async def notify_upline_of_submission(agent, sales_day: str) -> None:
    """Confirmation check-in (owner, 2026-08-27): the agent's DIRECT upline gets
    one push the first time the agent submits their own numbers for a sales day.
    Proxy entries and self-corrections never fire this; resubmits for the same
    sales day are deduped through notification_log (stage 'submitted_upline').
    Best-effort -- a failure here must never fail the submission itself."""
    try:
        upline_id = agent.get("upline_id")
        if not upline_id:
            return
        if not await _log_and_check(agent["agent_id"], sales_day, "submitted_upline"):
            return
        tokens = [t["push_token"] async for t in db.push_tokens.find({"agent_id": upline_id}, {"_id": 0, "push_token": 1})]
        await send_expo_push(tokens, "VantageLife", f"{agent.get('name', 'An agent')} entered their daily numbers.")
    except Exception as e:
        logger.warning(f"Upline submission push failed: {e}")


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
        a async for a in db.agent_profiles.find(
            {"role": {"$in": ["level_1", "level_2"]}, **ACTIVE_AGENT}, {"_id": 0, "agent_id": 1, "name": 1})
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

# ---- Scoreboard period windows -------------------------------------------
# The Team Production scoreboard can be viewed over three windows. "daily"
# keeps the existing 6 AM Detroit sales-day boundary. "weekly" and "monthly"
# are anchored to the Wednesday 2:00 PM America/Detroit cutoff and filter on
# submitted_at, so totals fall back to $0 the instant the cutoff passes with
# no data deletion required. Entries are retained (see wednesday_reset), so a
# window that spans prior weeks (monthly) still has its data.
SCOREBOARD_PERIODS = ("daily", "weekly", "monthly")
DEFAULT_SCOREBOARD_PERIOD = "weekly"


def most_recent_wed_2pm(dt_local: datetime) -> datetime:
    """Most recent Wednesday 2:00 PM America/Detroit at or before dt_local.

    dt_local must be Detroit-tz-aware (e.g. now_detroit()). Built via
    DETROIT_TZ.localize so the boundary shifts correctly across DST."""
    days_since_wed = (dt_local.weekday() - 2) % 7  # Mon=0..Wed=2
    wed = (dt_local - timedelta(days=days_since_wed)).date()
    cutoff = DETROIT_TZ.localize(datetime(wed.year, wed.month, wed.day, 14, 0))
    if cutoff > dt_local:
        # It is Wednesday before 2:00 PM — the active week began the prior Wed.
        wed = wed - timedelta(days=7)
        cutoff = DETROIT_TZ.localize(datetime(wed.year, wed.month, wed.day, 14, 0))
    return cutoff


def month_start_detroit(dt_local: datetime) -> datetime:
    """Midnight on the 1st of dt_local's calendar month, America/Detroit."""
    return DETROIT_TZ.localize(datetime(dt_local.year, dt_local.month, 1, 0, 0))


def scoreboard_window(period: str, sales_day: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[datetime]]:
    """Return (Mongo match fragment, window start in UTC) for a period.

    Every period matches on sales_day — the day production belongs to — never on
    submitted_at. Keying the rolling windows off submission time meant a deal
    sold Tuesday but entered Wednesday morning landed in the wrong week, and it
    made backfilled history invisible: imported entries carry submitted_at of
    their historical date, so anything older than the current window vanished
    from Weekly/Monthly while Daily showed it fine.

    The Wednesday 2 PM cutoff still decides WHICH week is current
    (most_recent_wed_2pm) — only the field being matched has changed. Daily
    honours an optional historical sales_day.

    Raises 400 on an unknown period.
    """
    if period not in SCOREBOARD_PERIODS:
        raise HTTPException(status_code=400, detail="period must be daily, weekly, or monthly")
    if period == "daily":
        return {"sales_day": resolve_history_day(sales_day)}, None

    now = now_detroit()
    start_local = most_recent_wed_2pm(now) if period == "weekly" else month_start_detroit(now)
    # The window runs from its start day through the current sales day. ISO date
    # strings compare lexicographically, so a plain string range is correct.
    day_from = start_local.date().isoformat()
    day_to = current_sales_day_str()
    return ({"sales_day": {"$gte": day_from, "$lte": day_to}},
            start_local.astimezone(timezone.utc))


@api_router.get("/team")
async def team_view(
    period: str = DEFAULT_SCOREBOARD_PERIOD,
    week_start: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_level(2)),
):
    """Team rollup. `week_start` (a Wednesday) pulls up a specific past week
    instead of a rolling window.

    A historical week matches on sales_day rather than submitted_at: the rolling
    windows key off submission time, which is right for "since the last reset",
    but a past week must be defined by the days the production belongs to —
    otherwise a backfilled entry, stamped when it was imported rather than when
    it was sold, would land in the wrong week.
    """
    ids = await visible_agent_ids(user)
    today = current_sales_day_str()
    if week_start:
        day_from, day_to = week_day_range(week_start)
        q: Dict[str, Any] = {"sales_day": {"$gte": day_from, "$lte": day_to}}
        window_start = None
    else:
        q, window_start = scoreboard_window(period)
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
    # Manager-visible "notifications off" flag (owner, 2026-08-27): a team
    # member with no registered push token can't get the 9 PM escalation or
    # upline confirmation pushes at all. Surfaced the same way as any other
    # alerts chip -- it's a signal for the manager to follow up, never an
    # in-app block on the agent's own access.
    reachable_ids = {
        t["agent_id"] async for t in db.push_tokens.find(
            {"agent_id": {"$in": list(agents.keys())}}, {"_id": 0, "agent_id": 1}
        )
    }
    out = []
    for r in rows:
        a = agents.get(r["_id"])
        if not a:
            continue
        sales = int(r["sales"])
        sits = int(r["sits"])
        # Close Rate = Sales / Sits. N1 (medically unqualified) is already
        # excluded from Sits at entry, so it is not subtracted again here.
        close = metrics.close_rate(sales, sits)
        avg_deal = (float(r["gross_alp"]) / sales) if sales > 0 else 0
        # Thresholds per the owner's spec: close ratio under 50% needs at least
        # 5 sits, average deal under $1,200 needs at least 3 sales. The minimums
        # keep a new agent's first night from tripping a flag.
        alerts = []
        if sits >= MIN_SITS_FOR_RATIO_ALERT and close < LOW_CLOSE_RATIO_PCT:
            alerts.append("low_close_ratio")
        if sales >= MIN_SALES_FOR_DEAL_ALERT and avg_deal < LOW_AVG_DEAL_USD:
            alerts.append("low_avg_deal")
        if not a.get("archived") and a["agent_id"] not in reachable_ids:
            alerts.append("notifications_off")
        out.append({
            "agent_id": a["agent_id"],
            "name": a["name"],
            "office": a["office"],
            "role": a["role"],
            "io_role": a.get("io_role") or "",
            "phone": a.get("phone") or "",
            "email": a.get("email") or "",
            "is_rookie": a.get("is_rookie", False),
            "upline_id": a.get("upline_id"),
            # A removed member's already-logged production stays on the board
            # for its window ("history is history") — flagged so the UI can
            # badge the row and withhold team actions.
            "archived": bool(a.get("archived")),
            "gross_alp": float(r["gross_alp"]),
            "net_alp": float(r["net_alp"]),
            "sits": sits,
            "sales": sales,
            "close_ratio": round(close, 1),
            "avg_deal": round(avg_deal, 2),
            "alerts": alerts,
        })
    # Add agents with no entries — removed members don't linger as no-pulse rows
    listed = {x["agent_id"] for x in out}
    for aid, a in agents.items():
        if aid not in listed and not a.get("archived"):
            no_entry_alerts = ["no_pulse"]
            if aid not in reachable_ids:
                no_entry_alerts.append("notifications_off")
            out.append({
                "agent_id": aid, "name": a["name"], "office": a["office"], "role": a["role"],
                "io_role": a.get("io_role") or "", "phone": a.get("phone") or "", "email": a.get("email") or "",
                "is_rookie": a.get("is_rookie", False), "upline_id": a.get("upline_id"), "archived": False,
                "gross_alp": 0, "net_alp": 0, "sits": 0, "sales": 0,
                "close_ratio": 0, "avg_deal": 0, "alerts": no_entry_alerts,
            })
    return {
        "team": out,
        "sales_day": today,
        "period": None if week_start else period,
        "week_start": week_start,
        "window_start": iso_utc(window_start) if window_start else None,
    }


@api_router.get("/team/weeks")
async def team_weeks(user: Dict[str, Any] = Depends(require_level(2))):
    """Reporting weeks that have production for the caller's visible team —
    the options for the Team screen's week picker."""
    ids = await visible_agent_ids(user)
    q: Dict[str, Any] = {} if ids is None else {"agent_id": {"$in": ids}}
    days = await db.production_entries.distinct("sales_day", q)
    weeks = set()
    for d in days:
        try:
            weeks.add(week_start_for_day(d))
        except (ValueError, TypeError):
            continue
    return {"weeks": sorted(weeks, reverse=True)}


# =========================================================
#                       SHOUTOUTS
# =========================================================

async def maybe_trigger_players_club(agent: Dict[str, Any], sd: str):
    """Player's Club: $10k+ Gross ALP in a sales day. Idempotent — no-ops if
    the shoutout for this agent+day already exists, and never retracts one.
    Split out of maybe_trigger_shoutouts so a self-correction can re-run just
    this check (the only shoutout type corrections may trigger)."""
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


async def maybe_trigger_shoutouts(agent: Dict[str, Any], entry: Dict[str, Any]):
    sd = entry["sales_day"]
    await maybe_trigger_players_club(agent, sd)
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
        dict(ACTIVE_AGENT), {"_id": 0, "agent_id": 1, "name": 1, "office": 1}).sort("name", 1)]
    return {"agents": out}


class NominationIn(BaseModel):
    nominee_agent_id: str
    reason: str = Field(min_length=10, max_length=500)


async def _nomination_visible_to(user: Dict[str, Any], nomination: Dict[str, Any]) -> bool:
    ids = await visible_agent_ids(user)
    return ids is None or nomination["nominee_agent_id"] in ids


@api_router.post("/nominations")
async def create_nomination(payload: NominationIn, user: Dict[str, Any] = Depends(require_agent)):
    nominee = await db.agent_profiles.find_one(
        {"agent_id": payload.nominee_agent_id, **ACTIVE_AGENT}, {"_id": 0})
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


def week_start_for_day(day_str: str) -> str:
    """Wednesday on-or-before a sales_day — the reporting week it belongs to."""
    d = date.fromisoformat(day_str)
    return (d - timedelta(days=(d.weekday() - 2) % 7)).isoformat()


# Metrics rolled up per week. gross/net ALP are dollars; the rest are counts.
_TREND_SUMS = [
    "sets", "sits", "sales", "ots_sits", "ots_sales", "n1", "refs_obtained",
    "ref_sits", "ref_sales", "pos_sits", "pos_sales", "vet_sits", "vet_sales",
    "gross_alp", "net_alp",
]


def week_day_range(week_start: str) -> Tuple[str, str]:
    """Inclusive sales_day bounds for a Wed-to-Tue reporting week."""
    ws = date.fromisoformat(week_start)
    if ws.weekday() != 2:
        raise HTTPException(
            status_code=400,
            detail=f"week_start must be a Wednesday; {week_start} is a {ws.strftime('%A')}.",
        )
    return week_start, (ws + timedelta(days=6)).isoformat()


async def agent_office_map() -> Dict[str, str]:
    """agent_id -> the office on their roster record.

    agent_profiles is the source of truth for which office someone belongs to.
    production_entries.office carries whatever the source system called it, and
    that drifts: a WAR spreadsheet header reads "Mohamed Aljahmi RGA" where the
    roster reads "MJ RGA", which splits one office into two in any grouping
    keyed off the entry. /dashboard/offices and the Wednesday reset already
    resolve offices through agent_profiles; this keeps trends consistent.
    """
    return {
        a["agent_id"]: (a.get("office") or UNASSIGNED_OFFICE)
        async for a in db.agent_profiles.find({}, {"_id": 0, "agent_id": 1, "office": 1})
    }


async def weekly_series(
    match: Dict[str, Any],
    office_of: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], set]:
    """Roll production_entries matching `match` into per-week totals.

    Shared by the office trends and the per-agent history so both apply the
    same Wed-to-Tue bucketing and the same N1-excluded Close Rate. Returns
    (series oldest-first, set of roster offices represented).
    """
    if office_of is None:
        office_of = await agent_office_map()

    pipeline: List[Dict[str, Any]] = []
    if match:
        pipeline.append({"$match": match})
    # Group by day only: office attribution comes from the roster map below, and
    # a per-agent group key would explode into (agents x days) buckets.
    pipeline.append({
        "$group": {
            "_id": "$sales_day",
            **{m: {"$sum": f"${m}"} for m in _TREND_SUMS},
            "agent_ids": {"$addToSet": "$agent_id"},
        }
    })

    by_week: Dict[str, Dict[str, Any]] = {}
    offices: set = set()
    async for row in db.production_entries.aggregate(pipeline):
        day = row["_id"]
        if not day:
            continue
        try:
            ws = week_start_for_day(day)
        except (ValueError, TypeError):
            continue  # malformed sales_day — skip rather than poison the series
        w = by_week.setdefault(ws, {m: 0.0 for m in _TREND_SUMS})
        w.setdefault("agents", set())
        w.setdefault("offices", set())
        for m in _TREND_SUMS:
            w[m] += float(row.get(m) or 0)
        for a in row.get("agent_ids", []):
            if not a:
                continue
            w["agents"].add(a)
            off = office_of.get(a)
            if off:
                w["offices"].add(off)
                offices.add(off)

    series = []
    for ws in sorted(by_week):
        w = by_week[ws]
        sales = int(w["sales"])
        sits = int(w["sits"])
        sets_ = int(w["sets"])
        series.append({
            "week_start": ws,
            **{m: (round(w[m], 2) if m.endswith("alp") else int(w[m])) for m in _TREND_SUMS},
            # Close Rate via metrics.py, never inline. N1 is already excluded
            # from Sits at entry, so it is not subtracted again.
            "close_rate": round(metrics.close_rate(sales, sits), 1),
            "show_rate": round((sits / sets_ * 100) if sets_ > 0 else 0.0, 1),
            "alp_per_sale": round(w["gross_alp"] / sales, 2) if sales else 0.0,
            "agent_count": len(w["agents"]),
            "office_count": len(w["offices"]),
        })
    return series, offices


@api_router.get("/agents/{agent_id}/history")
async def agent_history(
    agent_id: str,
    weeks: Optional[int] = None,
    user: Dict[str, Any] = Depends(require_agent),
):
    """Weekly production history for one agent.

    Authorization mirrors every other business route: an agent may read their
    own history, and an upline may read anyone in their downline — resolved by
    visible_agent_ids(), never by tier label. RGAs get ids=None (full agency).
    """
    ids = await visible_agent_ids(user)
    if ids is not None and agent_id not in ids and agent_id != user.get("agent_id"):
        raise HTTPException(status_code=403, detail="Not in your team")

    profile = await db.agent_profiles.find_one(
        {"agent_id": agent_id},
        {"_id": 0, "agent_id": 1, "name": 1, "office": 1, "role": 1, "io_role": 1},
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")

    series, _ = await weekly_series({"agent_id": agent_id})
    if weeks and weeks > 0:
        series = series[-weeks:]
    return {"agent": profile, "series": series}


@api_router.get("/vault/trends")
async def vault_trends(
    office: Optional[str] = None,
    weeks: Optional[int] = None,
    user: Dict[str, Any] = Depends(require_level(4)),
):
    """Week-over-week production series for the health dashboard.

    Reads production_entries rather than historical_vault on purpose: vault
    snapshots store only gross/net ALP, sits and sales, so Close Rate could not
    honour the N1 exclusion from them. Entries carry all 14 nightly metrics, and
    they are retained after the Wednesday reset (flagged `archived`), so the
    series covers every week that has data — not just the last 8 snapshots.

    `office` filters to one office; omitted returns every office combined.
    Offices resolve through agent_profiles, not through the office stamped on
    each entry — a WAR sheet header reads "Mohamed Aljahmi RGA" where the roster
    reads "MJ RGA", and grouping by the entry would show one office as two.
    """
    office_of = await agent_office_map()
    match: Dict[str, Any] = {}
    if office:
        member_ids = [aid for aid, off in office_of.items() if off == office]
        # An office with no roster members matches nothing — an empty $in, not
        # an absent filter, or it would silently return the whole agency.
        match["agent_id"] = {"$in": member_ids}

    series, _ = await weekly_series(match, office_of)

    if weeks and weeks > 0:
        series = series[-weeks:]

    return {
        "series": series,
        "offices": sorted({o for o in office_of.values() if o}),
        "office": office,
    }


@api_router.get("/vault/offices")
async def vault_offices(user: Dict[str, Any] = Depends(require_level(4))):
    """Offices for the dashboard tabs, from agent_profiles — the source of
    truth — matching /dashboard/offices and the Wednesday reset."""
    found = [o for o in await db.agent_profiles.distinct("office") if o]
    return {"offices": sorted(found)}


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


@api_router.get("/vault/export")
async def vault_export(
    week_start: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    format: str = "json",
    office: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_level(4)),
):
    """Export retained production entries as a WAR-format weekly report — the
    same shape import_war_data.py reads, so the JSON round-trips and serves as
    a permanent backup. Defaults to the current Wed-to-Wed week.

    `format=xlsx` rebuilds the WAR workbook itself — same tabs, same columns,
    same header — from the app's own data, so it can be read beside an old
    report or re-imported unchanged. This is the report the office has always
    worked from, so any admin may pull it.

    `format=csv` is a flat per-agent-per-day dump, a different thing from the
    report, and is restricted to EXPORT_EMAILS."""
    if format not in ("json", "csv", "xlsx"):
        raise HTTPException(status_code=400, detail="format must be json, csv or xlsx")
    if format == "xlsx" and not user_is_admin(user):
        raise HTTPException(status_code=403,
                            detail="The WAR workbook export is admin-only")
    if format == "csv" and not user_may_export(user):
        raise HTTPException(status_code=403,
                            detail="The per-agent CSV export is restricted")
    def _parse(d: str) -> date:
        try:
            return date.fromisoformat(d)
        except ValueError:
            raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD")

    if week_start:
        ws = _parse(week_start)
        # A WAR workbook carries nine daily tabs — "Wed (2)"/"Thurs (2)" reach
        # into the next week — so the xlsx needs two days more than the summary.
        frm, to = ws, ws + timedelta(days=8 if format == "xlsx" else 6)
    elif start and end:
        frm, to = _parse(start), _parse(end)
        if to < frm:
            raise HTTPException(status_code=400, detail="end cannot be before start")
    elif start or end:
        raise HTTPException(status_code=400, detail="provide both start and end, or week_start")
    else:
        today = date.fromisoformat(current_sales_day_str())
        frm = today - timedelta(days=(today.weekday() - 2) % 7)  # most recent Wednesday
        to = today
    from_iso, to_iso = frm.isoformat(), to.isoformat()

    # The 14 Nightly Metrics come straight from the PulseIn schema — never
    # hardcode metric names.
    metric_fields = list(PulseIn.model_fields.keys())
    ids = await visible_agent_ids(user)
    q: Dict[str, Any] = {"sales_day": {"$gte": from_iso, "$lte": to_iso}}
    if ids is not None:
        q["agent_id"] = {"$in": ids}
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": {"sales_day": "$sales_day", "agent_id": "$agent_id"},
            **{f: {"$sum": f"${f}"} for f in metric_fields},
        }},
    ]
    rows = [d async for d in db.production_entries.aggregate(pipeline)]
    agents = {a["agent_id"]: a async for a in db.agent_profiles.find({}, {"_id": 0})}

    # Build day -> [performance rows] with the canonical WAR field names, so the
    # output re-imports through make_entry() with per-agent totals intact.
    by_day: Dict[str, list] = {}
    flat = []  # rows for CSV
    total_alp = 0.0
    for r in rows:
        aid = r["_id"]["agent_id"]
        sd = r["_id"]["sales_day"]
        a = agents.get(aid)
        perf: Dict[str, Any] = {"agent": a["name"] if a else aid, "office": a.get("office", "") if a else ""}
        for f in metric_fields:
            perf[f] = r.get(f, 0)
        perf["alp"] = perf.pop("gross_alp", 0)  # WAR carries gross ALP under "alp"
        total_alp += float(perf["alp"] or 0)
        by_day.setdefault(sd, []).append(perf)
        flat.append({"date": sd, **perf, "gross_alp": perf["alp"]})

    if format == "csv":
        cols = ["date", "agent", "office", *[f for f in metric_fields if f != "gross_alp"], "gross_alp"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in sorted(flat, key=lambda x: (x["date"], -float(x.get("alp", 0) or 0))):
            w.writerow(row)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="war_export_{from_iso}_{to_iso}.csv"'},
        )

    if format == "xlsx":
        if not week_start:
            raise HTTPException(status_code=400,
                                detail="xlsx export needs week_start=YYYY-MM-DD")
        # A WAR report covers one office. Without a filter the workbook would
        # mix offices under a single header, which is not a report anyone can
        # reconcile — so default to the office carrying the most rows.
        counts: Dict[str, int] = {}
        for p in flat:
            counts[p.get("office") or UNASSIGNED_OFFICE] = \
                counts.get(p.get("office") or UNASSIGNED_OFFICE, 0) + 1
        sheet_office = office or (max(counts, key=lambda k: counts[k]) if counts else "Unknown")

        # Every agent in that office, listed on every tab whether or not they
        # produced — real reports carry the whole roster, and a name vanishing
        # on a quiet day is exactly what makes two files hard to compare.
        roster_docs = [
            a async for a in db.agent_profiles.find(
                {"office": sheet_office},
                {"_id": 0, "agent_id": 1, "name": 1, "state": 1, "office": 1},
            )
        ]
        if ids is not None:
            allowed = set(ids)
            roster_docs = [a for a in roster_docs if a["agent_id"] in allowed]

        names = {a["agent_id"]: a.get("name", a["agent_id"]) async for a in
                 db.agent_profiles.find({}, {"_id": 0, "agent_id": 1, "name": 1})}
        roles = {a["agent_id"]: (a.get("role"), a.get("io_role")) async for a in
                 db.agent_profiles.find({}, {"_id": 0, "agent_id": 1, "role": 1, "io_role": 1})}

        roster = []
        for a in sorted(roster_docs, key=lambda x: x.get("name") or ""):
            chain = await _ancestor_chain(a["agent_id"])
            person = {"name": a.get("name", a["agent_id"]), "state": a.get("state"),
                      "mga": None, "ga": None, "sa": None}
            for up in chain:
                role, io_role = roles.get(up, (None, None))
                if person["sa"] is None and io_role == "SA":
                    person["sa"] = names.get(up)
                elif person["ga"] is None and role == "level_2":
                    person["ga"] = names.get(up)
                elif person["mga"] is None and role == "level_3":
                    person["mga"] = names.get(up)
            roster.append(person)

        rows_by_day: Dict[str, Dict[str, Any]] = {}
        for p in flat:
            if (p.get("office") or UNASSIGNED_OFFICE) != sheet_office:
                continue
            rows_by_day.setdefault(p["date"], {})[p["agent"]] = p

        buf = await asyncio.to_thread(
            war_export.build_workbook, sheet_office, frm, roster, rows_by_day)
        safe = re.sub(r"[^A-Za-z0-9]+", "_", sheet_office).strip("_") or "office"
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":
                     f'attachment; filename="{from_iso}_{safe}_War_Report.xlsx"'},
        )

    weekly_tabs = []
    for sd in sorted(by_day.keys()):
        perfs = sorted(by_day[sd], key=lambda p: -float(p.get("alp", 0) or 0))
        weekly_tabs.append({
            "tab_name": sd,
            "date": sd,
            "daily_alp": round(sum(float(p.get("alp", 0) or 0) for p in perfs), 2),
            "performance": perfs,
        })
    return {
        "report_metadata": {
            "source_file": f"vantagelife_export_{from_iso}_{to_iso}.json",
            "rga_office": "ALL",
            "weekly_total_alp": round(total_alp, 2),
            "week_ending": to_iso,
            "processed_at": iso_utc(now_utc()),
            "tab_sync_complete": True,
        },
        "weekly_tabs": weekly_tabs,
    }


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
    # Only the current, un-archived entries belong to the week being closed.
    # Entries are retained as a permanent transactional record, so every field
    # below must be scoped to active entries — otherwise prior weeks' retained
    # data would be re-counted into this week's snapshot.
    active = {"archived": {"$ne": True}}
    # Snapshot totals
    totals_pipe = [
        {"$match": active},
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
        a = await aggregate_alp({"agent_id": {"$in": ag_ids}, "archived": {"$ne": True}})
        by_office[office] = a

    snapshot = {
        "week_id": f"wk_{uuid.uuid4().hex[:8]}",
        "week_start": week_start,
        "archived_at": now_utc(),
        "totals": totals,
        "by_office": by_office,
        "agent_count": await db.agent_profiles.count_documents(dict(ACTIVE_AGENT)),
    }
    await db.historical_vault.insert_one(snapshot)
    # Retain entries as the permanent transactional record: flag the week's
    # active entries as archived instead of deleting them. Daily/weekly/monthly
    # scoreboards roll over on their own via their time windows; the flag keeps
    # each future snapshot scoped to just its own week.
    archived_result = await db.production_entries.update_many(
        active,
        {"$set": {"archived": True, "archived_week": week_start, "archived_at": now_utc()}},
    )
    snapshot["entries_archived"] = archived_result.modified_count
    snapshot.pop("_id", None)
    snapshot["archived_at"] = iso_utc(snapshot["archived_at"])
    return {"ok": True, "snapshot": snapshot}


@api_router.post("/admin/purge-archived")
async def purge_archived(
    older_than_days: int = 365,
    dry_run: bool = False,
    user: Dict[str, Any] = Depends(require_level(4)),
):
    """Retention purge: delete archived entries older than `older_than_days`
    (default 365) — but only for weeks already snapshotted in historical_vault,
    so nothing is dropped without a backing record. Active (un-archived) entries
    are never touched. Idempotent and safe to schedule: a cron can POST this.

    (When a persisted work-report backup store exists — see #13 follow-up — the
    backing guard should additionally require that backup to be present.)"""
    if older_than_days < 1:
        raise HTTPException(status_code=400, detail="older_than_days must be >= 1")
    cutoff = (date.fromisoformat(current_sales_day_str()) - timedelta(days=older_than_days)).isoformat()
    candidate_q = {"archived": True, "sales_day": {"$lt": cutoff}}

    # A week is safe to purge only if historical_vault holds its snapshot.
    weeks = [w for w in await db.production_entries.distinct("archived_week", candidate_q) if w]
    backed, unbacked = [], []
    for w in weeks:
        if await db.historical_vault.find_one({"week_start": w}, {"_id": 1}):
            backed.append(w)
        else:
            unbacked.append(w)

    purge_q = {**candidate_q, "archived_week": {"$in": backed}}
    would_purge = await db.production_entries.count_documents(purge_q)
    skipped = await db.production_entries.count_documents(
        {**candidate_q, "archived_week": {"$nin": backed}}
    )

    purged = 0
    if not dry_run and backed:
        purged = (await db.production_entries.delete_many(purge_q)).deleted_count

    summary = {
        "ok": True,
        "dry_run": dry_run,
        "cutoff": cutoff,
        "older_than_days": older_than_days,
        "weeks_purged": sorted(backed),
        "weeks_skipped_unbacked": sorted(unbacked),
        "entries_purged": would_purge if dry_run else purged,
        "entries_skipped_unbacked": skipped,
    }
    logger.info("purge-archived: %s", summary)
    return summary


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


class AdminSetUplineIn(BaseModel):
    agent_id: str
    upline_agent_id: Optional[str] = None  # null detaches (valid only for RGA)


class AdminMergeOfficeIn(BaseModel):
    from_office: str
    to_office: str


class AdminSetFlagsIn(BaseModel):
    email: str
    is_admin: Optional[bool] = None
    can_switch_role: Optional[bool] = None


class SelfRoleIn(BaseModel):
    role: str  # level_1..level_4


def _login_ts(value: Any) -> Optional[str]:
    """Serialize a stored login timestamp for the admin roster (None passes through)."""
    if isinstance(value, datetime):
        return iso_utc(value)
    return value or None


@api_router.get("/admin/people")
async def admin_people(user: Dict[str, Any] = Depends(require_admin)):
    """Full roster with login-link status, login/activity timestamps, permission
    flags, and a launch-engagement summary, for the Admin screen. Removed
    (archived) people are returned separately and excluded from the summary."""
    everyone = [a async for a in db.agent_profiles.find(
        {}, {"_id": 0, "agent_id": 1, "name": 1, "email": 1, "phone": 1,
             "office": 1, "role": 1, "io_role": 1, "upline_id": 1, "is_rookie": 1,
             "state": 1, "archived": 1, "archived_at": 1, "archived_by_name": 1,
             "former_upline_id": 1},
    ).sort("name", 1)]
    users_by_email: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({}, {"_id": 0, "email": 1, "is_admin": 1, "can_switch_role": 1,
                                      "created_at": 1, "first_login_at": 1, "last_seen_at": 1}):
        users_by_email[str(u.get("email", "")).lower()] = u
    agents, archived = [], []
    for a in everyone:
        u = users_by_email.get(str(a.get("email", "")).lower())
        a["has_login"] = u is not None
        a["is_admin"] = bool(u and u.get("is_admin")) or str(a.get("email", "")).lower() in ADMIN_EMAILS
        a["can_switch_role"] = bool(u and u.get("can_switch_role"))
        # Accounts predating these fields fall back to created_at — for them the
        # account was created by their first sign-in.
        a["first_login_at"] = _login_ts(u.get("first_login_at") or u.get("created_at")) if u else None
        a["last_seen_at"] = _login_ts(u.get("last_seen_at") or u.get("created_at")) if u else None
        if a.pop("archived", None):
            a["archived_at"] = _login_ts(a.get("archived_at"))
            archived.append(a)
        else:
            a.pop("archived_at", None)
            a.pop("archived_by_name", None)
            a.pop("former_upline_id", None)
            agents.append(a)
    signed_in = sum(1 for a in agents if a["has_login"])
    return {"people": agents, "archived": archived,
            "summary": {"roster": len(agents), "signed_in": signed_in}}


@api_router.post("/admin/set-role")
async def admin_set_role(payload: AdminSetRoleIn, user: Dict[str, Any] = Depends(require_admin)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    agent = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.get("archived"):
        # The users sync below would re-activate their login role while the
        # profile stays archived — restore is the only path back.
        raise HTTPException(status_code=400, detail="This person was removed — restore them first (Admin Panel → Archived)")
    await db.agent_profiles.update_one(
        {"agent_id": payload.agent_id},
        {"$set": {"role": payload.role, "updated_at": now_utc()}},
    )
    # Sync any linked login so the change takes effect without a re-login.
    email = str(agent.get("email", "")).lower()
    if email:
        await db.users.update_many({"email": email}, {"$set": {"role": payload.role, "agent_id": payload.agent_id}})
    return {"ok": True, "agent_id": payload.agent_id, "role": payload.role}


async def _roster_add_person(
    *,
    name: str,
    email: str,
    phone: str,
    office: str,
    role: str,
    io_role: Optional[str],
    upline_agent_id: Optional[str],
    is_rookie: Optional[bool],
    state: Optional[str],
    changed_by: Dict[str, Any],
) -> Dict[str, Any]:
    """Shared onboarding core for /admin/add-person and /team/add-person: creates
    the agent_profile keyed by email so their very first Google/Apple sign-in
    links to the right role automatically. Callers own their permission checks;
    all business validation lives here so the two paths cannot drift."""
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if is_rookie is None:
        raise HTTPException(status_code=400, detail="Tenure is required — choose Veteran or Rookie")
    email = email.lower().strip()
    name = name.strip()
    if not email or "@" not in email or not name:
        raise HTTPException(status_code=400, detail="Name and a valid email are required")
    if role != "level_4" and not upline_agent_id:
        # Team rollups walk agent_profiles.upline_id (visible_agent_ids BFS) — an
        # agent created without an upline is invisible in every GA/MGA team view.
        raise HTTPException(status_code=400, detail="Upline is required for everyone below RGA tier")
    if upline_agent_id:
        upline = await db.agent_profiles.find_one(
            {"agent_id": upline_agent_id, **ACTIVE_AGENT}, {"_id": 0, "agent_id": 1})
        if not upline:
            raise HTTPException(status_code=404, detail="Upline agent not found or was removed from the team")
    existing = await db.agent_profiles.find_one({"email": email}, {"_id": 0})
    if existing:
        if existing.get("archived"):
            raise HTTPException(
                status_code=409,
                detail=f"{existing.get('name', 'Someone')} held this email and was removed — restore them from the Admin Panel instead of re-adding")
        raise HTTPException(status_code=409, detail=f"{existing.get('name', 'Someone')} already has this email on the roster")
    now = now_utc()
    profile = {
        "agent_id": f"agent_{uuid.uuid4().hex[:10]}",
        "name": name,
        "email": email,
        "phone": re.sub(r"\D", "", phone or ""),
        "office": office.strip() or "MJ RGA",
        "role": role,
        "upline_id": upline_agent_id,
        "is_rookie": is_rookie,
        "created_at": now,
        "joined_at": now,
    }
    if io_role:
        profile["io_role"] = io_role.strip()
    if state:
        profile["state"] = state.strip().upper()
    await db.agent_profiles.insert_one(profile)
    profile.pop("_id", None)
    # If they signed in before being rostered they hold a "pending" users doc — link it now.
    await db.users.update_many({"email": email}, {"$set": {"role": role, "agent_id": profile["agent_id"]}})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "add_agent",
        "agent_id": profile["agent_id"],
        "agent_name": name,
        "changed_by": changed_by["user_id"],
        "changed_by_name": changed_by.get("name"),
        "role": role,
        "is_rookie": is_rookie,
        "upline_id": upline_agent_id,
    })
    return profile


@api_router.post("/admin/add-person")
async def admin_add_person(payload: AdminAddPersonIn, user: Dict[str, Any] = Depends(require_admin)):
    """Onboard a person with full control (any office, any upline) — admin only."""
    profile = await _roster_add_person(
        name=payload.name, email=payload.email, phone=payload.phone,
        office=payload.office, role=payload.role, io_role=payload.io_role,
        upline_agent_id=payload.upline_agent_id, is_rookie=payload.is_rookie,
        state=payload.state, changed_by=user,
    )
    return {"ok": True, "agent": profile}


class TeamAddPersonIn(BaseModel):
    name: str
    email: str
    phone: str = ""
    role: str = "level_1"  # must be strictly below the requester's own level
    io_role: Optional[str] = None  # display title: Agent, SA, GA, ...
    is_rookie: Optional[bool] = None  # required — surfaced as a clear 400, like admin add
    state: Optional[str] = None


@api_router.post("/team/add-person")
async def team_add_person(payload: TeamAddPersonIn, user: Dict[str, Any] = Depends(require_level(2))):
    """Let any upline (SA and above, level_2+) onboard a new team member DIRECTLY
    UNDER THEMSELVES. The upline is always the requester — never client-chosen —
    so the new member automatically rolls up through the requester's existing
    chain (SA → GA → MGA → RGA) in every team view. Office is inherited from the
    requester for the same reason. Placement elsewhere is an admin action."""
    me = await db.agent_profiles.find_one({"agent_id": user["agent_id"]}, {"_id": 0})
    if not me:
        raise HTTPException(status_code=404, detail="Your agent profile was not found")
    my_level = int(str(user.get("role", "level_1")).split("_")[1])
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    new_level = int(payload.role.split("_")[1])
    if new_level >= my_level:
        raise HTTPException(
            status_code=403,
            detail="You can only add team members below your own level — ask an admin for anything else")
    profile = await _roster_add_person(
        name=payload.name, email=payload.email, phone=payload.phone,
        office=str(me.get("office") or "").strip() or UNASSIGNED_OFFICE,
        role=payload.role, io_role=payload.io_role,
        upline_agent_id=me["agent_id"],  # forced: directly under the requester
        is_rookie=payload.is_rookie, state=payload.state, changed_by=user,
    )
    return {"ok": True, "agent": profile}


# ---------- Remove / reassign / restore (archive-and-detach, never delete) ----------

class TeamRemovePersonIn(BaseModel):
    agent_id: str
    # Admin-only: where the removed person's direct reports go when the target
    # has no upline of their own (a root RGA). For everyone else the decision
    # tree is fixed — downlines always go to the removed leader's former upline.
    destination_upline_agent_id: Optional[str] = None
    dry_run: bool = False
    reason: str = ""


class TeamReassignIn(BaseModel):
    agent_id: str
    new_upline_agent_id: str


class AdminUnarchivePersonIn(BaseModel):
    agent_id: str
    upline_agent_id: Optional[str] = None  # null allowed only when restoring a root RGA


async def _remove_person_context(user: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
    """Shared permission + target resolution for remove-person. Owner's decision
    tree: you may remove anyone in your own downline whose tier is strictly
    below yours (so GA cannot remove SA — same tier — and RGA cannot remove
    RGA); admins may remove anyone but themselves. Built on get_current_user,
    not require_agent, so an admin without an agent link can still act."""
    is_admin = user_is_admin(user)
    my_level = role_level(user.get("role"))
    if not is_admin and (my_level < 2 or not user.get("agent_id")):
        raise HTTPException(status_code=403, detail="Removing team members requires SA level or above")
    target = await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    if target.get("archived"):
        raise HTTPException(status_code=400, detail=f"{target.get('name', 'This person')} is already removed")
    if target["agent_id"] == user.get("agent_id"):
        raise HTTPException(status_code=400, detail="You can't remove yourself from the team")
    if not is_admin:
        if role_level(target.get("role")) >= my_level:
            raise HTTPException(
                status_code=403,
                detail="You can only remove team members below your own level — ask an admin for anything else")
        # level_4 is agency-wide, matching visible_agent_ids and can_enter_for
        # ("RGA can do whatever they want" — except remove another RGA, above).
        if my_level < 4 and target["agent_id"] not in await downline_agent_ids(user["agent_id"]):
            raise HTTPException(status_code=403, detail="You can only remove people in your own downline")
    return {"target": target, "is_admin": is_admin}


@api_router.post("/team/remove-person")
async def team_remove_person(payload: TeamRemovePersonIn, user: Dict[str, Any] = Depends(get_current_user)):
    """Remove someone from the team: archive their profile and detach them.

    Nothing is deleted — the profile is flagged archived so their production
    history keeps aggregating into the hierarchy's sales records, and their
    login drops to the pending screen on next sign-in. Direct reports are
    reassigned to the removed leader's former upline, subtrees intact.
    `dry_run` returns the exact plan (same plan-then-apply shape as the
    duplicate-merge and hierarchy-audit tools) so the app can show "their N
    agents will move under X" before the confirm."""
    ctx = await _remove_person_context(user, payload.agent_id)
    target, is_admin = ctx["target"], ctx["is_admin"]

    destination_id = target.get("upline_id")
    if is_admin and payload.destination_upline_agent_id:
        destination_id = payload.destination_upline_agent_id.strip()
    children = [c async for c in db.agent_profiles.find(
        {"upline_id": target["agent_id"], **ACTIVE_AGENT},
        {"_id": 0, "agent_id": 1, "name": 1, "role": 1, "io_role": 1, "office": 1})]

    destination = None
    if children and not destination_id:
        # Owner decision #1: a top-of-tree removal has nowhere to send the
        # downline, so the admin must pick a destination as part of the removal.
        raise HTTPException(
            status_code=400,
            detail=("They have no upline to inherit their team — an admin must "
                    "choose a destination upline as part of the removal"))
    child_ids = {c["agent_id"] for c in children}
    promoted = False
    if destination_id and children:
        # Only validated when there is a downline to move — removing a leaf
        # never needs a destination, even if their own upline is long gone.
        destination = await db.agent_profiles.find_one(
            {"agent_id": destination_id, **ACTIVE_AGENT}, {"_id": 0})
        if not destination:
            raise HTTPException(status_code=404, detail="Destination upline not found or is archived")
        if destination["agent_id"] == target["agent_id"]:
            raise HTTPException(status_code=400, detail="Destination can't be the person being removed")
        # A destination inside the target's subtree is allowed in exactly one
        # form: a DIRECT report, who is promoted into the target's spot (takes
        # the target's own upline; siblings move under them). Anything deeper
        # would leave the chain pointing into the removed branch.
        promoted = destination["agent_id"] in child_ids
        if not promoted and destination["agent_id"] in await downline_agent_ids(target["agent_id"]):
            raise HTTPException(
                status_code=400,
                detail="Destination reports to the person being removed — pick their direct report to promote, or someone outside the team")
        if promoted and not target.get("upline_id") and destination.get("role") != "level_4":
            # Mirrors /admin/set-upline: only an RGA may sit at the top with no upline.
            raise HTTPException(
                status_code=400,
                detail=f"Promoting {destination.get('name', 'them')} to the top requires RGA tier — raise their tier first")

    plan = {
        "agent_id": target["agent_id"],
        "name": target.get("name", ""),
        "role": target.get("role"),
        "io_role": target.get("io_role") or "",
        "children": children,
        "children_count": len(children),
        "destination_upline": (
            {"agent_id": destination["agent_id"], "name": destination.get("name", ""),
             "role": destination.get("role"), "io_role": destination.get("io_role") or "",
             "promoted": promoted}
            if destination else None),
    }
    if payload.dry_run:
        return {"ok": True, "dry_run": True, "plan": plan}

    now = now_utc()
    if children:
        sibling_ids = [c for c in child_ids if c != destination["agent_id"]]
        if sibling_ids:
            await db.agent_profiles.update_many(
                {"agent_id": {"$in": sibling_ids}},
                {"$set": {"upline_id": destination["agent_id"], "updated_at": now}})
        if promoted:
            await db.agent_profiles.update_one(
                {"agent_id": destination["agent_id"]},
                {"$set": {"upline_id": target.get("upline_id"), "updated_at": now}})
    # upline_id is deliberately left in place on the archived profile: the
    # hierarchy walk is what keeps their past production inside the team's
    # sales records. Active-roster queries exclude them via ACTIVE_AGENT.
    await db.agent_profiles.update_one(
        {"agent_id": target["agent_id"]},
        {"$set": {"archived": True, "archived_at": now,
                  "archived_by": user["user_id"], "archived_by_name": user.get("name"),
                  "removed_reason": payload.reason.strip(),
                  "former_upline_id": target.get("upline_id"), "updated_at": now}})
    email = str(target.get("email", "")).lower()
    if email:
        # Lock the login out immediately, not just at next sign-in.
        await db.users.update_many({"email": email}, {"$set": {"role": "pending", "agent_id": None}})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "remove_agent",
        "agent_id": target["agent_id"],
        "agent_name": target.get("name", ""),
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "reason": payload.reason.strip(),
        "children_reassigned": [c["agent_id"] for c in children],
        "destination_upline_id": destination["agent_id"] if destination and children else None,
        "former_upline_id": target.get("upline_id"),
    })
    return {"ok": True, "dry_run": False, "plan": plan}


@api_router.post("/team/reassign")
async def team_reassign(payload: TeamReassignIn, user: Dict[str, Any] = Depends(get_current_user)):
    """Move a downline member under a different upline. Owner's decision tree:
    GA, MGA, and RGA may reassign (not SA — same tier as GA, so the SA display
    title is the only thing that separates them); scope is the mover's own
    downline on both ends. Admins may reassign anyone anywhere."""
    is_admin = user_is_admin(user)
    my_level = role_level(user.get("role"))
    my_subtree: Optional[List[str]] = None
    if not is_admin:
        if my_level < 2 or not user.get("agent_id"):
            raise HTTPException(status_code=403, detail="Reassigning requires GA level or above")
        me = await db.agent_profiles.find_one({"agent_id": user["agent_id"]}, {"_id": 0})
        if not me:
            raise HTTPException(status_code=404, detail="Your agent profile was not found")
        if my_level == 2 and str(me.get("io_role") or "").strip().upper() == "SA":
            raise HTTPException(status_code=403, detail="Reassigning is for GA level and above — ask your GA")
        # level_4 is agency-wide (None = no subtree restriction), matching
        # visible_agent_ids and can_enter_for.
        my_subtree = None if my_level >= 4 else await downline_agent_ids(user["agent_id"])

    target = await db.agent_profiles.find_one({"agent_id": payload.agent_id, **ACTIVE_AGENT}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    if target["agent_id"] == user.get("agent_id"):
        raise HTTPException(status_code=400, detail="You can't reassign yourself")
    new_upline = await db.agent_profiles.find_one(
        {"agent_id": payload.new_upline_agent_id, **ACTIVE_AGENT}, {"_id": 0})
    if not new_upline:
        raise HTTPException(status_code=404, detail="New upline not found or is archived")
    if new_upline["agent_id"] == target["agent_id"]:
        raise HTTPException(status_code=400, detail="An agent cannot be their own upline")
    if not is_admin:
        if role_level(target.get("role")) >= my_level:
            raise HTTPException(status_code=403, detail="You can only move team members below your own level")
        if my_subtree is not None and target["agent_id"] not in my_subtree:
            raise HTTPException(status_code=403, detail="You can only move people in your own downline")
        if my_subtree is not None and new_upline["agent_id"] not in my_subtree:
            raise HTTPException(status_code=403, detail="The new upline must be in your own downline")
        if role_level(new_upline.get("role")) < role_level(target.get("role")):
            raise HTTPException(status_code=400, detail="The new upline must be at or above their level")
    # Same cycle guard as /admin/set-upline: a loop hides both branches.
    if target["agent_id"] in await _ancestor_chain(new_upline["agent_id"]):
        raise HTTPException(
            status_code=400,
            detail="That would create a loop — the chosen upline already reports to this agent")

    now = now_utc()
    await db.agent_profiles.update_one(
        {"agent_id": target["agent_id"]},
        {"$set": {"upline_id": new_upline["agent_id"], "updated_at": now}})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "reassign_agent",
        "agent_id": target["agent_id"],
        "agent_name": target.get("name", ""),
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "old_upline_id": target.get("upline_id"),
        "new_upline_id": new_upline["agent_id"],
    })
    return {"ok": True, "agent_id": target["agent_id"], "upline_id": new_upline["agent_id"]}


@api_router.post("/admin/unarchive-person")
async def admin_unarchive_person(payload: AdminUnarchivePersonIn, user: Dict[str, Any] = Depends(require_admin)):
    """Restore a removed person to the active roster. The upline is chosen at
    restore time (their old branch may have been reorganized since); null is
    allowed only for a root RGA, mirroring /admin/set-upline."""
    target = await db.agent_profiles.find_one({"agent_id": payload.agent_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not target.get("archived"):
        raise HTTPException(status_code=400, detail=f"{target.get('name', 'This person')} is not archived")
    upline_id = (payload.upline_agent_id or "").strip() or None
    if upline_id is None:
        if target.get("role") != "level_4":
            raise HTTPException(
                status_code=400,
                detail="Pick an upline to restore them under — only an RGA may have none")
    else:
        upline = await db.agent_profiles.find_one({"agent_id": upline_id, **ACTIVE_AGENT}, {"_id": 1})
        if not upline:
            raise HTTPException(status_code=404, detail="Upline agent not found or is archived")
        if upline_id == target["agent_id"]:
            raise HTTPException(status_code=400, detail="An agent cannot be their own upline")
        if target["agent_id"] in await _ancestor_chain(upline_id):
            raise HTTPException(
                status_code=400,
                detail="That would create a loop — the chosen upline already reports to this agent")

    now = now_utc()
    await db.agent_profiles.update_one(
        {"agent_id": target["agent_id"]},
        {"$set": {"archived": False, "upline_id": upline_id,
                  "restored_at": now, "restored_by": user["user_id"],
                  "restored_by_name": user.get("name"), "updated_at": now}})
    email = str(target.get("email", "")).lower()
    if email:
        # Re-link any login so their role comes back without a fresh sign-in.
        await db.users.update_many(
            {"email": email}, {"$set": {"role": target["role"], "agent_id": target["agent_id"]}})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "restore_agent",
        "agent_id": target["agent_id"],
        "agent_name": target.get("name", ""),
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "upline_id": upline_id,
    })
    return {"ok": True, "agent_id": target["agent_id"], "upline_id": upline_id}


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


@api_router.get("/admin/orphans")
async def admin_orphans(user: Dict[str, Any] = Depends(require_admin)):
    """Agents unreachable by any team rollup.

    visible_agent_ids() walks DOWN agent_profiles.upline_id, so an agent whose
    upline_id is null — or points at an agent that no longer exists — can never
    be reached, and one broken link severs that agent's whole subtree. Every
    agent minted by the WAR import starts this way. Nothing surfaced them
    before, so they were invisible in every GA/MGA view with no way to notice.

    level_4 is excluded: a root RGA legitimately has no upline.
    """
    everyone = [
        a async for a in db.agent_profiles.find(
            dict(ACTIVE_AGENT), {"_id": 0, "agent_id": 1, "name": 1, "office": 1, "role": 1,
                                 "upline_id": 1, "created_by_import": 1})
    ]
    # `known` is active-only on purpose: an agent still pointing at a removed
    # (archived) upline SHOULD be flagged here — removal reassigns children,
    # so such a link only appears via imports and needs repair.
    known = {a["agent_id"] for a in everyone}
    orphans = []
    for a in everyone:
        if a.get("role") == "level_4":
            continue  # a root RGA has no upline by design
        up = a.get("upline_id")
        if not up:
            reason = "no_upline"
        elif up not in known:
            reason = "dangling_upline"
        else:
            continue
        orphans.append({
            "agent_id": a["agent_id"],
            "name": a.get("name", ""),
            "office": a.get("office") or UNASSIGNED_OFFICE,
            "role": a.get("role", ""),
            "upline_id": up,
            "reason": reason,
            "created_by_import": bool(a.get("created_by_import")),
        })
    orphans.sort(key=lambda o: o["name"])
    return {"orphans": orphans, "total_agents": len(everyone)}


# ---- Bulk upline repair from the committed roster hierarchy (admin) ----
# The orphans endpoint above surfaced ~150 unlinked agents in production —
# every one invisible in their upline's Team tab (found troubleshooting Snoor
# Qaradaghi's missing team, 2026-08-20). Fixing them one at a time through the
# picker is not realistic, but the repo already knows most of the hierarchy:
# the two committed roster scripts record who reports to whom. These routes
# match each orphan against that committed sheet data (tolerant of name-format
# drift) and re-link them in bulk, dry-run first.

def _committed_hierarchy() -> Dict[frozenset, Dict[str, str]]:
    """Person-name-key -> {name, email, upline_name}, newest source last so it
    wins: the two committed roster scripts, then the office's full app-sheet
    snapshot (backend/data/roster/agent_hierarchy_*.csv), which carries
    SA/GA/MGA/RGA columns for all three RGA books."""
    out: Dict[frozenset, Dict[str, str]] = {}
    for name, _phone, email, _io, _role, upline_name in roster_2026_07.ROSTER:
        key = _person_name_key(name)
        if key:
            out[key] = {"name": name, "email": (email or "").strip().lower(),
                        "upline_name": upline_name or ""}
    for name, email, _io, _role, _rookie, upline_name in roster_2026_08.ROSTER:
        key = _person_name_key(name)
        if key:
            out[key] = {"name": name, "email": (email or "").strip().lower(),
                        "upline_name": upline_name or ""}
    for key, entry in roster_hierarchy.load_hierarchy().items():
        out[key] = {"name": entry["name"], "email": entry["email"],
                    "upline_name": entry["upline_name"]}
    return out


async def _find_profile_tolerant(name: str) -> Optional[Dict[str, Any]]:
    """find_profile_by_person_name across every spelling the person goes by
    (curated aliases like "Edward Leon" / "Eddie Leon"), then a
    one-typo-per-token fuzzy pass — the office sheet misspells some of its own
    references ("Afnan Alfatlaway" for "Afnan Alfatlawy"). Fuzzy matching
    stays confined to the hierarchy audit; production-attributing paths (WAR
    import) keep exact matching."""
    for variant in roster_hierarchy.alias_names(name):
        exact = await find_profile_by_person_name(variant)
        if exact:
            return exact
    key = _person_name_key(name)
    if not key:
        return None
    matches = [a async for a in db.agent_profiles.find({}, {"_id": 0})
               if roster_hierarchy.person_match(key, _person_name_key(a.get("name", "")))]
    if not matches:
        return None
    with_email = [a for a in matches if str(a.get("email", "")).strip()]
    return (with_email or matches)[0]


async def _profile_rank(a: Dict[str, Any], child_count: Dict[str, int]) -> Tuple:
    """Keeper-preference rank, same order the duplicates endpoint suggests:
    a linked login first, then a login email, then the larger subtree."""
    logins = await db.users.count_documents({"agent_id": a["agent_id"]})
    entries = await db.production_entries.count_documents({"agent_id": a["agent_id"]})
    return (logins > 0, bool(str(a.get("email", "")).strip()),
            child_count.get(a["agent_id"], 0), entries)


async def _hierarchy_repair_plan() -> Dict[str, Any]:
    """For every orphaned agent (same definition as /admin/orphans), work out
    the fix: an orphan that is a duplicate twin of an already-linked profile
    should be MERGED into it (the WAR import minted these); anyone else gets
    the upline the committed roster sheets record, if they record one."""
    sheet = _committed_hierarchy()
    by_email = {v["email"]: v for v in sheet.values() if v["email"]}
    everyone = [a async for a in db.agent_profiles.find(
        dict(ACTIVE_AGENT), {"_id": 0, "agent_id": 1, "name": 1, "email": 1, "office": 1,
                             "role": 1, "upline_id": 1})]
    known = {a["agent_id"] for a in everyone}
    child_count: Dict[str, int] = {}
    for a in everyone:
        up = a.get("upline_id")
        if up:
            child_count[up] = child_count.get(up, 0) + 1

    def is_linked(a: Dict[str, Any]) -> bool:
        return a.get("role") == "level_4" or (a.get("upline_id") in known)

    linked_by_key: Dict[frozenset, List[Dict[str, Any]]] = {}
    linked_by_login: Dict[str, List[Dict[str, Any]]] = {}
    for a in everyone:
        if is_linked(a):
            key = _person_name_key(a.get("name", ""))
            if key:
                linked_by_key.setdefault(key, []).append(a)
            email = str(a.get("email", "")).strip().lower()
            if email:
                linked_by_login.setdefault(email, []).append(a)

    proposals, merges, unresolved = [], [], []
    for a in everyone:
        if a.get("role") == "level_4" or is_linked(a):
            continue
        key = _person_name_key(a.get("name", ""))

        # Duplicate twin of a linked profile → merge them back into one node.
        # Matched by name key or by login email — the roster sometimes mashes
        # a name ("OTHMAN, WALEEDJASHOLIH" vs "Waleed Othman"), and then only
        # the shared email identifies the twins.
        a_email = str(a.get("email", "")).strip().lower()
        twins = [t for t in linked_by_key.get(key, [])
                 + (linked_by_login.get(a_email, []) if a_email else [])
                 if t["agent_id"] != a["agent_id"]]
        twins = list({t["agent_id"]: t for t in twins}.values())
        if twins:
            ranked = sorted(
                [(await _profile_rank(p, child_count), p) for p in [a] + twins],
                key=lambda t: t[0], reverse=True)
            keep, remove = ranked[0][1], ranked[1][1]
            merges.append({
                "keep_agent_id": keep["agent_id"], "keep_name": keep.get("name", ""),
                "remove_agent_id": remove["agent_id"], "remove_name": remove.get("name", ""),
                "office": a.get("office") or UNASSIGNED_OFFICE,
            })
            continue

        entry = sheet.get(key) or (by_email.get(a_email) if a_email else None)
        if entry is None and key:
            # One-typo and alias tolerance for the sheet's own spelling drift.
            entry = next((v for k2, v in sheet.items()
                          if roster_hierarchy.person_match(key, k2)), None)
        if entry is None or not entry["upline_name"]:
            unresolved.append({"agent_id": a["agent_id"], "name": a.get("name", ""),
                               "office": a.get("office") or UNASSIGNED_OFFICE,
                               "reason": "not_on_sheet"})
            continue
        upline = await _find_profile_tolerant(entry["upline_name"])
        if upline is None or upline["agent_id"] == a["agent_id"]:
            unresolved.append({"agent_id": a["agent_id"], "name": a.get("name", ""),
                               "office": a.get("office") or UNASSIGNED_OFFICE,
                               "reason": "upline_not_found",
                               "sheet_upline": entry["upline_name"]})
            continue
        proposals.append({
            "agent_id": a["agent_id"],
            "name": a.get("name", ""),
            "office": a.get("office") or UNASSIGNED_OFFICE,
            "upline_agent_id": upline["agent_id"],
            "upline_name": upline.get("name", ""),
        })
    proposals.sort(key=lambda p: p["name"].lower())
    merges.sort(key=lambda p: p["keep_name"].lower())
    unresolved.sort(key=lambda p: p["name"].lower())
    return {"proposals": proposals, "merges": merges, "unresolved": unresolved,
            "orphan_count": len(proposals) + len(merges) + len(unresolved)}


@api_router.get("/admin/hierarchy-audit")
async def admin_hierarchy_audit(user: Dict[str, Any] = Depends(require_admin)):
    """Dry-run: which unlinked agents the committed roster hierarchy can
    re-link, and who still needs a manual upline assignment."""
    return await _hierarchy_repair_plan()


@api_router.post("/admin/hierarchy-audit/fix")
async def admin_hierarchy_audit_fix(user: Dict[str, Any] = Depends(require_admin)):
    """Apply the plan above: merge each orphan that duplicates a linked
    profile, then set each remaining resolvable orphan's upline to the one the
    roster sheets record. Same cycle guard as /admin/set-upline, re-checked at
    apply time since each link changes the tree."""
    plan = await _hierarchy_repair_plan()

    merged = []
    for m in plan["merges"]:
        keep = await db.agent_profiles.find_one({"agent_id": m["keep_agent_id"]}, {"_id": 0})
        remove = await db.agent_profiles.find_one({"agent_id": m["remove_agent_id"]}, {"_id": 0})
        if not keep or not remove:
            continue  # an earlier merge in this run already consumed it
        merge_plan = await _plan_agent_merge(keep, remove)
        await _apply_agent_merge(keep, remove, merge_plan, user["user_id"], user.get("name"))
        merged.append(m)

    # Re-plan after the merges: a merged keeper may have adopted its upline,
    # and its former children now hang off a linked profile.
    plan = await _hierarchy_repair_plan()
    applied, skipped = [], list(plan["unresolved"])
    now = now_utc()
    for p in plan["proposals"]:
        if p["agent_id"] in await _ancestor_chain(p["upline_agent_id"]):
            skipped.append({**p, "reason": "would_create_cycle"})
            continue
        await db.agent_profiles.update_one(
            {"agent_id": p["agent_id"]},
            {"$set": {"upline_id": p["upline_agent_id"], "updated_at": now}})
        applied.append(p)
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "hierarchy_bulk_relink",
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "applied_count": len(applied),
        "merged_count": len(merged),
        "applied": [{"agent_id": p["agent_id"], "upline_agent_id": p["upline_agent_id"]}
                    for p in applied],
        "merged": [{"keep_agent_id": m["keep_agent_id"],
                    "remove_agent_id": m["remove_agent_id"]} for m in merged],
    })
    return {"ok": True, "applied": applied, "merged": merged, "unresolved": skipped}


# ---- Full roster-sheet sync (admin) ----
# Owner request (2026-08-21): the 2026-08-20 app sheet is the source of truth
# for tier, display title, tenure, and the entire upline structure — sync the
# app to it. One deliberate exception: the sync only RAISES access tiers to
# match a person's sheet position; it never lowers anyone's access on its own.
# The sheet structurally shows e.g. MJ Aljahmi as an MGA under Joseph Gojcaj,
# but he is level_4 in the app by explicit owner decision — demotions are
# reported for human review instead of applied. Titles follow the same rule:
# Partner / Senior Partner are deliberate titles carried by level_3/level_4
# holders and are never overwritten.

_PROTECTED_TITLES = {"partner", "senior partner"}


def _level_of(role: str) -> int:
    try:
        return int(str(role or "level_1").split("_")[1])
    except (IndexError, ValueError):
        return 1


async def _roster_sync_plan() -> Dict[str, Any]:
    sheet = roster_hierarchy.load_hierarchy()
    profiles = [a async for a in db.agent_profiles.find({}, {"_id": 0})]
    known = {a["agent_id"] for a in profiles}
    by_email = {str(a.get("email", "")).strip().lower(): a
                for a in profiles if str(a.get("email", "")).strip()}

    def match_profile(entry: Dict[str, str]) -> Optional[Dict[str, Any]]:
        key = roster_hierarchy.name_key(entry["name"])
        for a in profiles:
            if roster_hierarchy.person_match(key, _person_name_key(a.get("name", ""))):
                return a
        return by_email.get(entry["email"]) if entry["email"] else None

    changes, demotions_review, to_create = [], [], []
    matched_ids = set()
    for entry in sheet.values():
        prof = match_profile(entry)
        if prof is None:
            to_create.append(entry)
            continue
        matched_ids.add(prof["agent_id"])
        if prof.get("archived"):
            # Removed in-app; the sheet hasn't caught up. Matching (above)
            # stops a duplicate being created, and skipping here stops a sync
            # from resurrecting or re-linking them. Restore is the only path back.
            continue
        change: Dict[str, Any] = {}
        cur_level, sheet_level = _level_of(prof.get("role")), _level_of(entry["role"])
        if sheet_level > cur_level:
            change["role"] = entry["role"]
        elif sheet_level < cur_level:
            demotions_review.append({
                "agent_id": prof["agent_id"], "name": prof.get("name", ""),
                "app_role": prof.get("role"), "sheet_position": entry["io_role"],
            })
        cur_title = str(prof.get("io_role") or "").strip()
        if cur_title.lower() not in _PROTECTED_TITLES:
            if not cur_title or ("role" in change and cur_title != entry["io_role"]):
                if entry["io_role"] != cur_title:
                    change["io_role"] = entry["io_role"]
        tenure = entry["tenure"].strip().lower()
        target_rookie = True if tenure.startswith("rookie") else False if tenure.startswith("vet") else None
        if target_rookie is not None and prof.get("is_rookie") != target_rookie:
            change["is_rookie"] = target_rookie
        for field in ("email", "phone"):
            if not str(prof.get(field) or "").strip() and entry[field]:
                change[field] = entry[field]
        if entry["upline_name"]:
            upline = await _find_profile_tolerant(entry["upline_name"])
            cur_upline = prof.get("upline_id")
            if (upline and upline["agent_id"] != prof["agent_id"]
                    and upline["agent_id"] != cur_upline
                    and prof["agent_id"] not in await _ancestor_chain(upline["agent_id"])):
                # Correct a wrong or dangling link — but never null out a valid
                # one silently; this only re-points to the sheet's upline.
                change["upline_id"] = upline["agent_id"]
                change["upline_name"] = upline.get("name", "")
        if change:
            changes.append({"agent_id": prof["agent_id"], "name": prof.get("name", ""),
                            "current_role": prof.get("role"), **change})

    not_on_sheet = sorted(
        ({"agent_id": a["agent_id"], "name": a.get("name", ""),
          "office": a.get("office") or UNASSIGNED_OFFICE}
         for a in profiles if a["agent_id"] not in matched_ids and not a.get("archived")),
        key=lambda x: x["name"].lower())
    changes.sort(key=lambda c: c["name"].lower())
    return {"changes": changes, "to_create": [e["name"] for e in to_create],
            "_create_entries": to_create, "demotions_review": demotions_review,
            "not_on_sheet": not_on_sheet, "sheet_size": len(sheet),
            "profiles_total": len(profiles), "known_ids": known}


@api_router.get("/admin/roster-sync")
async def admin_roster_sync(user: Dict[str, Any] = Depends(require_admin)):
    """Preview: what syncing the app to the committed roster sheet would
    change — tier raises, titles, tenure, upline corrections, missing profiles
    to create — plus demotion candidates and app-only people, both left for
    human review."""
    plan = await _roster_sync_plan()
    plan.pop("_create_entries", None)
    plan.pop("known_ids", None)
    return plan


@api_router.post("/admin/roster-sync/fix")
async def admin_roster_sync_fix(user: Dict[str, Any] = Depends(require_admin)):
    """Apply the sync: per-profile field updates (role raises re-synced onto
    linked logins, per the sign-in invariant), then create sheet people the
    app lacks — in sheet order, so each new profile's upline usually already
    exists."""
    plan = await _roster_sync_plan()
    now = now_utc()

    applied = []
    for c in plan["changes"]:
        sets = {k: v for k, v in c.items()
                if k in ("role", "io_role", "is_rookie", "email", "phone", "upline_id")}
        if not sets:
            continue
        if "email" in sets:
            sets["email"] = str(sets["email"]).strip().lower()
        await db.agent_profiles.update_one(
            {"agent_id": c["agent_id"]}, {"$set": {**sets, "updated_at": now}})
        if "role" in sets:
            await db.users.update_many(
                {"agent_id": c["agent_id"]}, {"$set": {"role": sets["role"]}})
        applied.append(c)

    created = []
    for entry in plan["_create_entries"]:
        upline = None
        if entry["upline_name"]:
            upline = await _find_profile_tolerant(entry["upline_name"])
        if entry["role"] != "level_4" and upline is None:
            continue  # an agent created without an upline would be a fresh orphan
        tenure = entry["tenure"].strip().lower()
        profile = {
            "agent_id": f"agent_{uuid.uuid4().hex[:10]}",
            "name": entry["name"],
            "email": entry["email"],
            "phone": entry["phone"],
            "office": (upline.get("office") if upline else "") or UNASSIGNED_OFFICE,
            "role": entry["role"],
            "io_role": entry["io_role"],
            "upline_id": upline["agent_id"] if upline else None,
            "created_at": now,
        }
        if tenure.startswith("rookie"):
            profile["is_rookie"] = True
        elif tenure.startswith("vet"):
            profile["is_rookie"] = False
        await db.agent_profiles.insert_one(dict(profile))
        if entry["email"]:
            await db.users.update_many(
                {"email": entry["email"]},
                {"$set": {"role": entry["role"], "agent_id": profile["agent_id"]}})
        created.append(entry["name"])

    if created:
        # An upline that only came into existence in the creation pass above
        # couldn't be linked in the first pass — one re-plan settles those.
        replan = await _roster_sync_plan()
        for c in replan["changes"]:
            if "upline_id" not in c:
                continue
            await db.agent_profiles.update_one(
                {"agent_id": c["agent_id"]},
                {"$set": {"upline_id": c["upline_id"], "updated_at": now}})
            applied.append(c)

    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "roster_sheet_sync",
        "changed_by": user["user_id"],
        "changed_by_name": user.get("name"),
        "changes_applied": len(applied),
        "profiles_created": len(created),
        "changes": [{k: v for k, v in c.items() if k != "current_role"} for c in applied],
    })
    return {"ok": True, "applied": applied, "created": created,
            "demotions_review": plan["demotions_review"],
            "not_on_sheet": plan["not_on_sheet"]}


# ---- Duplicate agent profiles (admin) ----
# Root cause found troubleshooting Snoor Qaradaghi's Team tab (2026-08-20):
# each import path spelled names its own way — the roster script wrote
# "QARADAGHI, SNOOR" while the WAR import and the office's app sheet wrote
# "Snoor Qaradaghi" — and every exact-name lookup saw "no match" and minted a
# second profile for the same human. The person's downline then splits: some
# agents' upline_id points at one profile, the rest at the other. Sign-in links
# a login to exactly one profile (by email), so the person sees only that
# fragment of their team — and the fragment they do see reads $0 / "No Pulse",
# because those agents' own logins attach their entries to the *other* twin.

def _person_name_key(name: str) -> frozenset:
    """Order/case/punctuation-insensitive identity key: "QARADAGHI, SNOOR" and
    "Snoor Qaradaghi" both map to {"snoor", "qaradaghi"}. Mirrors
    import_missing_roster.norm_name so every tool agrees on who is who."""
    cleaned = re.sub(r"[^a-z'\- ]", " ", str(name).replace(",", " ").lower())
    return frozenset(t for t in cleaned.split() if t)


async def find_profile_by_person_name(name: str) -> Optional[Dict[str, Any]]:
    """Resolve a human's profile tolerating name-format drift. Exact
    (case-insensitive) match first; then the token-set key above. If duplicate
    profiles exist for the person, prefer the one a login can attach to (has an
    email), then the one with the larger downline — so imports keep attaching
    production to the profile the person and their team actually see."""
    exact = await db.agent_profiles.find_one(
        {"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}}, {"_id": 0})
    if exact:
        return exact
    key = _person_name_key(name)
    if not key:
        return None
    matches = [a async for a in db.agent_profiles.find({}, {"_id": 0})
               if _person_name_key(a.get("name", "")) == key]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    ranked = []
    for a in matches:
        downline = await db.agent_profiles.count_documents({"upline_id": a["agent_id"]})
        ranked.append((bool(str(a.get("email", "")).strip()), downline, a))
    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return ranked[0][2]


@api_router.get("/admin/duplicates")
async def admin_duplicates(user: Dict[str, Any] = Depends(require_admin)):
    """Groups of agent_profiles that are the same human twice: identical name
    key (any word order / case / "Last, First" formatting) or identical login
    email. Each member is annotated with what hangs off it, and the group
    carries a suggested keeper: the profile a login is linked to, else the one
    with a login email, else the larger subtree."""
    profiles = [a async for a in db.agent_profiles.find(dict(ACTIVE_AGENT), {"_id": 0})]
    child_count: Dict[str, int] = {}
    for a in profiles:
        up = a.get("upline_id")
        if up:
            child_count[up] = child_count.get(up, 0) + 1

    grouped: Dict[Any, List[Dict[str, Any]]] = {}
    for a in profiles:
        key = _person_name_key(a.get("name", ""))
        if key:
            grouped.setdefault(("name", key), []).append(a)
        email = str(a.get("email", "")).strip().lower()
        if email:
            grouped.setdefault(("email", email), []).append(a)

    names = {a["agent_id"]: a.get("name", "") for a in profiles}
    groups, seen_id_sets = [], set()
    for (reason, _), members in grouped.items():
        if len(members) < 2:
            continue
        id_set = frozenset(m["agent_id"] for m in members)
        if len(id_set) < 2 or id_set in seen_id_sets:
            continue  # same pair already reported under the other reason
        seen_id_sets.add(id_set)
        annotated = []
        for m in members:
            aid = m["agent_id"]
            entries = await db.production_entries.count_documents({"agent_id": aid})
            logins = await db.users.count_documents({"agent_id": aid})
            annotated.append({
                "agent_id": aid,
                "name": m.get("name", ""),
                "email": str(m.get("email", "")).strip(),
                "office": m.get("office") or UNASSIGNED_OFFICE,
                "role": m.get("role", ""),
                "io_role": m.get("io_role") or "",
                "upline_id": m.get("upline_id"),
                "upline_name": names.get(m.get("upline_id") or "", ""),
                "downline_count": child_count.get(aid, 0),
                "entries_count": entries,
                "logins_count": logins,
                "created_by_import": bool(m.get("created_by_import")),
            })
        annotated.sort(
            key=lambda x: (x["logins_count"] > 0, bool(x["email"]),
                           x["downline_count"], x["entries_count"]),
            reverse=True)
        groups.append({
            "reason": "same_name" if reason == "name" else "same_email",
            "suggested_keep_agent_id": annotated[0]["agent_id"],
            "profiles": annotated,
        })
    groups.sort(key=lambda g: g["profiles"][0]["name"].lower())
    return {"groups": groups, "total_agents": len(profiles)}


class AdminMergeAgentsIn(BaseModel):
    keep_agent_id: str
    remove_agent_id: str
    dry_run: bool = False


@api_router.post("/admin/merge-agents")
async def admin_merge_agents(
    payload: AdminMergeAgentsIn,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Fold a duplicate profile into the one being kept, so the person is one
    node in the hierarchy again: direct reports, production entries, logins,
    push tokens, shoutouts and nominations all move to the keeper, blank keeper
    fields (email, phone, title, tenure...) adopt the duplicate's values, the
    keeper ends at the higher of the two access tiers, and the duplicate is
    deleted. `dry_run` reports every count without writing.

    Production entries: a WAR-import entry on a sales_day the keeper already
    covers is dropped, not moved — both twins were handed the same restated
    WAR rows, and moving them would double-count that day. App-submitted
    entries always move (multiple entries per day are legal and additive)."""
    keep_id, remove_id = payload.keep_agent_id, payload.remove_agent_id
    if keep_id == remove_id:
        raise HTTPException(status_code=400, detail="Pick two different profiles to merge")
    keep = await db.agent_profiles.find_one({"agent_id": keep_id}, {"_id": 0})
    remove = await db.agent_profiles.find_one({"agent_id": remove_id}, {"_id": 0})
    if not keep or not remove:
        raise HTTPException(status_code=404, detail="Agent not found")

    plan = await _plan_agent_merge(keep, remove)
    report = {
        "ok": True,
        "dry_run": payload.dry_run,
        "keep_agent_id": keep_id,
        "remove_agent_id": remove_id,
        **{k: plan[k] for k in ("final_role", "final_upline_id", "adopted_fields",
                                "children_repointed", "entries_moved",
                                "entries_dropped_war_duplicates", "logins_relinked",
                                "push_tokens_moved")},
    }
    if payload.dry_run:
        return report
    await _apply_agent_merge(keep, remove, plan, user["user_id"], user.get("name"))
    return report


async def _plan_agent_merge(keep: Dict[str, Any], remove: Dict[str, Any]) -> Dict[str, Any]:
    keep_id, remove_id = keep["agent_id"], remove["agent_id"]
    keep_level = int(str(keep.get("role", "level_1")).split("_")[1])
    remove_level = int(str(remove.get("role", "level_1")).split("_")[1])
    final_role = f"level_{max(keep_level, remove_level)}"

    # The keeper adopts the duplicate's upline when its own is missing,
    # dangling (points at a profile that no longer exists), or — worse —
    # points at the duplicate itself (about to be deleted). Guarded against
    # self-loops and cycles the same way /admin/set-upline is.
    final_upline = keep.get("upline_id")
    if final_upline == remove_id:
        final_upline = None
    if final_upline and not await db.agent_profiles.find_one(
            {"agent_id": final_upline}, {"_id": 1}):
        final_upline = None
    if not final_upline:
        candidate = remove.get("upline_id")
        if (candidate and candidate not in (keep_id, remove_id)
                and await db.agent_profiles.find_one({"agent_id": candidate}, {"_id": 1})
                and keep_id not in await _ancestor_chain(candidate)):
            final_upline = candidate

    adopted = {}
    for field in ("email", "phone", "io_role", "state", "office"):
        if not str(keep.get(field) or "").strip() and str(remove.get(field) or "").strip():
            adopted[field] = remove[field]
    if keep.get("is_rookie") is None and remove.get("is_rookie") is not None:
        adopted["is_rookie"] = remove["is_rookie"]
    if not keep.get("created_by_import") or not remove.get("created_by_import"):
        adopted["created_by_import"] = False

    keep_days = set(await db.production_entries.distinct("sales_day", {"agent_id": keep_id}))
    move_entry_ids, drop_entry_ids = [], []
    async for e in db.production_entries.find(
            {"agent_id": remove_id}, {"_id": 0, "entry_id": 1, "sales_day": 1, "source": 1}):
        if e.get("sales_day") in keep_days and e.get("source") == war_import.WAR_IMPORT_SOURCE:
            drop_entry_ids.append(e["entry_id"])
        else:
            move_entry_ids.append(e["entry_id"])

    children_q = {"upline_id": remove_id, "agent_id": {"$ne": keep_id}}
    return {
        "final_role": final_role,
        "final_upline_id": final_upline,
        "adopted": adopted,
        "adopted_fields": sorted(adopted.keys()),
        "move_entry_ids": move_entry_ids,
        "drop_entry_ids": drop_entry_ids,
        "children_q": children_q,
        "children_repointed": await db.agent_profiles.count_documents(children_q),
        "entries_moved": len(move_entry_ids),
        "entries_dropped_war_duplicates": len(drop_entry_ids),
        "logins_relinked": await db.users.count_documents({"agent_id": remove_id}),
        "push_tokens_moved": await db.push_tokens.count_documents({"agent_id": remove_id}),
    }


async def _apply_agent_merge(
    keep: Dict[str, Any], remove: Dict[str, Any], plan: Dict[str, Any],
    changed_by: str, changed_by_name: Optional[str],
) -> None:
    keep_id, remove_id = keep["agent_id"], remove["agent_id"]
    final_role, final_upline = plan["final_role"], plan["final_upline_id"]
    adopted = plan["adopted"]
    move_entry_ids, drop_entry_ids = plan["move_entry_ids"], plan["drop_entry_ids"]
    now = now_utc()
    await db.agent_profiles.update_many(
        plan["children_q"], {"$set": {"upline_id": keep_id, "updated_at": now}})
    await db.agent_profiles.update_one(
        {"agent_id": keep_id},
        {"$set": {**adopted, "role": final_role, "upline_id": final_upline, "updated_at": now}})
    if move_entry_ids:
        await db.production_entries.update_many(
            {"entry_id": {"$in": move_entry_ids}},
            {"$set": {"agent_id": keep_id, "updated_at": now}})
    if drop_entry_ids:
        await db.production_entries.delete_many({"entry_id": {"$in": drop_entry_ids}})
    # Per the sign-in invariant, users re-derive role/agent_id from
    # agent_profiles by email — but update the linked docs now so the fix is
    # visible without waiting for the next sign-in.
    await db.users.update_many(
        {"agent_id": remove_id}, {"$set": {"agent_id": keep_id, "role": final_role}})
    if adopted.get("email"):
        await db.users.update_many(
            {"email": str(adopted["email"]).strip().lower()},
            {"$set": {"agent_id": keep_id, "role": final_role}})
    if final_role != keep.get("role"):
        await db.users.update_many({"agent_id": keep_id}, {"$set": {"role": final_role}})
    await db.push_tokens.update_many(
        {"agent_id": remove_id}, {"$set": {"agent_id": keep_id}})
    for field in ("agent_id", "posted_by_agent_id", "ga_team_id"):
        await db.shoutouts.update_many({field: remove_id}, {"$set": {field: keep_id}})
    for field in ("nominee_agent_id", "nominator_agent_id"):
        await db.nominations.update_many({field: remove_id}, {"$set": {field: keep_id}})
    async for nom in db.nominations.find(
            {"endorsements.agent_id": remove_id}, {"_id": 0, "nomination_id": 1, "endorsements": 1}):
        ends = [{**e, "agent_id": keep_id} if e.get("agent_id") == remove_id else e
                for e in nom.get("endorsements", [])]
        await db.nominations.update_one(
            {"nomination_id": nom["nomination_id"]}, {"$set": {"endorsements": ends}})
    await db.agent_profiles.delete_one({"agent_id": remove_id})
    await db.audit_log.insert_one({
        "audit_id": f"au_{uuid.uuid4().hex[:10]}",
        "ts": now,
        "action": "merge_agents",
        "agent_id": keep_id,
        "agent_name": keep.get("name"),
        "merged_agent_id": remove_id,
        "merged_agent_name": remove.get("name"),
        "changed_by": changed_by,
        "changed_by_name": changed_by_name,
        "entries_moved": plan["entries_moved"],
        "entries_dropped_war_duplicates": plan["entries_dropped_war_duplicates"],
        "children_repointed": plan["children_repointed"],
    })


# ---- Roster email audit (admin) ----
# Server-side twin of `python backend/audit_roster_emails.py`: verifies every
# agent_profiles email against the committed roster sheet snapshot
# (backend/data/roster/) and, on the fix route, applies the same corrections.
# The CLI module owns all matching/fix logic (covered by
# tests/test_audit_roster_emails.py); it is written for sync pymongo, so these
# routes run it in a worker thread over a short-lived sync client instead of
# duplicating the logic against motor and letting the two drift.

def _sync_roster_db():
    from pymongo import MongoClient
    return MongoClient(mongo_url, serverSelectionTimeoutMS=15000)[os.environ['DB_NAME']]


def _run_roster_audit(fix: bool, changed_by: str) -> Dict[str, Any]:
    roster = roster_audit.load_roster(roster_audit.DEFAULT_CSV)
    f = roster_audit.audit(_sync_roster_db(), roster, fix=fix, changed_by=changed_by)
    return {
        "fixed": fix,
        "roster_size": len(roster),
        "ok": len(f["ok"]),
        "mismatches": [
            {"name": e["name"], "db_email": str(p.get("email", "")), "sheet_email": e["email"]}
            for e, p in f["mismatch"]
        ],
        "not_lowercase": [
            {"name": str(p.get("name", "")), "email": str(p.get("email", ""))}
            for p in f["not_lower"]
        ],
        "missing": [
            {"app_id": e["app_id"], "name": e["name"], "email": e["email"]}
            for e in f["missing"]
        ],
        "ambiguous": [
            {"name": e["name"], "sheet_email": e["email"],
             "candidates": [{"name": str(h.get("name", "")), "email": str(h.get("email", ""))}
                            for h in hits]}
            for e, hits in f["ambiguous"]
        ],
        "conflicts": [
            {"name": e["name"], "sheet_email": e["email"],
             "holders": [{"name": str(h.get("name", "")), "role": str(h.get("role", "")),
                          "agent_id": str(h.get("agent_id", ""))} for h in holders]}
            for e, _profile, holders in f["conflict"]
        ],
        "extra": [
            {"name": str(p.get("name", "")), "email": str(p.get("email", "")),
             "role": str(p.get("role", ""))}
            for p in f["extra"]
        ],
    }


@api_router.get("/admin/roster-audit")
async def admin_roster_audit(user: Dict[str, Any] = Depends(require_admin)):
    """Dry-run report only — nothing is written."""
    return await asyncio.to_thread(_run_roster_audit, False, f"admin:{user['user_id']}")


@api_router.post("/admin/roster-audit/fix")
async def admin_roster_audit_fix(user: Dict[str, Any] = Depends(require_admin)):
    """Apply the email corrections the audit found: update mismatched /
    non-lowercase profile emails to the sheet's value, link any waiting
    "pending" login under the corrected email, unlink logins keyed to the
    replaced address, and write audit_log entries. Missing people are never
    auto-created (role tier and upline can't be derived from an email sheet) —
    onboard them through Add Person."""
    return await asyncio.to_thread(_run_roster_audit, True, f"admin:{user['user_id']}")


@api_router.post("/admin/set-upline")
async def admin_set_upline(
    payload: AdminSetUplineIn,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Repair an agent's upline.

    There was previously no way to change an upline through the API at all —
    add-person is create-only and every other admin write touches a single
    unrelated field — so an orphaned agent could only be fixed with direct
    database access.
    """
    agent = await db.agent_profiles.find_one(
        {"agent_id": payload.agent_id}, {"_id": 0, "agent_id": 1, "role": 1, "archived": 1})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.get("archived"):
        raise HTTPException(status_code=400, detail="This person was removed — restore them first (Admin Panel → Archived)")

    upline_id = (payload.upline_agent_id or "").strip() or None
    if upline_id is None:
        # Detaching is only ever right for a root RGA; for anyone else it
        # recreates the exact invisibility this endpoint exists to fix.
        if agent.get("role") != "level_4":
            raise HTTPException(
                status_code=400,
                detail="Only an RGA may have no upline — everyone else needs one to appear in team rollups.",
            )
    else:
        if upline_id == payload.agent_id:
            raise HTTPException(status_code=400, detail="An agent cannot be their own upline")
        if not await db.agent_profiles.find_one({"agent_id": upline_id, **ACTIVE_AGENT}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Upline agent not found or was removed from the team")
        # A cycle would make downline_agent_ids unable to reach either branch
        # from above, silently hiding both.
        if payload.agent_id in await _ancestor_chain(upline_id):
            raise HTTPException(
                status_code=400,
                detail="That would create a loop — the chosen upline already reports to this agent.",
            )

    await db.agent_profiles.update_one(
        {"agent_id": payload.agent_id},
        {"$set": {"upline_id": upline_id, "updated_at": now_utc()}},
    )
    return {"ok": True, "agent_id": payload.agent_id, "upline_id": upline_id}


@api_router.get("/admin/offices")
async def admin_offices(user: Dict[str, Any] = Depends(require_admin)):
    """Offices on the roster with headcount, so duplicates are visible.

    One office recorded under two names (a WAR sheet header says
    "Mohamed Aljahmi RGA" where the roster says "MJ RGA") shows up as two tabs
    everywhere offices are listed, and splits that office's numbers between
    them. agent_profiles is the source of truth, so the duplicate has to be
    resolved here rather than worked around downstream.
    """
    rows = [
        r async for r in db.agent_profiles.aggregate([
            {"$group": {"_id": "$office", "agents": {"$sum": 1}}},
            {"$sort": {"agents": -1}},
        ])
    ]
    return {"offices": [
        {"office": r["_id"] or "(none)", "agents": r["agents"]}
        for r in rows
    ]}


@api_router.post("/admin/merge-office")
async def admin_merge_office(
    payload: AdminMergeOfficeIn,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Move every agent from one office name onto another.

    Renames on agent_profiles only. Nothing reads production_entries.office for
    grouping any more, so historical entries need no rewrite — offices resolve
    through the roster, which means this corrects past weeks too.
    """
    src = payload.from_office.strip()
    dst = payload.to_office.strip()
    if not src or not dst:
        raise HTTPException(status_code=400, detail="Both office names are required")
    if src == dst:
        raise HTTPException(status_code=400, detail="Office names are the same")
    if not await db.agent_profiles.find_one({"office": src}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"No agents in office '{src}'")

    result = await db.agent_profiles.update_many(
        {"office": src}, {"$set": {"office": dst, "updated_at": now_utc()}}
    )
    return {"ok": True, "from_office": src, "to_office": dst,
            "agents_moved": result.modified_count}


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


def _foreign_offices(roster_offices: Dict[str, int]) -> List[Dict[str, Any]]:
    """Offices in a WAR file other than the one most of its agents belong to.

    A file is expected to cover a single office. Anything else means the sheet
    lists agents from elsewhere, whose production would be attributed to this
    file's office — the failure that made one office's totals swallow another's.
    """
    if len(roster_offices) < 2:
        return []
    dominant = max(roster_offices, key=lambda k: roster_offices[k])
    return [
        {"office": off, "rows": n}
        for off, n in sorted(roster_offices.items(), key=lambda kv: -kv[1])
        if off != dominant
    ]


@api_router.post("/admin/import-war-report")
async def admin_import_war_report(
    file: UploadFile = File(...),
    week_start: Optional[str] = Form(None),
    dry_run: bool = Form(False),
    create_missing: bool = Form(False),
    user: Dict[str, Any] = Depends(require_admin),
):
    """Import one weekly WAR spreadsheet into production_entries.

    In-app replacement for the terminal backfill script (import_xlsx_war.py):
    both read the same layout via war_import, so they cannot drift apart.

    Overlap rule: each report carries NINE daily tabs, so "Wed (2)"/"Thurs (2)"
    land on the same sales days as the NEXT report's "Wed"/"Thurs". The later
    file wins — a re-import replaces an existing WAR-sourced entry for the same
    (agent, sales_day), so corrections in the following week's report are kept
    rather than dropped. Entries an agent submitted in-app are never replaced;
    they are reported under "protected" and left untouched.
    """
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload a .xlsx WAR report")

    # Week start comes from the filename date (the Wednesday the report opens
    # on) unless explicitly supplied. Without it every tab would be misdated.
    if week_start:
        try:
            ws_date = date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="week_start must be YYYY-MM-DD")
    else:
        ws_date = war_import.week_start_from_filename(filename)
        if ws_date is None:
            raise HTTPException(
                status_code=400,
                detail="Could not read the week start from the filename — expected "
                       "'YYYY-MM-DD_...xlsx', or send week_start explicitly.",
            )
    if ws_date.weekday() != 2:
        raise HTTPException(
            status_code=400,
            detail=f"Week start {ws_date.isoformat()} is a "
                   f"{ws_date.strftime('%A')} — WAR reports open on Wednesday.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        parsed = await asyncio.to_thread(war_import.parse_workbook, io.BytesIO(raw), ws_date)
    except Exception as e:
        logger.exception("WAR import failed to parse %s", filename)
        raise HTTPException(status_code=400, detail=f"Could not read the spreadsheet: {e}")

    office = parsed["office"]
    # Roster office of every matched agent, counted by row. A WAR sheet is
    # supposed to cover one office; if its agents mostly belong to another,
    # the file is mislabelled or mixed, and importing it would attribute their
    # production to the wrong office. Reported so preview catches it.
    roster_offices: Dict[str, int] = {}
    inserted = replaced = protected = skipped_unmatched = 0
    created_agents: List[str] = []
    unmatched: Dict[str, Dict[str, Any]] = {}
    days_seen: List[str] = []

    for date_str in sorted(parsed["days"].keys()):
        rows = parsed["days"][date_str]
        days_seen.append(date_str)
        for m in rows:
            name = str(m["name"]).strip()
            # Tolerant of name-format drift ("Snoor Qaradaghi" vs the roster's
            # "QARADAGHI, SNOOR"): the old exact-only match minted a second
            # profile for the same human, splitting their upline's team view.
            profile = await find_profile_by_person_name(name)
            if not profile:
                if not create_missing:
                    # Report rather than orphan: an agent created without an
                    # upline is invisible in every GA/MGA team rollup, since
                    # visible_agent_ids() walks agent_profiles.upline_id.
                    unmatched.setdefault(name, {
                        "name": name,
                        "mga": m.get("mga"), "ga": m.get("ga"), "sa": m.get("sa"),
                        "state": m.get("state"), "rows": 0,
                    })
                    unmatched[name]["rows"] += 1
                    skipped_unmatched += 1
                    continue
                agent_id = f"agent_{uuid.uuid4().hex[:10]}"
                await db.agent_profiles.insert_one({
                    "agent_id": agent_id,
                    "name": name,
                    # Deliberately NOT the spreadsheet's office name: a WAR sheet
                    # header reads "Mohamed Aljahmi RGA" where the roster reads
                    # "MJ RGA", and stamping it here is what split one office
                    # into two. Left unassigned for an admin to place.
                    "office": UNASSIGNED_OFFICE,
                    "role": "level_1",
                    "upline_id": None,
                    "created_at": now_utc(),
                    "created_by_import": True,
                })
                created_agents.append(name)
                entry_office = office
            else:
                agent_id = profile["agent_id"]
                # Stamp the roster's office, not the spreadsheet header. The
                # sheet says "Mohamed Aljahmi RGA" where the roster says
                # "MJ RGA"; taking the sheet's version splits one office into
                # two everywhere entries are grouped by office.
                entry_office = profile.get("office") or office
                roster_offices[entry_office] = roster_offices.get(entry_office, 0) + 1

            entry = war_import.build_entry(agent_id, entry_office, date_str, m)
            existing = await db.production_entries.find_one(
                {"agent_id": agent_id, "sales_day": date_str},
                {"_id": 0, "entry_id": 1, "source": 1},
            )
            if existing is None:
                if not dry_run:
                    await db.production_entries.insert_one(entry)
                inserted += 1
            elif existing.get("source") == war_import.WAR_IMPORT_SOURCE:
                if not dry_run:
                    entry["entry_id"] = existing["entry_id"]
                    entry["updated_at"] = now_utc()
                    await db.production_entries.replace_one(
                        {"entry_id": existing["entry_id"]}, entry
                    )
                replaced += 1
            else:
                protected += 1

    return {
        "ok": True,
        "dry_run": dry_run,
        "file": filename,
        "office": office,
        "week_start": ws_date.isoformat(),
        "days": days_seen,
        "tabs_found": parsed["tabs_found"],
        "inserted": inserted,
        "replaced": replaced,
        "protected": protected,
        "skipped_unmatched": skipped_unmatched,
        "created_agents": created_agents,
        "unmatched": sorted(unmatched.values(), key=lambda u: u["name"]),
        # Rows per roster office, biggest first, plus the offices that are not
        # the dominant one. A non-empty foreign_offices means this file mixes
        # offices — worth stopping on before writing.
        "roster_offices": dict(sorted(roster_offices.items(), key=lambda kv: -kv[1])),
        "foreign_offices": _foreign_offices(roster_offices),
    }


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
    # Covers Vercel preview/production deployments AND the custom production
    # domain. Leaving the custom domain out blocks every credentialed browser
    # call from the app's real address — login included — while the .vercel.app
    # URL keeps working, which makes it look like an app bug rather than CORS.
    # Extra origins can be appended via CORS_EXTRA_ORIGIN_REGEX.
    allow_origin_regex=CORS_ORIGIN_REGEX,
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
    await db.production_entries.create_index("archived")
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
