# CLAUDE.md - VantageLife 2.1 (AO Premier)

## Project Overview
Real-time sales tracking and victory culture platform for AO Globe Life - Vantage.
Expo/React Native mobile app backed by a Python/FastAPI API over MongoDB.

Brand spelling: always "Premier" (AO Premier, Premier Shoutouts) — never
"Premiere". Exception: legacy identifiers keep the old spelling and must not
change (`com.aopremiere.vantagelife` bundle ID, `@aopremiere.com` demo emails).

## Tech Stack
- Frontend: Expo (SDK 56) / React Native, TypeScript, file-based routing via Expo Router
- Backend: Python / FastAPI (`backend/server.py`), Motor async MongoDB driver
- Database: MongoDB
- Auth: custom session tokens — Emergent-proxied Google OAuth, Sign in with Apple, and `/api/auth/demo-login` for RBAC-tier testing
- Deploy: Railway runs the backend (`railway.json` → `uvicorn server:app`); Vercel hosts the Expo web export (`vercel.json`); iOS builds via EAS (`frontend/eas.json`)
- Package managers: npm (root), yarn (frontend), pip (backend)

## Architecture
- `frontend/app/` — screens, file-based routes (`(tabs)/` for the tab bar, `login.tsx`, etc.)
- `frontend/src/components/` — shared UI components
- `frontend/src/lib/` — utilities, auth/session helpers
- `backend/server.py` — the entire API (routes, auth, RBAC, gates)
- `backend/metrics.py` — metric calculations (Close Rate lives here, never inline)
- `backend/tests/` — pytest suite

## RBAC Hierarchy (4-tier - NEVER flatten or bypass)
1. `level_1` Agent — enters their own metrics only
2. `level_2` GA (General Agent) — sees their team rollup — displays as "CoExecutive Producer"
3. `level_3` MGA (Master General Agent) — sees GA-level rollups — displays as "Executive Producer"
4. `level_4` RGA (Regional General Agent) — sees all MGA rollups — displays as "Chief Executive Producer"

Display titles (producer track) are separate from access tiers. `io_role`
titles map via `roleTitle()` in `frontend/src/lib/auth.tsx`: SA → Regional
Producer, GA → CoExecutive Producer, MGA → Executive Producer, RGA → Chief
Executive Producer; Partner and Senior Partner are titles carried by
level_3/level_4 holders (no exclusive access tier); Agent, Builder, and
In Training are unchanged. RBAC is always enforced by `role`, never by title.

SA is a level_2 title: SAs and GAs have identical permissions across the
app (per owner, 2026-07-09; the prod roster carries every SA at level_2).
Never model SA as a special case in code — the tier does the work.

Enforced server-side in `backend/server.py`: `require_agent()` / `require_level()`
dependencies plus `visible_agent_ids()`, a BFS over `agent_profiles.upline_id`.

## Authentication vs. authorization (two deliberate steps - do not collapse)
1. **Authentication**: any verified identity (Google or Apple) completes sign-in
   successfully. App Store review must be able to finish Sign in with Apple
   without an error — a prior single-step version caused a real rejection.
2. **Authorization**: a separate lookup against `agent_profiles` by email.
   A roster match gets the real role and data; no match gets role `"pending"`
   and a read-only "Account Pending" screen, never an auth error.

## The 14 Nightly Metrics (exact order - do not reorder)
| # | Display name | `PulseIn` field |
|---|--------------|-----------------|
| 1 | Sets | `sets` |
| 2 | Sits | `sits` |
| 3 | Sales | `sales` |
| 4 | OTS Sits | `ots_sits` |
| 5 | OTS Sales | `ots_sales` |
| 6 | N1 ← medically unqualified; already excluded from Sits | `n1` |
| 7 | Referrals | `refs_obtained` |
| 8 | Ref Sits | `ref_sits` |
| 9 | Ref Sales | `ref_sales` |
| 10 | POS Sits | `pos_sits` |
| 11 | POS Sales | `pos_sales` |
| 12 | Vet Sits | `vet_sits` |
| 13 | Vet Sales | `vet_sales` |
| 14 | Gross ALP | `gross_alp` |

