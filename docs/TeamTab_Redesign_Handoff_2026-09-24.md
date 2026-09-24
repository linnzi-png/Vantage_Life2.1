# VantageLife: Team Tab Redesign Handoff (2026-09-24)

This is a planning handoff for Claude Code. **Plan first, then build.** Linnzi's additional changes are in **section 7**, and they take precedence over sections 2 to 4 where they conflict. Fold everything into one plan, and ask her about anything still open (2e and 7c) before writing code.

---

## 0. How to work on this repo

- **Repo:** `github.com/linnzi-png/Vantage_Life2.1`, branch `main`.
- **Local copy on Linnzi's Windows machine:** `C:\Users\linnz\Vantage_Life2.1`.
  - The working branch there is `feat/universal-dashboard`, and it has uncommitted changes (`frontend/app.json` plus some untracked files). **Do not touch or commit that working tree.**
  - Work in a separate git worktree created from `origin/main`. PR #159 was made that way (`..\vl-switch-copy`).
- **Read `CLAUDE.md` in the repo root first.** It records the owner-decided RBAC rules, the dashboard rules, the view-switch rules, the SA tier, the business logic and the forbidden patterns. Every rule in it still applies.
- **Stack:** Expo SDK 56 / React Native / TypeScript strict (frontend), FastAPI + Motor/MongoDB (backend, all in `backend/server.py`).
  - Railway auto-deploys the backend on merge to `main`.
  - The app ships through EAS OTA updates, which are label-gated.
- **Checks before every commit:** `npm run typecheck` and `npm test` (pytest over `backend/tests/`).
- **Branching:** feature branches only; never commit to `main`.
- **Rollout rule (from the 9/22 login-crash post-mortem):** any server-driven value the current app does not understand ships a tolerant client OTA **first**, and the backend or data change goes out afterwards.
  - The reason: the backend deploys on merge but the OTA is label-gated, so without this order the two are guaranteed to be out of step.
