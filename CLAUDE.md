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
- Auth: custom session tokens — Google OAuth via Auth0, Sign in with Apple, and `/api/auth/demo-login` for RBAC-tier testing
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
1. `level_1` Agent — enters their own metrics only; reads full metrics for their own office via the Team tab (per owner, 2026-09-13 — see below)
2. `level_2` GA (General Agent) — sees their team rollup — displays as "CoExecutive Producer"
3. `level_3` MGA (Master General Agent) — sees GA-level rollups — displays as "Executive Producer"
4. `level_4` RGA (Regional General Agent) — sees all MGA rollups — displays as "Chief Executive Producer"

**A team IS an office (per owner, 2026-09-16).** MJ's team, Rust's team,
Alwatan's, Gojcaj's — the four offices are the four teams, and "my team" in
product language means the whole office, not the caller's downline. Seeing
every person on it is deliberate: motivation, team building and healthy
competition. Do not narrow it back to downline-only. The Team tab opens on the
team and reads as a leaderboard — agents ranked inside their tenure group
(ROOKIES, VETERANS, and TENURE NOT SET for the people nobody has recorded one
for), leaders ranked among leaders with their own production and their team's
rollup side by side. Rank always runs on Gross ALP, the same measure the
Platinum Wall ranks on, and nobody who produced nothing in the window is
ranked. The secondary filter, REPORTS TO ME, is the caller's downline — what an
upline wants for entry, not for competing.

**Office read scope (per owner, 2026-09-13, extended 2026-09-14 and
2026-09-15):** the Team tab shows everyone in the caller's own **office**, at
every tier, plus their own downline wherever it reaches — one helper,
`team_scope_agent_ids()`, shared by `GET /api/team`, `/api/team/weeks`,
`/api/agents/{id}/history` and `/api/agents/{id}/day`, never re-derived per
route. Any agent may see general team stats, their office's sales numbers, any
teammate's day/week/month production, and that teammate's basic ALP and close
ratio on the contact card. The union matters: an MGA's downline can reach past
their home office, and an upline must never see less of the board than the
agents under them do, which is what the 2026-09-15 extension fixed.

Three things are deliberately NOT widened with it:

- **Coaching cards** stay upline-only (`is_upline_of`).
- **Judgement alerts** (`UPLINE_ONLY_ALERTS`: low close ratio, low average
  deal, no pulse) are stripped from any row outside the caller's own downline —
  the numbers are the office's, the assessment is the upline's. Neutral flags
  such as the rookie badge stay.
- **Every write path** — `can_enter_for`, remove-person, reassign, set-tier —
  stays on `downline_agent_ids`. `team_view` marks each row with
  `in_my_downline` so the client only offers those actions where they would
  succeed; the Team tab also uses it for the MY TEAM / MY OFFICE filter.

**Tier changes by an upline (per owner, 2026-09-14):** `POST /api/team/set-tier`
lets an upline change the access tier of someone in their **own downline**, in
either direction, and only to a tier **strictly below their own** — an MGA may
make someone a GA, never another MGA. `is_admin` and `finance_admin` get the
same control agency-wide, capped the same way. Setting `level_4`, changing an
RGA's tier, and anything involving the Financial Admin role stay in the Admin
Panel (`/api/admin/set-role`). The producer title (`io_role`) moves with the
tier so access and displayed title cannot drift apart. Two shape guards: nobody
may be raised above their own upline (that inverts the rollup), and nobody with
active direct reports may be lowered (their branch would go dark to them) —
reassign first. Every change is audit-logged as `set_role` and syncs the linked
login so it applies without a re-login.

Display titles (producer track) are separate from access tiers. `io_role`
titles map via `roleTitle()` in `frontend/src/lib/auth.tsx`: SA → Regional
Producer, GA → CoExecutive Producer, MGA → Executive Producer, RGA → Chief
Executive Producer; Partner and Senior Partner are titles carried by
level_3/level_4 holders (no exclusive access tier); Agent, Builder, and
In Training are unchanged. RBAC is always enforced by `role`, never by title.

