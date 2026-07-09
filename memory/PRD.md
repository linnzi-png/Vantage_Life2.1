# VantageLife 2.0 — Product Requirements Document

**Org:** AO Premier — 174-person sales force
**Vision:** Real-Time Impact Culture
**Stack:** React Native (Expo SDK 56) + FastAPI + MongoDB
**TZ:** America/Detroit (all gates)

## 1. RBAC — The Identity Vault
4-tier hierarchy, filtered automatically by `upline_id`:
- **Level 1 — Agent**: Personal stats + Pulse Entry
- **Level 2 — GA / Co-Executive Producer**: Direct downline team view
- **Level 3 — MGA / Executive Producer**: Full agency hierarchy
- **Level 4 — RGA / Executive**: Global view, Net ALP Eraser, Audit Log, Historical Vault

Five offices: **MCM, AMP, Dearborn, Heritage, Siren**.

## 2. Auth
Emergent Google OAuth (web) + Demo Login bypass (`/api/auth/demo-login`) for the 4 RBAC levels (no Google needed). 7-day session_token (httpOnly cookie + Authorization Bearer).

## 3. Executive Dashboard
- 3 summary cards: **Total Team ALP** (with green/red delta vs yesterday), **Agency Sits**, **Total Sales**.
- **Platinum Wall**: side-by-side Top 3 Vets / Top 3 Rookies ranked by Gross ALP.
- **Office Market Share**: 5 tabs (MCM/AMP/Dearborn/Heritage/Siren) — Office ALP, Total Sales, Avg Deal.
- **LIVE ticker**: scrolling marquee of last 60 minutes — `[Agent] - $[ALP] - [Market] - [Reps]`.
- 30s polling refresh.

## 4. Accountability Gates (America/Detroit)
- **9:00 PM**: Yellow warning banner — *"9:00 PM Deadline Passed. Log your numbers now to avoid leadership escalation."*
- **6:00 AM**: Red lock — Midnight Miracle window closes, missed days marked Red.
- **Wednesday 14:00 reset**: Archive to `Historical_Vault`, zero out active production. Endpoint: `POST /api/admin/wednesday-reset` (Level 4).

## 5. Nightly Pulse Entry (Agent)
14-step stepper form, exact order: sets, sits, sales, OTS sits, OTS sales, N1, referrals, ref sits, ref sales, POS sits, POS sales, vet sits, vet sales, gross ALP. Auto-tagged `submitted_on_time` if before 9 PM.

## 6. Premier Shoutouts
- **Player's Club** (Gold Crown): $10,000+ Gross ALP in a single Sales Day (6 AM → 6 AM). Global scope.
- **Performance Streak** (Fire emoji): 5+ consecutive days of on-time Pulses. Global scope.
- **First Deal** (Welcome to the Board): an agent's first-ever sale — **GA-Team scope only** (visible to immediate GA + Level 4).

## 7. Manager Command Panel — Net ALP Eraser (Level 4)
- "Adjust ALP" with **mandatory 10+ char Reason** for Adjustment.
- **Ledger logic**: adjustments update **Net ALP** (internal) only; **Gross ALP** on Platinum Wall is unchanged.
- **Audit Log** records: timestamp, action, agent, changed_by, original_value, new_value, reason.

## 8. Historical Vault (Level 4)
Last 8 archived weeks. Side-by-side comparison of any two weeks across `gross_alp`, `net_alp`, `sales`, `sits` with delta % (green=positive, red=negative).

## 9. Data Models (Mongo)
- `agent_profiles` (174 seeded): agent_id, name, license, email, phone, resident_state, office, role (level_1..4), upline_id, ga_id, is_rookie, joined_at
- `production_entries`: sales_day, gross_alp, net_alp, sets/sits/sales/OTS/N1/refs, submitted_at, submitted_on_time, is_adjustment, reason
- `audit_log`: ts, action, agent_id, changed_by, original_value, new_value, delta, reason
- `historical_vault`: week_start, archived_at, totals, by_office, agent_count
- `shoutouts`: type (players_club | streak | first_deal), scope (global | ga_team), agent_id, ga_team_id, ts
- `users` + `user_sessions`

## 10. Test Credentials
See `/app/memory/test_credentials.md` — Demo Login emails per level (no password; just hit `/api/auth/demo-login`).

## 11. Notes
- 174 agents auto-seed on first startup (1 RGA → 4 MGAs → 8 GAs → 161 Agents).
- Data spans 7 days; today's batch sprinkles entries within last 60 min for the live ticker.