- **Line endings:** `frontend/app/(tabs)/more.tsx` (and likely others) uses CRLF. Preserve line endings when editing, or the diff becomes the whole file.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```
- **Linnzi's standing preferences:**
  - Answer her questions before starting work.
  - Ask all your questions at once in one compact block.
  - Never guess; ask instead.
  - Write in plain, direct full sentences.
  - Put each PowerShell command in its own code block.

---

## 1. Done in this session (for context only)

### 1a. Dashboard vs. MJ's view switch: investigated, no code bug

MJ reported that his More-tab view switch still changed the dashboard. It does not.

- Backend PR #156 ("Universal dashboard") has been live on Railway since 2026-09-24 00:47 UTC (8:47 PM Detroit, 9/23). PR #158 was also live before the screen recording.
- `dashboard_agent_ids()` (`backend/server.py` ~L505) returns `None` for everyone. The summary, ticker, platinum-wall and offices routes all use it, and push-goal is unscoped.
- The number jump in the recording was a real entry arriving mid-recording: Henry Long, 9/23, Gross ALP **$9,464**, `submitted_at` 2026-09-24T02:09:26Z (10:09:26 PM Detroit, the same minute as the recording).
  - Push Month, Agency ALP and his wall figure all rose by exactly $9,464.
- **Confirmed rule:** the dashboard always shows the whole agency. The Production by Office tabs at the bottom change only that section.

### 1b. PR #159: view switch text (open, waiting for merge + OTA)

- Branch `fix/view-switch-copy`, commit `9ef271b`: https://github.com/linnzi-png/Vantage_Life2.1/pull/159
- `frontend/app/(tabs)/more.tsx`, the switch note:
  - **Old:** "On: every office. Off: only the team under you — dashboard, Platinum Wall, offices and Team tab all follow it."
  - **New:** "On: every office. Off: only the team under you. This changes the Team tab only; the dashboard always shows the whole agency."
- This is a copy change only, and it needs an OTA to reach phones.

---

## 2. The main task: Team tab redesign (MJ's request)

### 2a. What MJ asked for (his video, transcribed)

> "See how this is separated by leaders, rookies and veterans? Just have the list show everybody in order — doesn't matter if they're a rookie, veteran or a leader — and then give them the option somewhere over here to click rookies only… turn on a rookies-only tab."

### 2b. Linnzi's decisions (stated, final unless marked open)

1. **Team tab only.** The dashboard Platinum Wall stays as it is (Top 3 Vets / Top 3 Rookies, with the `exclude_from_platinum_vets` flag).
2. **One combined list, ranked on each person's own Gross ALP.** Leaders are ranked on their own sales, the same as everyone else.
3. **Filters on that list:** Rookies only, Veterans only, Leaders only.
4. **Team views with a total team ALP:**
   - **SA Teams**, **GA Teams** and **MGA Teams** as separate views.
   - Each is restricted to the viewer's own office.
   - This is how leaders compare themselves with other leaders at their level in their office.
5. **Filtered lists keep the original number.** Each filtered list is in ranking order, but every person keeps their rank number from the full list, so a rookies list reads 8, 9, 12 and so on.
6. **The Team tab stays scoped to the office** (ranks per office, never across offices).
7. **Applies to everyone** who sees the Team tab, every tier.
8. **The time control changes** (Linnzi, after reviewing the design). **Superseded by 7a.3 (range picker).**
   - Remove the Daily/Weekly/Monthly segmented control **and** the LIVE / week-date chip row.
   - Replace them with **one date button**. The default is **Month to date** (the 1st of the current month through today's sales day).
   - Tapping it opens a sheet with a "Month to date" option and a **calendar** for picking **any single past day**.
   - Month arrows go back as far as the data goes. Future days are disabled.
   - Picking a day shows that one sales day. A "Back to month to date" link returns to the default.
9. **The filter controls must all be visible at once.** **Superseded by 7a.2 (dropdown plus leader-only team selector).**
   - The first design put all seven chips in one sideways-scrolling row, and the SA/GA/MGA Teams chips were off-screen. Linnzi rejected that.
   - Current design: a two-part **PEOPLE | TEAMS** switch.
     - People shows 4 equal buttons: All · Rookies · Veterans · Leaders.
     - Teams shows 3 equal buttons: SA · GA · MGA.
   - MY TEAM / REPORTS TO ME shows only under People.

### 2c. Linnzi's annotated screenshot: how it was read (confirm with her)

She circled four areas of the current Team tab. The design took them to mean "the top of the screen is too crowded; the list starts too low":

- **"· CONTACT ONLY"** on the upline card is dropped; the card now reads "YOUR UPLINE".
- **The MY TEAM / REPORTS TO ME and LIVE / week-date rows** become the date button (section 2b.8) plus the MY TEAM / REPORTS TO ME chips under People.
- **The Missing Tonight card** becomes a slim one-line bar that still opens `/missing` (By Team).
- **The five sort buttons plus the search bar** become one row: the search field with a single "GROSS ALP ▾" sort dropdown beside it. **Superseded by 7a.1 and 7a.2: the metric buttons stay visible, labelled ALP / Sales / Close Ratio / Avg Deal, with no Net ALP.**

Linnzi has not explicitly confirmed this reading. Ask her.

### 2d. Design preview

- Design canvas "Team Tab Redesign": https://claude.ai/artifact/DF136rrbNYGu9Wnh12p6EF (shared with anyone who has the link). There are 9 phone artboards, 390 px wide:
  - `Main` (People · All, month to date)
  - `DatePicker` (calendar sheet)
  - `DayView` (single day, 9/16)
  - `Rookies`, `Veterans`, `Leaders`
  - `SATeams`, `GATeams`, `MGATeams` (empty state: MJ RGA has no MGAs)
- It uses real MJ RGA month-to-date numbers (9/1 to 9/24) and 9/16 for the single-day screen.
- It uses the app's real `COLORS` from `frontend/src/lib/auth.tsx` (bg `#0D0D0D`, surface `#141414`, primary `#319842`, gold `#FFD700`, and so on). It does **not** use the "VantageLife Design System" artifact, whose tokens were inferred from screenshots and don't match the app.
- It is a design reference, not a spec for pixel values. Match the existing `team.tsx` styles where they already exist. **The canvas predates section 7 and no longer matches on the filter layout, the date control, the team dashboard row or the ALP label.**

### 2e. Open decisions: ask Linnzi before building

