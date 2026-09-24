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

## RBAC Hierarchy (5-tier - NEVER flatten or bypass)
1. `level_1` Agent — enters their own metrics only; reads their own SA team via the Team tab (per owner, 2026-09-19 — see below)
1½. `level_sa` SA — runs a team: reads and enters for their own downline, promotes to Agent/Trainee only — displays as "Regional Producer" (per owner, 2026-09-22 — see "The SA tier" below)
2. `level_2` GA (General Agent) — sees their team rollup, may promote to SA — displays as "CoExecutive Producer"
3. `level_3` MGA (Master General Agent) — sees GA-level rollups — displays as "Executive Producer"
4. `level_4` RGA (Regional General Agent) — sees their own office — displays as "Chief Executive Producer"

**No one sees more than their SA team (per owner, 2026-09-19, from MJ).**
This replaces the 2026-09-16 "a team IS an office" rule, which is retired:
an agent is not to see the whole office. The Team tab's read scope, in one
helper `team_scope_agent_ids()` shared by `GET /api/team`, `/api/team/weeks`,
`/api/agents/{id}/history` and `/api/agents/{id}/day` and never re-derived per
route, is:

- **level_1** — their SA team: the subtree under the nearest SA or GA in
  their upline chain (the SA or GA who runs them), leader included
  (`sa_team_agent_ids()`). Someone straight under an MGA/RGA gets that
  upline's subtree. This is the same grouping `/api/team/missing` uses.
- **level_sa / level_2 / level_3** — their own downline, nothing sideways.
- **level_4** — their own office (plus their downline, normally the same
  people). Gojcaj, Alwatan and Rust see their office, never the agency.
- **MJ** (level_4 with the admin grant) — the whole company by default, his
  own RGA team with the More-tab switch on "own". An admin below level_4
  (Afnan) reads the company in the admin view and her SA team in the agent
  view. `finance_admin` reads the company, read only.

**Uplines are contacts, not rows.** `GET /api/team` returns `uplines`: the
chain above the caller, nearest first, with name, title, phone, email and
office only, never production (`team_uplines()`). The client opens them in
the contact sheet without an `agent_id`, so no history is fetched.