SA is a level_2 title: SAs and GAs have identical permissions across the
app (per owner, 2026-07-09, reaffirmed 2026-09-15 — every SA reassigns and
promotes, and SA and GA read the same way). Never model SA as a special case
in code; the tier does the work. Reassigning was the last exception and was
removed on 2026-09-15, so no access decision anywhere reads an `io_role`
title.

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
- Sit Rate (a.k.a. Show Rate) formula: `(Sits + N1) / Sets` — implemented in
  `backend/metrics.py` as `show_rate()`. This is the mirror image of Close Rate
  on the N1 question and for the opposite reason: an N1 person **did** keep the
  appointment and sit through the presentation, they simply could not be
  insured afterwards, so they are added back into the numerator here. It is
  never a bare `Sits / Sets`. (Owner, 2026-09-13, restating the WAR reports'
  own `=IFERROR(SUM(H+L)/G,0)`.)
- Coaching card visibility: everyone **above** an agent in that agent's own
  chain may see their coaching card — SA, GA, MGA, RGA alike — and nobody at or
  below them, and nobody sideways. This is a hierarchy question, never a tier
  comparison: SA and GA are both level_2, so `viewer_level > agent_level`
  denies a GA their own SA's card. Decided server-side by `is_upline_of()` and
  returned as `coaching_visible` on `/api/agents/{id}/history`; the client must
  never re-derive it from roles. Read scope (`visible_agent_ids`) is
  deliberately wider than this and must not be conflated with it.
  (Owner, 2026-09-13.)
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
- NEVER allow an Agent to see data above their RBAC tier — the one documented exception is the Team tab's own-office read and the agent card it opens (see RBAC Hierarchy above); don't generalize it or extend it to other routes without an explicit owner decision
- NEVER change the 6AM cycle boundary without explicit instruction
- NEVER bypass the Wednesday 2PM cutoff gate
- NEVER collapse authentication and authorization into a single check
- NEVER commit directly to main - feature branches always

## Known Gotchas
- N1 looks like a sales metric but is a medical-disqualification tally. It is NOT part of Sits, so never subtract it from Sits and never add it into production totals.
- Reporting cycle starts 6AM Detroit time - all date range queries must go through `sales_day_for()`.
- Users not on the agent roster have role `"pending"` and no `agent_id` — every business-data route must sit behind `require_agent`/`require_level`, which reject them.
- Google OAuth flows through Auth0 (`AUTH0_DOMAIN`/`AUTH0_CLIENT_IDS`, `/api/auth/auth0`): the app runs Auth0 Universal Login routed to the Google connection, and the backend verifies the resulting Auth0-issued ID token against Auth0's own JWKS/issuer, not Google's directly. Sign in with Apple is unaffected and still verifies natively against Apple's JWKS.
- The Emergent auth proxy is fully gone. `/api/auth/session`, `EMERGENT_AUTH_URL`, `SessionExchangeIn`, `signInGoogleSession`, and the OAuth-fragment handler in `index.tsx` were all removed after the Auth0 OTA update reached the fleet (published 2026-09-04, re-published 2026-09-09). Don't reintroduce a session-id exchange path.
- There is no longer a config-only rollback for Google sign-in. While the Emergent fallback existed, clearing the `EXPO_PUBLIC_AUTH0_*` vars fell the app back to the old flow; now an unconfigured build just shows "Google Sign-In Unavailable" and only Apple and demo logins work. Rolling Google back means republishing a previous EAS Update group, not flipping an env var.

## AI Agent Notes
- Ask before modifying any business logic or calculation
- Run `npm run typecheck` and `npm test` after every non-trivial change; stop if they fail
- Read existing patterns in `backend/server.py` and `frontend/src/lib/` before proposing new architecture
- Create feature branches for all work; never commit directly to main
- When uncertain about tier permissions, enforce more restrictive access