1. **Who sees what (the most important one).**
   - Today `team_scope_agent_ids()` limits the Team tab: an Agent sees only their SA team, SA/GA/MGA see their own downline, an RGA sees their office, and MJ sees the company (or his RGA team with the switch on "own"). That is MJ's rule from 9/19: "No one sees more than their SA team."
   - The new SA/GA/MGA Teams views are office-wide by Linnzi's decision.
   - **Proposed:** the team views show every team in the office as **total lines only** (leader name, team ALP, team sales, head count, leader's own ALP), and the People lists stay exactly as limited as today.
   - The alternative, everyone seeing every person in the office, would retire MJ's 9/19 rule and needs MJ's sign-off.
2. **Tapping a team line.**
   - Proposed: a team inside the viewer's own downline expands (or opens) its member list; any other team opens the leader's contact card only.
3. **Weekly view.** Answered by 7a.3: a week is a range on the calendar.
4. **Past whole months.** Answered by 7a.3: a whole month is a range on the calendar.
5. **Team total definition.**
   - Proposed: the leader **plus everyone under them**, nested, so a GA team includes the SA teams under that GA.
   - Note that today's `team_gross_alp` on leader rows **excludes the leader** (subtree without root). Pick one definition and make both places agree.
6. **MJ in company view.**
   - Proposed: one section per office (the existing behavior), each with its own ranks and its own team views.
   - Also confirm what the "own" switch position does to the team views (probably: only MJ RGA).
7. **Confirm the screenshot reading** in section 2c.
8. **Data anomaly.**
   - Henry Long ($45,732 month to date) and Adam Youssef ($15,355) have Gross ALP with **0 sales**, which puts them near the top of a combined list.
   - Ask whether that's intended (for example, proxy entries missing the sales count) or needs a data fix.

---

## 3. Current code map

### Backend: `backend/server.py`

| What | Where (approx. line) | Notes |
| --- | --- | --- |
| `downline_agent_ids` | L1025 | write-scope BFS |
| `sa_team_agent_ids` | L1064 | Agent's SA/GA team |
| `team_scope_agent_ids` | L1082 | Team tab read scope; one helper shared by `/api/team`, `/api/team/weeks`, `/api/agents/{id}/history`, `/api/agents/{id}/day`. Never re-derive per route. |
| `visible_agent_ids` | L1144 | |
| `_leaderboard_group` | L151 | `leader` if `is_leader_role`, else `rookie` / `veteran` / `unset` from `is_rookie` |
| `resolve_history_day` | L1278 | validates any past `YYYY-MM-DD`; rejects the future |
| `SCOREBOARD_PERIODS`, `DEFAULT_SCOREBOARD_PERIOD = "weekly"` | L2279 | |
| `scoreboard_window(period, sales_day)` | L2303 | daily (optionally historical) / weekly (from `most_recent_wed_2pm`) / monthly (from `month_start_detroit`), all on `sales_day` |
| `GET /api/team` `team_view(period, week_start)` | L2334 | builds rows, alerts, leader rollups, ranks, `in_my_downline`, `uplines` |
| Leader rollups (`team_gross_alp`, `team_sales`, `team_size`) | ~L2489 to 2531 | one roster read plus one aggregation over the union of subtrees; archived included in production, excluded from head count |
| Ranking | ~L2537 to 2556 | pools keyed by `(office, leaderboard_group)`; `rank` / `rank_of`; `gross_alp > 0` only |
| `week_start_for_day`, `week_day_range` | L3074, L3088 | used by `week_start` and `/api/team/weeks` |
| `GET /api/agents/{id}/day` `agent_day` | ~L3240 | single-day drill-down; same scope as `agent_history` |
| `POST /admin/set-state` | ~L5192 | resident state (single code, WAR export), `require_admin`; **not** the licensed-states list, which is new |

### Frontend: `frontend/app/(tabs)/team.tsx` (663 lines)

| What | Where | Notes |
| --- | --- | --- |
| `usePersistedPeriod('vl_team_period', 'weekly')` | L71 | to be replaced by the date state |
| `weekOptions` + `/api/team/weeks` | L78, L122, L415 to 440 | week-chip row, to be removed |
| Fetch | L95 | `/api/team?week_start=` or `?period=` |
| `scope` MY TEAM / REPORTS TO ME | L61, ~L396 to 413 | stays |
| Client sort (`sortKey`) | L68, L129, L322 to 330, sort bar ~L473 | Gross ALP / Net ALP / Sales / Close % / Avg Deal today; becomes ALP / Sales / Close Ratio / Avg Deal (7a.1, 7b.6) |
| `renderRow` | ~L231 | shows `rank`; the Net line under Gross (L274) goes; the leader row shows the TEAM rollup line |
| `BOARDS` (Leaders / Rookies / Veterans / Tenure not set) | ~L290 to 296 | to be replaced by the single list plus the dropdown |
| Per-office render loop | ~L501 to 535 | office headings when there is more than one office |
| Upline card, "CONTACT ONLY" kicker | styles `uplineCard`, `uplineKicker` | |
| Missing Tonight card | ~L447 to 468 | slim it down |

- Tour anchors used on this screen: `team-weeks`, `team-roster`, `team-missing` (steps in `frontend/src/lib/tourSteps.ts`). The public `/tour` page mirrors the steps, so update both.
- Shared pieces: `PeriodSelector` (`frontend/src/components/PeriodSelector.tsx`), `SearchBar`, `LoadState`, `AgentContactSheet`, `AgentHistory` → `AgentDayDetail` + `CoachingTips`.

### Tests: `backend/tests/`

`test_team_leaderboard.py`, `test_team_period.py`, `test_team_missing.py`, `test_team_add_person.py`, `test_team_remove.py`, `test_team_set_tier.py`

---

## 4. Proposed implementation (adjust after sections 2e and 7c are answered)

### Backend

1. **Time window on `/api/team`:**
   - Add `start_day` and `end_day` query params for an arbitrary range (both validated through `resolve_history_day`; end no later than the current sales day; start no later than end). A single day is `start_day == end_day`.
   - Month to date is the default when neither is given.
   - Keep `period` / `week_start` working for old app builds during the OTA gap.
   - Echo `start_day` and `end_day` in the response so the client labels exactly what the server answered.
2. **Overall rank:**
   - Add `overall_rank` and `overall_rank_of`, ranked per **office** across **all** groups on own `gross_alp > 0`.
   - Keep `rank` / `rank_of` / `leaderboard_group` so old builds keep rendering, then retire them later.
   - Filtered views use `overall_rank` (decision 2b.5).
3. **Team views (leaders only, per 7a.2) with category comparison (7a.5):**
   - New route, for example `GET /api/team/branches?tier=sa|ga|mga&start_day=…&end_day=…`, gated by `require_leader`.
   - Candidates are active leaders whose **tier** is `level_sa` / `level_2` / `level_3` (by `role`, never by title, per CLAUDE.md), in the viewer's own office (MJ's company view: per office).
   - Each line carries: leader `agent_id`, name, title, office, team ALP, team sales, team sits, team close ratio, team show ratio, team average deal, head count, leader's own ALP and sales, and `team_rank` within (office, tier).
   - The response also carries, per category, the best and worst team so the client can call them out without re-deriving.
   - Reuse the existing subtree/rollup approach (one roster read, one aggregation); no BFS per leader. Ratios go through `metrics.py`.
   - Add `in_my_downline` per line so the client knows whether tapping may expand members (decision 2e.2).
   - **RBAC:** these totals are a new documented read above tier (like the dashboard). Document it in CLAUDE.md, and never return per-member rows for teams outside `team_scope_agent_ids`.