**The dashboard is universal (owner, 2026-09-22).** Every agent, leader and
office opens the same board, whatever their tier and whatever the More-tab
switch says: Push Month, then Agency ALP / Sits / Sales directly under the
countdown, then Top 3 Vets & Rookies with the Platinum Rule, then Production
by Office with its four office tabs, all on the Daily / Weekly / Monthly
selector. `GET /api/dashboard/summary`, `/ticker`, `/platinum-wall` and
`/offices` all take their agent filter from one helper,
`dashboard_agent_ids()`, which returns None (no filter) — never call
`visible_agent_ids` or `team_scope_agent_ids` from a dashboard route, and
never add a per-tier branch there. The summary still carries `scope` and one
scope word runs through the section title and the three stat labels; on
the dashboard that word is always "Agency". The old PRODUCTION HISTORY block
(the viewer's own 13-week chart at the foot of the dashboard) is gone; that
chart lives on the contact card the Team tab opens.

**Top 3 Veterans exclusion (per owner, 2026-09-23):** an `agent_profiles`
record with `exclude_from_platinum_vets: true` is skipped when
`/dashboard/platinum-wall` fills the TOP 3 VETS slots, and the next veteran
moves up. It is a record flag, never a name or id check, and it reaches
nothing else — the person's team, their own numbers and card, the Team tab,
the Hierarchy Map, the ticker and the office roll-ups all still count them.

The Team tab still reads as a leaderboard — agents ranked inside their tenure
group (ROOKIES, VETERANS, and TENURE NOT SET for the people nobody has
recorded one for), leaders ranked among leaders with their own production and
their team's rollup side by side. Rank always runs on Gross ALP, the same
measure the Platinum Wall ranks on, and nobody who produced nothing in the
window is ranked. The secondary filter, REPORTS TO ME, is the caller's
downline — what an upline wants for entry, not for competing.

Three things stay exactly as they were:

- **Coaching cards** stay upline-only (`is_upline_of`).
- **Judgement alerts** (`UPLINE_ONLY_ALERTS`: low close ratio, low average
  deal, no pulse) are stripped from any row outside the caller's own downline —
  the numbers are the team's, the assessment is the upline's. Neutral flags
  such as the rookie badge stay.
- **Every write path** — `can_enter_for`, remove-person, reassign, set-tier —
  stays on `downline_agent_ids`. `team_view` marks each row with
  `in_my_downline` so the client only offers those actions where they would
  succeed; the Team tab also uses it for the MY TEAM / REPORTS TO ME filter.

**Missing Numbers (per owner, 2026-09-19, MJ's request):** `GET
/api/team/missing` lists, for each of the last 7 sales days (max 14), who has
not submitted, grouped by team — every producer filed under the nearest
SA or GA in their chain (an SA or GA heads their own section; someone straight
under an MGA/RGA files under that upline). It is a grouping of the hierarchy,
never a permission, and no access decision reads a title. Scope is the
caller's own **downline** (SA and above; level_4 sees every team), because
the panel exists to enter numbers on people's behalf and that write is
downline-only. Same candidate rule as the 9 PM escalation: active Agent, SA
and GA producers (`NIGHTLY_PULSE_ROLES`), minus non-producing staff. The screen is
`frontend/app/missing.tsx`, opened from the Team tab's MISSING TONIGHT card;
tapping a person opens `QuickEntryForm` aimed at that night
(`initialSalesDay`), ENTER ALL walks one team's list.

**Tier changes by an upline (per owner, 2026-09-14):** `POST /api/team/set-tier`
lets an upline change the access tier of someone in their **own downline**, in
either direction, and only to a tier **strictly below their own** — a GA may
make an SA, an SA may make an Agent, an MGA may make a GA, never a peer. `is_admin` and `finance_admin` get the
same control agency-wide, capped the same way. Setting `level_4`, changing an
RGA's tier, and anything involving the Financial Admin role stay in the Admin
Panel (`/api/admin/set-role`). The producer title (`io_role`) moves with the
tier so access and displayed title cannot drift apart. Two shape guards: nobody
may be raised above their own upline (that inverts the rollup), and nobody with
active direct reports may be lowered (their branch would go dark to them) —
reassign first. Every change is audit-logged as `set_role` and syncs the linked
login so it applies without a re-login.

**Office follows the upline (per owner, 2026-09-22):** a person's office is
set from their upline's, never left to disagree with it. `POST /api/team/reassign`
(the Team tab's MOVE, and the Admin Panel's UPLINE · MOVE) and
`POST /api/admin/set-upline` (orphan repair) both go through `_rehome_under()`:
a move under someone in another office rehomes the person into that office,
so the whole hierarchy above them is the new office's. Crossing an office
line is **admin-only** (`is_admin`: the owner and MJ) — not RGA, not
`finance_admin`; a leader's within-downline move stays inside one office.
`move_downline` (default on, a Switch on the Move sheet) takes the person's
downline with them, office and all, still reporting to them; off, their
direct reports go to the person's former upline (where remove-person parks an
orphaned downline), so nobody is left reporting across an office line.
`POST /api/admin/set-office` corrects **one** record's office with no
hierarchy change (the Admin Panel's OFFICE field) and deliberately does not
cascade. Every one of these is audit-logged with the old and new office and
the ids moved.

**The view switch (per owner, 2026-09-19):** one preference on the users doc,
`view_mode` (`full` | `own`), set by the More tab through
`POST /api/me/view-mode` and offered only where `user_can_toggle_view()` —
an `is_admin` account with a linked producer tier. Two meanings by tier:
MJ (level_4 + admin) flips between the whole company and his own RGA team
on the Team tab (`visible_agent_ids` and `team_scope_agent_ids` return his
downline in `own`; the dashboard does not move — see "The dashboard is
universal" above); Afnan (level_1 + the in-house admin grant) flips between
agent duties and the admin tools (`user_admin_active()` is what the read
paths consult, so in `own` the Team tab marks office peers as not hers and
the client hides the admin menu). It is a preference about what the person
is looking at, never a security boundary: `is_admin` is untouched, every
`require_admin` route keeps honouring it, and no re-login is needed. Morgan
(admin, no agent link) has nothing to narrow to and is not offered it; plain
RGAs are not offered it either — narrowing is MJ's request, not a general
RGA feature. The in-house admin grant itself is still `/api/admin/set-flags`.

Display titles (producer track) are separate from access tiers. `io_role`
titles map via `roleTitle()` in `frontend/src/lib/auth.tsx`: SA → Regional
Producer, GA → CoExecutive Producer, MGA → Executive Producer, RGA → Chief
Executive Producer; Partner and Senior Partner are titles carried by
level_3/level_4 holders (no exclusive access tier); Agent, Builder, and
In Training are unchanged. RBAC is always enforced by `role`, never by title.

**The SA tier (per owner, 2026-09-22; this retires the 2026-07-09 /
2026-09-15 "SA and GA are one tier" rule).** The ladder is Agent < SA < GA <
MGA < RGA. SA is its own tier, `level_sa`, ranked **1.5** in `ROLE_RANK` /
`role_level()` (and `levelNum()` on the client) so the `level_1..level_4`
strings and every existing comparison keep their meaning. What changed is
only what "strictly below your own tier" now yields: **a GA makes an SA, an
SA makes Agents and Trainees only, an MGA makes a GA.** An SA otherwise has
every GA power, limited to their own downline: reads it, enters for it,
promotes, moves and removes inside it, heads a team in Missing Numbers, owes
a nightly pulse and gets the 9 PM ladder. "Is this person a leader" checks
go through `is_leader_role()` / `LEADER_ROLES` (server) and
`levelNum(r) >= LEADER_MIN` (client) — never a bare `>= 2`, which now means
GA and above. `NIGHTLY_PULSE_ROLES` is everyone who owes a pulse (Agent, SA,
GA). Route gates for "any leader" use `require_leader` (= `require_level(RANK_SA)`);
a bare `require_level(2)` would turn every SA away. The Agent, Trainee,
Builder, SA and GA titles are each pinned to one tier (`TITLE_HOME_TIER`,
`title_tier_mismatch()`): set-tier and the shared add-person core reject a
mismatched pair, and an admin tier change replaces a title that belongs to
another tier with the new tier's default (`title_after_tier_change()`;
Partner / Senior Partner survive at MGA and above). `migrate_sa_tier()` runs on every start and moves any
SA-titled `level_2` profile (and login) to `level_sa` once. RBAC is still
enforced by `role`, never by title; the tier does the work.

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
- Leaders' pulse is NIF by default (owner, 2026-09-22): at 06:30 Detroit
  `run_leader_auto_nif()` files an automatic all-zero NIF entry (`is_nif`,
  `auto_nif`, `source: "auto"`, `entered_by: "system"`) for every active,
  producing MGA/RGA — `LEADER_AUTO_NIF_ROLES`, level_3 and level_4 **by
  tier**, never by title — who has no entry for the sales day that closed at
  06:00. Only that one day, never older ones, never twice. A real entry for
  that day (their own or a proxy) deletes the automatic one. For those tiers
  `/pulse/me/today` returns an open gate and `auto_nif: true` (no yellow
  banner), `/pulse/me/streak` returns `exempt: true` (no streak pill), and
  `team_view` files no `no_pulse` flag on their row. Agents, SAs and GAs are
  untouched: the 9 PM ladder and Missing Numbers were already MGA/RGA-free.
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
  comparison: a chain walk is what makes an SA's own upline GA (and nobody
  sideways) the right answer, whatever the ranks say. Decided server-side by `is_upline_of()` and
  returned as `coaching_visible` on `/api/agents/{id}/history`; the client must
  never re-derive it from roles. Read scope (`visible_agent_ids`) is
  deliberately wider than this and must not be conflated with it.
  (Owner, 2026-09-13.)
- Push Month (owner, 2026-09-19; confirmed by MJ): one company-wide Gross ALP
  goal of $2,000,000 across all four offices, from the 2026-09-18 sales day
  through 2026-10-30, drawn at the top of the dashboard. Fill bar throughout;
  a "$X to go" callout joins it at 80%; days-left always shown. Tapping opens
  ALP by day and by office. No per-office sub-goals and no per-team widget
  (MJ declined). Constants `PUSH_GOAL_*` in `backend/server.py` are
  env-overridable so the next campaign is config, not code. Keyed on
  `sales_day` like everything else — the 6 AM boundary decides which side of
  the start a policy lands on.
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
- NEVER allow an Agent to see data above their RBAC tier — the documented exceptions are the Team tab's own-SA-team read and the agent card it opens (see RBAC Hierarchy above), and the dashboard (owner 2026-09-22; Push Month owner 2026-09-19): `GET /api/dashboard/summary`, `/ticker`, `/platinum-wall`, `/offices` and `/push-goal` are company-wide for every tier — rollups, top-3 names with their Gross ALP, office totals and the Push Month goal, never a per-agent history; don't generalize these or extend them to other routes without an explicit owner decision
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
