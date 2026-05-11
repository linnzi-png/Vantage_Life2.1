# CLAUDE.md - VantageLife 2.1 (AO Premiere)

## Project Overview
Real-time sales tracking and victory culture platform for AO Globe Life - Vantage.
Mobile-first TypeScript/Node app deployed on Vercel. GitHub MCP: https://github-mcp-server-blond.vercel.app/api/mcp

## Tech Stack
- Language: TypeScript (strict mode)
- Runtime: Node.js
- Database: Supabase (PostgreSQL)
- Auth: Supabase Auth with 4-tier RBAC
- Deploy: Vercel (auto-deploy from main)
- Package manager: npm

## Architecture
- src/components/pages/ — Page components (NumbersEntry.jsx = primary entry point)
- src/components/ — Shared UI components
- src/lib/ — Utilities, Supabase client, metric helpers
- src/types/ — TypeScript type definitions
- src/hooks/ — Custom React hooks

## RBAC Hierarchy (4-tier - NEVER flatten or bypass)
1. Agent — enters their own metrics only
2. GA (General Agent) — sees their team rollup
3. MGA (Master General Agent) — sees GA-level rollups
4. RGA (Regional General Agent) — sees all MGA rollups

## The 14 Nightly Metrics (exact order - do not reorder)
1. Sets
2. Sits
3. Sales
4. OS Sits
5. OS Sales
6. N1  ← EXCLUDED FROM ALL CLOSE RATE MATH
7. Referrals
8. Ref Sits
9. Ref Sales
10. POS Sits
11. POS Sales
12. Vet Sits
13. Vet Sales
14. Gross ALP

## Business Logic (sacred - do not change without explicit instruction)
- Reporting cycle: 6:00 AM to 5:59 AM (not midnight-to-midnight)
- Wednesday 2:00 PM = weekly submission cutoff
- 9PM gates = nightly data lock
- "Midnight Miracle" = last-minute entry window before midnight gate
- Close Rate formula: Sales / (Sits - N1)  // N1 always excluded
- All metric calculations go in a dedicated utility file, never inline

## Current Focus
VantageLife 2.1 "Nightly Numbers" 14-metric mobile stepper. Wiring backend services.
Stale View bug previously resolved via hard-replace in src/components/pages/NumbersEntry.jsx.
PULSEFORMV2_ACTIVE label confirms correct version is live.

## Commands
- Dev: npm run dev
- Build: npm run build
- Type check: npm run typecheck (must pass before every commit)
- Deploy: Vercel auto-deploys from main

## Coding Conventions
- TypeScript strict mode. No any types. No type assertions.
- Named exports only. No default exports.
- Kebab-case files. PascalCase components.
- Every Close Rate calculation must include comment: // N1 excluded per business rule
- Never hardcode metric names - always reference the METRICS constant

## Forbidden Patterns
- NEVER include N1 in Close Rate or any aggregate calculation
- NEVER allow an Agent to see data above their RBAC tier
- NEVER change the 6AM cycle boundary without explicit instruction
- NEVER bypass the Wednesday 2PM cutoff gate
- NEVER commit directly to main - feature branches always
- NEVER hardcode metric names or tier labels

## Known Gotchas
- Stale View: NumbersEntry.jsx can cache stale version. Hard-replace if metrics appear wrong.
  Verify with PULSEFORMV2_ACTIVE label.
- N1 looks like a sales metric but is a write-off category. Audit every aggregation.
- Reporting cycle starts 6AM - all date range queries must account for this offset.
- Supabase real-time subscriptions can fire duplicate events - always debounce.

## AI Agent Notes
- Ask before modifying any business logic or calculation
- Run npm run typecheck after every non-trivial change; stop if it fails
- Read existing patterns in src/lib/ before proposing new architecture
- Create feature branches for all work; never commit directly to main
- When uncertain about tier permissions, enforce more restrictive access