4. **Team dashboard row (7a.4):** a summary for the viewer's own scope broken down by SA team, on Daily / Weekly / Monthly, with each person's `licensed_states`. Reuse `scoreboard_window` and the same subtree rollup; it can share the branches route with `tier=sa` scoped to the viewer's downline, or be a small `summary` block on `/api/team`. Decide once the payload shape for 3 is settled.
5. **Tenure Not Set guard (7b.7):** `_leaderboard_group()` and the Platinum Wall's unset section skip archived profiles.
6. **Licensed states (7b.9):** new `licensed_states` list on `agent_profiles` (two-letter codes, validated, deduplicated). `POST /api/me/licensed-states` (self) and `POST /api/team/set-licensed-states` (downline-scoped, `require_leader`), both audit-logged like `set-tenure`. Include it in `/api/team` rows and `/api/agents/{id}/history`. Leave the resident `state` field and `/admin/set-state` untouched.
7. **Shoutouts as notifications (7b.10):** when a shoutout is created, send the push through `send_expo_push` to the scope that would have seen it on the tab. Do not remove the tab until the ChatAI question in 7c is settled.
8. **Keep what must not change:**
   - Upline-only alerts are stripped outside the downline.
   - Write paths stay on `downline_agent_ids`.
   - Coaching cards stay on `is_upline_of`.
   - The Missing Numbers scope is unchanged.
