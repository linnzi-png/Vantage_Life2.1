# Admin Panel & Tier Switcher — Operator Guide

Manage access levels from inside the app — no terminal, no scripts. Change someone's
tier, onboard a new person, or let a tester walk every level, all from the **More** tab.

Shipped in PR #32 (`feat/admin-panel`). Backend endpoints live in `backend/server.py`
behind `require_admin`; frontend is `frontend/app/admin.tsx` plus the switcher on the
More tab (`frontend/app/(tabs)/more.tsx`).

## Who sees what

- **Admin Panel** — appears in the **More** tab for admins only. Built-in admins
  (`linnzi@aoluxor.com`, `mj@aopremier.com`) always qualify; anyone else needs the
  `is_admin` flag. This is where you manage everyone.
- **"View As Tier" switcher** — a card on a person's **own** More tab, shown only if
  they have the `can_switch_role` flag. Lets a tester flip their own level without an admin.

Admin list is bootstrapped from the `ADMIN_EMAILS` env var
(defaults to `linnzi@aoluxor.com,mj@aopremier.com`).

## How to do each thing

### 1. Change someone's access level  *(you · Admin Panel)*
1. **More** tab → **Admin Panel** (shield icon).
2. Search for the person by name, email, or office.
3. Tap the tier: `L1` Agent · `L2` GA · `L3` MGA · `L4` RGA.
4. Confirm. Takes effect immediately — no sign-out required.

### 2. Add a new person / onboard  *(you · Admin Panel)*
1. Admin Panel → **Add Person**.
2. Enter **Name**, **Email** (their Google/Apple sign-in address), Phone, Office.
3. Pick **Access Tier** and **Display Title**, optionally search an **Upline**.
4. **Add to Roster**. Their first sign-in links to this record automatically.

### 3. Let a tester switch their own tier  *(you enable · they use)*
1. Have the tester **sign in once** so their account exists.
2. You: Admin Panel → find them → turn **Can switch role** ON.
3. A **View As Tier** card now appears on *their* More tab (`L1`–`L4`).
4. They tap a tier and instantly become that level — no sign-out. Test, tap next, repeat.

### 4. Remove it after testing  *(you · Admin Panel)*
1. Admin Panel → find the tester → turn **Can switch role** OFF (their card disappears).
2. Set their role back to their real tier (e.g. Timothy → `L2` GA).
3. Revoke any `is_admin` flag granted just for this.

All of this is flag-based — instant, and needs no new build or App Store release.

## Importing War Reports

**Admin Panel → Import War Reports.** Uploads weekly WAR spreadsheets straight into
production data — no terminal, no local MongoDB.

1. Name each file with the week's **Wednesday**: `2026-02-18_MJ_War_Report.xlsx`.
   The date drives which sales day each tab lands on, so a wrong date misdates the
   whole week. Non-Wednesday dates are rejected.
2. **Choose Files** — pick all of them at once. They upload in filename order, which
   is chronological; that ordering matters (see the overlap rule below).
3. Leave **Preview only (dry run)** ON for the first pass. It reports exactly what
   would change and writes nothing.
4. Review the summary, then turn dry run OFF and import for real.

### The nine-tab overlap rule

Each report has nine daily tabs (`Wed` → `Thurs (2)`) but reports are seven days
apart. So `Wed (2)`/`Thurs (2)` cover the same sales days as the *next* report's
`Wed`/`Thurs`. **The later file wins** — re-importing replaces the earlier
WAR-sourced entry for that (agent, day), which keeps the following week's
corrections instead of dropping them. This is why chronological order matters, and
why re-uploading the same file is safe: it updates in place rather than duplicating.

### What is never overwritten

Entries an agent submitted in the app (`source` other than `war_xlsx_import`) are
left untouched and reported as **protected**. A spreadsheet backfill can never
silently replace someone's own entry.

### Agents not on the roster

Their rows are **skipped** and listed by name with their MGA/GA, because an agent
created without an upline is invisible in every team rollup (`visible_agent_ids()`
walks `agent_profiles.upline_id`). Add them via **Add Person** with the correct
upline, then re-run the import. The **Create agents not on the roster** toggle
exists for bulk historical loads, but leaves those agents orphaned until you set
an upline.

## How it works (for maintainers)

- **Source of truth is `agent_profiles`.** Sign-in re-derives role/`agent_id` from
  `agent_profiles` by email on every login. So every role write updates **both**
  `agent_profiles` (survives the next login) **and** `users` (visible immediately).
- **Endpoints** (all `require_admin` except the self-switch):
  - `GET  /api/admin/people` — roster with `has_login`, `is_admin`, `can_switch_role`,
    `first_login_at`, `last_seen_at` (activity, refreshed at most every 10 minutes),
    plus a `summary { roster, signed_in }` powering the Login Scoreboard card
  - `POST /api/admin/set-role` — `{ agent_id, role }`
  - `POST /api/admin/add-person` — `{ name, email, phone?, office?, role, io_role?, upline_agent_id? }`
  - `POST /api/admin/set-flags` — `{ email, is_admin?, can_switch_role? }`
  - `POST /api/admin/import-war-report` — multipart: `file` (.xlsx), plus optional
    `week_start` (YYYY-MM-DD, defaults to the filename date), `dry_run`, `create_missing`.
    Returns per-file counts (`inserted`/`replaced`/`protected`/`skipped_unmatched`) and
    the `unmatched` agent list.
  - `POST /api/me/role` — self-service switch, gated by the caller's `can_switch_role`;
    changes the caller's **own** account only.
- `GET /api/auth/me` returns `is_admin` and `can_switch_role` so the UI knows what to show.
- Tests: `backend/tests/test_admin.py` (require_admin gating, people/set-role/add-person/set-flags,
  and `/api/me/role` invariants).

## Command-line equivalents (fallback only)

The panel replaces these, but they still exist for scripted/bulk use:

- `backend/create_users.py` — upsert the `USERS` list into the roster.
- `backend/set_test_role.py <email> <level_1..4>` — flip one person's tier.
- `backend/import_xlsx_war.py <files...>` — bulk WAR backfill. Shares its parsing with
  the upload endpoint via `backend/war_import.py`, so both apply the same column
  mapping and the same later-file-wins overlap rule. Requires direct MongoDB network
  access, so it will not run from a cloud container.

All require `MONGO_URL` (and `DB_NAME`, default `vantagelife`) in the environment.