## Business Logic (sacred - do not change without explicit instruction)
- Reporting cycle: 6:00 AM to 5:59 AM America/Detroit (not midnight-to-midnight) — see `sales_day_for()`
- Wednesday 2:00 PM = weekly submission cutoff (`POST /api/admin/wednesday-reset`, RGA-only)
- WAR overlap (owner, 2026-08-17): consecutive reports share two days —
  `Wed (2)`/`Thurs (2)` of one book are the same calendar days as the next
  book's `Wed`/`Thurs`. The 2 PM cutoff **splits** that Wednesday: a sale in the
  older book was made **before** 2 PM Eastern, one appearing only in the newer
  book was made **after**. They are two halves of one day, NOT competing records.
  A blank row in the newer book therefore does **not** mean the agent produced
  nothing, and must never be used to delete the older book's entry. In practice
  the office usually restates the overlap days in the new book (15 of 18 such
  rows across MJ's 25 reports carry identical numbers), which is why the
  importer replaces rather than adds. Reconcile with
  `python3 backend/audit_war_overlap.py <folder>`.
- 9 PM gate = yellow warning banner; "Midnight Miracle" = the 12 AM–6 AM entry window (`gate_state()`)
- Close Rate formula: `Sales / Sits` — implemented in `backend/metrics.py`.
  N1 is a person who cannot be insured for medical reasons. An agent has no
  control over that, so it must never count against them — and it doesn't,
  because **N1 people are already left out of the Sits count at entry**. The
  `n1` field is a separate tally, not a subset of Sits, so it is NOT subtracted
  again. (Corrected 2026-08-08 per owner: the prior `Sales / (Sits - N1)` rule
  excluded them twice and inflated every score — the WAR spreadsheets' own
  Close Rate column matched `Sales / Sits` in all 54 rows where the two differ
  and `Sales / (Sits - N1)` in none; office-wide 57.2% vs 68.0%.)
- All metric calculations go in `backend/metrics.py`, never inline in route handlers

## Commands
- Dev (backend + frontend web): `npm run dev`
- Build (Expo web export): `npm run build`
- Type check: `npm run typecheck` (must pass before every commit)
- Tests: `npm test` (pytest over `backend/tests/`)
- Deploy: Railway deploys the backend from main; Vercel builds the web export

## Coding Conventions
- TypeScript strict mode in the frontend. No `any` types. No type assertions.
- Named exports preferred; Expo Router screens are the default-export exception.
- Every Close Rate calculation goes through `metrics.close_rate()` — never inline, and never subtract `n1` from `sits`
- Never hardcode metric names or tier labels — reference the `PulseIn` schema / `LEVELS` map in `backend/server.py`

## Forbidden Patterns
- NEVER subtract N1 from Sits — Sits already excludes them; subtracting double-counts the exclusion
- NEVER allow an Agent to see data above their RBAC tier
- NEVER change the 6AM cycle boundary without explicit instruction
- NEVER bypass the Wednesday 2PM cutoff gate
- NEVER collapse authentication and authorization into a single check
- NEVER commit directly to main - feature branches always

## Known Gotchas
- N1 looks like a sales metric but is a medical-disqualification tally. It is NOT part of Sits, so never subtract it from Sits and never add it into production totals.
- Reporting cycle starts 6AM Detroit time - all date range queries must go through `sales_day_for()`.
- Users not on the agent roster have role `"pending"` and no `agent_id` — every business-data route must sit behind `require_agent`/`require_level`, which reject them.
- Google OAuth still flows through Emergent's auth proxy (`EMERGENT_AUTH_URL`); it is not a plain Google client.

## AI Agent Notes
- Ask before modifying any business logic or calculation
- Run `npm run typecheck` and `npm test` after every non-trivial change; stop if they fail
- Read existing patterns in `backend/server.py` and `frontend/src/lib/` before proposing new architecture
- Create feature branches for all work; never commit directly to main
- When uncertain about tier permissions, enforce more restrictive access