9. **Tests:**
   - Overall rank across groups, per office.
   - Filtered views keep the overall number.
   - Team totals, nested (GA includes SA teams), with archived handling.
   - Per-category best and worst.
   - Office restriction, and MJ's company versus own view.
   - An agent cannot call the branches route; a leader sees office totals but not other teams' members.
   - Range window (single day, week, whole month, future rejected, start after end rejected) and month to date default.
   - Old `period` / `week_start` requests still work.
   - Archived profiles never land in the unset group.
   - Licensed-state edits: self only for agents, downline only for leaders; invalid codes rejected; resident `state` unaffected.

### Frontend (`team.tsx` plus new components)

1. **Date button plus range calendar** (new component, for example `TeamDateSheet`):
   - "Month to date" (default) and a month calendar where tapping two days selects a range; one tap twice is a single day.
   - Previous/next month arrows; next is disabled at the current month, and future days are disabled.
   - Persist the choice per viewer the way `usePersistedPeriod` does, or reset to month to date on every open (ask Linnzi).
   - Handle the 6 AM Detroit sales-day boundary by using the server's `sales_day`, never the device date.
   - Reuse the same component in `AgentDayDetail` (7b.8).
2. **Team dashboard row (7a.4)** at the top: the viewer's team by SA level, Daily / Weekly / Monthly, compact.
3. **Filter controls (7a.2):** a dropdown (All / Rookies / Veterans) beside the metric buttons; for `levelNum(role) >= LEADER_MIN`, a selector for SA Teams / GA Teams (MGA Teams where the viewer is an RGA or admin). MY TEAM / REPORTS TO ME stays. The "Tenure not set" people appear under All only; how to keep the nudge to set tenure is open (ask).
4. **One list** ordered by own Gross ALP.
   - The rank number is `overall_rank`.
   - The rookie **R** badge stays, and a small LEADER tag replaces the separate Leaders board.
   - People at $0 are unranked ("—") at the bottom.
5. **Metric buttons:** ALP, Sales, Close Ratio, Avg Deal. No Net ALP anywhere on the tab. Rank numbers never change when the sort changes; they are always the Gross ALP rank, matching the Platinum Wall.
6. **Team views:** one line per team with totals, and per-category best/worst call-outs.
7. **Search** stays and applies to the current view.
8. **Upline card:** remove "· CONTACT ONLY".
9. **Missing Tonight:** a slim one-line bar, same `canEnter` gating, still opens `/missing`.
10. **Office headings** stay for viewers who reach more than one office (MJ, cross-office MGAs).
11. **Licensed states (7b.9):** a multi-select state picker on the agent's own profile (More tab) and on the contact card for people in the viewer's downline; the list shows on the card and in the team dashboard row.
12. **Labels (7b.6):** Show Ratio and Close Ratio across the agent card, Company Health and the tour.
13. **Tour:** update `tourSteps.ts` and the public `/tour` page. Anchors `team-weeks` and `team-roster` move; add one for the dropdown and the team selector.
14. **Update CLAUDE.md** (the Team tab section) with the new rules and the owner decision date.

### Rollout

1. The backend PR adds new fields and routes (additive only, so old builds are unaffected) and merges first. That is safe because nothing old breaks.
2. The frontend OTA consumes them.
3. A later cleanup removes `rank` / `leaderboard_group` / `week_start` once the fleet is on the new build (check EAS update adoption first).

---

## 5. Real data for sanity checks (MJ RGA, month to date 9/1 to 9/24, pulled 9/24)

- **Top of the combined list:**
  1. Awni Shuaib $47,194 (Agent, vet)
  2. Henry Long $45,732 (SA, 0 sales, see 2e.8)
  3. Adam Almassudi $19,874
  4. Snoor Qaradaghi $18,333 (SA)
  5. Jeannieliza Solis $16,767 (GA)
  6. Adam Youssef $15,355 (SA, 0 sales)
  7. Sajad Aljanaby $12,869
  8. Termaine Hudson $12,840 (rookie)
  9. Kyle Stikeleather $9,086 (rookie)
  10. Ali Eltanoukhi $8,863 (SA)
- **SA teams** (leader plus everyone under):

  | SA | Team ALP | Sales | People |
  | --- | --- | --- | --- |
  | Henry Long | $102,020 | 31 | 5 |
  | Maher Altairi | $32,714 | 25 | 5 |
  | Snoor Qaradaghi | $28,254 | 20 | 6 |
  | Ali Eltanoukhi | $22,804 | 15 | 3 |
  | Adam Youssef | $19,609 | 1 | 5 |
  | Aleskander Murshed | $1,714 | 2 | 2 |

- **GA teams:**

  | GA | Team ALP | Sales | People |
  | --- | --- | --- | --- |
  | Ali Musa | $207,115 | 94 | 29 |
  | Jeannieliza Solis | $19,147 | 4 | 4 |

- **MGA teams:** none in MJ RGA.
- **9/16 single day, MJ RGA:** Awni Shuaib $5,620 · Sajad Aljanaby $4,622 · Snoor Qaradaghi $1,341 · Christine Demaras $1,065.
- These totals were computed from active profiles only. The server also counts archived members' production; expect small differences.

---

## 6. Other open items from the project

- **PR #159** needs a merge and an OTA.
- **Streak and correction decisions** listed in project memory are still unanswered:
  - whether proxy entries extend streaks;
  - whether a correction repairs a streak;
  - whether a correction re-triggers the Player's Club check.
- **`package-lock.json`** was added by accident (the frontend uses yarn). Clean it up.
- **The feedback dashboard** still lives on OneDrive.

---

## 7. Linnzi's additional changes (added 2026-09-24, from MJ's written notes and voice memo)

These are owner decisions. Where they conflict with sections 2b, 2c or 4, **this section wins**; adjust the plan and the design canvas to match before building.

### 7a. Decisions that change the plan above

1. **ALP only; Net ALP disappears.** MJ's note and memo: remove Gross and Net, show one "ALP". Linnzi confirmed Gross and Net are the same across the boards. The value shown is Gross ALP, labelled **ALP**. Net ALP leaves the sort options (section 4, frontend 4), the row (the Net line under Gross in `renderRow`), and any other Team tab surface. Rank stays on Gross ALP, as before.
2. **Filter controls (replaces 2b.9's PEOPLE | TEAMS switch).**
   - A **dropdown** defaulting to **All**, with **All / Rookies / Veterans**. MJ's reasoning: the tenure filter is used far less than the metric buttons, so it should take less room.
   - For **leaders only**, add a **tab or selector** for seeing the other **SA teams and GA teams in their office** (the team views from 2b.4). Agents do not get this control.
   - The metric buttons (ALP, Sales, Close Ratio, Avg Deal) stay as visible buttons at the top.
3. **Date control is a range picker (replaces 2b.8's single-day calendar).** Leaders especially, but agents too, pick **any date range** on a calendar (for example one week). Default is still month to date. This answers 2e.3 and 2e.4: a reporting week or a whole past month is just a range the person selects, so no separate "This week" or "All of August" options are required.
4. **The Team tab opens on a team dashboard row, then the list (per MJ; Linnzi agrees).** At the top, a compact dashboard for the viewer's team **broken down by SA level**, with Daily / Weekly / Monthly, and showing each person's **licensed states** (MJ's "exact states"; see 7b.9). Below it, the agent list with its breakdown and the selectors from 7a.2. This is smaller than MJ's original "full dashboard first, list behind a button" ask: it is one row, not a separate screen, and the list stays on the same screen.
5. **Category comparison, MJ's version (extends 2b.4 and section 4, backend 3).** The team views show **which sub-teams excel in each category and which bring it down**, not only a total line. MGAs see it by GA team, GAs by SA team, SAs by individual agent. Categories are the metrics the tab already carries (ALP, sales, close ratio, show ratio, average deal); best and worst are called out per category.

### 7b. Other changes from MJ's notes (same release if practical)

6. **Rename labels:** "Sit Rate" becomes **"Show Ratio"**; "Close" / "Close %" / "Close Rate" becomes **"Close Ratio"**. Surfaces: `AgentDayDetail.tsx`, `AgentHistory.tsx`, `CoachingTips.tsx`, `vault.tsx` (CLOSE RATE KPI and chart title), `tourSteps.ts` and the public `/tour` page. Formulas are unchanged (`metrics.close_rate`, `metrics.show_rate`).
7. **Archived people never show under "Tenure Not Set".** `_leaderboard_group()` (`server.py` ~L151) reads only `is_rookie` and ignores `archived`, so a removed person with no tenure lands in that group. `PlatinumWall.tsx` has a "TOP 3 — TENURE NOT SET" section with the same exposure. With the single list (2b.2) the group goes away on the Team tab, but the wall still needs the guard.
8. **"What they submitted on a specific day" for every manager level.** `GET /api/agents/{id}/day` already uses `team_scope_agent_ids`, so SA, GA, MGA and RGA reach their downline. Verify on a real SA and GA login what MJ saw; if it works, this is done. Change the single "Pick a date" to the same calendar range control as 7a.3 (the route takes one `sales_day` today, so it needs a range or a per-day loop).
9. **Licensed states ("Dropdown" in the office's terminology; Linnzi, 2026-09-24).** When MJ writes "dropdown" he means the list of **states an agent is licensed to sell in**. Agents record their own licensed states; managers edit them for anyone in their hierarchy. This is a **new list field** (for example `licensed_states: ["MI", "OH"]`), not the existing single `state` field, which is the resident state used by the WAR-parity export and stays as it is. Add a self-service path and a downline-scoped manager path following the `set-tenure` pattern, audit-logged the same way, and surface the list on the agent card and in the team dashboard row (7a.4).
10. **Shoutouts move to badge notifications.** First deal, Player's Club, streak and Platinum Rule shoutouts become push/badge notifications. The types are already generated server-side and `send_expo_push` exists, so this is routing, not new logic. The Shoutouts tab itself is to be replaced by a "ChatAI" (see 7c).
11. **Release announcements.** When an update ships, notify users of the new features. No SMS provider exists in the codebase; push does. See 7c.

### 7c. Still open (ask Linnzi or MJ before building these)

- **"A different way to do the correction"** in the memo, said right after removing Gross and Net: what correction does this refer to?
- **ChatAI**: what should it do, and is it part of this redesign or a separate project? Nothing in the codebase resembles it today; treat as out of scope for the Team tab PR unless told otherwise.
- **Release announcements**: real SMS (new provider, new cost) or push notifications?
- **"What does Reports to Me breakdown"**: REPORTS TO ME filters to rows marked `in_my_downline` (direct downline), MY TEAM is the wider scope. Confirm whether MJ wants a change or just clearer copy.
- **"Coaching Toolkit Update"**: `CoachingTips.tsx` is static text. What update does he want?
- **Which build showed MJ a dropdown on Gross ALP?** `main` has no dropdown on the sort bar; it may be the local `feat/universal-dashboard` branch or a TestFlight build.
- The section 2e items not answered above: 2e.1 (who sees what), 2e.2 (tapping a team line), 2e.5 (team total definition), 2e.6 (MJ in company view), 2e.7 (screenshot reading), 2e.8 (0-sales data anomaly).

---

## 8. Build order (Linnzi, 2026-09-24): start now vs. after the MJ meeting

Linnzi meets MJ on 2026-09-25 at 5 PM with the open questions (the "Questions for MJ" doc in her artifacts). Work is split so the decided pieces start first.

**Start now (no open question):** merge PR #159 and ship its OTA; remove `package-lock.json`; label renames (7b.6); archived-never-in-Tenure-Not-Set (7b.7); ALP only, Net ALP removed (7a.1); verify the specific-day view on SA and GA logins (7b.8); `licensed_states` field, endpoints and picker, display only (7b.9); date range picker on `/api/team` and `/api/agents/{id}/day` with the calendar sheet (7a.3); single ranked list with `overall_rank` and the All / Rookies / Veterans dropdown (7a.2, 2b.2, 2b.5); shoutouts as push notifications with the tab left in place (7b.10).

**After the meeting:** SA / GA / MGA team views with totals and per-category best/worst (2b.4, 7a.5, 2e.1, 2e.2, 2e.5); the team dashboard row (7a.4) and any licensed-states filter; the leader-only team selector (7a.2); anything tied to the "correction" remark; Reports to Me and Coaching Toolkit changes; ChatAI and the Shoutouts tab removal; release announcements; the zero-sales data fix (2e.8).

**Linnzi's answers (2026-09-24):** the layout follows MJ's notes rather than the 2c screenshot reading, so the upline card, Missing Tonight card and search bar stay as they are for now; the date picker resets to month to date on every open; people with no tenure get a small SET TENURE badge on their row and their nearest SA or GA upline gets one consolidated daily push (with the 06:30 morning job) until it is set; "Close Ratio" replaces "Close %" / "Close Rate" everywhere.

Ship the start-now work as its own backend PR and OTA. The after-meeting work is additive on top of it (new route for team views, new summary block), so nothing built now has to be redone.
