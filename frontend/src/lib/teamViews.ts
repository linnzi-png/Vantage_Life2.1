// Team views (owner: MJ 2026-09-25; Linnzi 2026-09-26, 2026-09-29, 2026-10-02):
// the types GET /api/team/branches returns and the pure helpers the Team tab
// builds on them. Nothing here touches React or the network, so every rule is
// testable on its own.
import type { Role } from './auth';

export type BranchTier = 'sa' | 'ga' | 'mga';
/** PEOPLE is the Team tab as it always was; the other three are team totals. */
export type TeamViewMode = 'people' | BranchTier;

export const VIEW_ORDER: TeamViewMode[] = ['people', 'sa', 'ga', 'mga'];
export const VIEW_LABEL: Record<TeamViewMode, string> = {
  people: 'PEOPLE', sa: 'SA TEAMS', ga: 'GA TEAMS', mga: 'MGA TEAMS',
};
/** The tier a team's leader holds, so a line is titled by tier and never guessed. */
export const TIER_ROLE: Record<BranchTier, Role> = { sa: 'level_sa', ga: 'level_2', mga: 'level_3' };

export type CategoryKey = 'alp' | 'refs_per_sit' | 'show_ratio' | 'avg_alp';

export function formatMoney(n: number | null | undefined): string {
  return `$${Math.round(Number(n) || 0).toLocaleString()}`;
}

/** The four best / worst categories, in the order they are called out. */
export const CATEGORIES: { key: CategoryKey; label: string; format: (v: number) => string }[] = [
  { key: 'alp', label: 'ALP', format: formatMoney },
  { key: 'refs_per_sit', label: 'REFS PER SIT', format: (v) => (Number(v) || 0).toFixed(2) },
  { key: 'show_ratio', label: 'SHOW RATIO', format: (v) => `${(Number(v) || 0).toFixed(1)}%` },
  { key: 'avg_alp', label: 'AVERAGE ALP', format: formatMoney },
];

export interface BranchLine {
  agent_id: string;
  name: string;
  io_role: string;
  role: string;
  phone: string;
  email: string;
  office: string;
  team_gross_alp: number;
  team_sales: number;
  team_sits: number;
  team_refs: number;
  head_count: number;
  close_ratio: number;
  refs_per_sit: number;
  show_ratio: number;
  avg_alp: number;
  team_rank: number;
  /** True for a team under the caller (or one the caller reaches whole). */
  in_my_downline: boolean;
  /** Filled only for a team under the caller; every other team is a total. */
  member_ids: string[];
}

export interface BestWorstEntry { agent_id: string; name: string; io_role: string; value: number }
export type BestWorst = Record<CategoryKey, { best: BestWorstEntry[]; worst: BestWorstEntry[] }>;

export interface BranchSection { office: string; lines: BranchLine[]; best_worst: BestWorst }

/** A peer of the caller's own tier: identity and one number, nothing else. */
export interface Competitor {
  agent_id: string; name: string; io_role: string; office: string; team_gross_alp: number;
}

export interface BranchesResponse {
  tier: BranchTier;
  scope: 'office' | 'company' | 'own';
  start_day: string;
  end_day: string;
  offices: BranchSection[];
  competitors: Competitor[];
}

/** The metric buttons stay buttons (decision 7); on a team line each one sorts by
 *  the team figure that means the same thing. Anything else falls back to ALP. */
export function lineSortField(sortKey: string): 'team_gross_alp' | 'team_sales' | 'close_ratio' | 'avg_alp' {
  switch (sortKey) {
    case 'sales': return 'team_sales';
    case 'close_ratio': return 'close_ratio';
    case 'avg_deal': return 'avg_alp';
    default: return 'team_gross_alp';
  }
}

/** Highest first on the chosen figure; a tie falls back to name so the order is stable. */
export function sortLines(lines: BranchLine[], sortKey: string): BranchLine[] {
  const field = lineSortField(sortKey);
  return [...lines].sort((a, b) =>
    (Number(b[field]) || 0) - (Number(a[field]) || 0) || a.name.localeCompare(b.name));
}

export interface TeamWindow { mode: 'mtd' | 'range'; start?: string; end?: string }

export function branchesPath(tier: BranchTier, win: TeamWindow): string {
  const range = win.mode === 'range' && win.start && win.end
    ? `&start_day=${win.start}&end_day=${win.end}`
    : '';
  return `/api/team/branches?tier=${tier}${range}`;
}

/** The people an expanded team shows: the leader first (their own production is
 *  in the total), then the members, each as the row /api/team already returned
 *  for the window. A member the board did not return is simply absent. */
export function membersOf<T extends { agent_id: string; gross_alp: number }>(line: BranchLine, rows: T[]): T[] {
  const byId = new Map(rows.map((r) => [r.agent_id, r]));
  const leader = byId.get(line.agent_id);
  const members = line.member_ids
    .map((id) => byId.get(id))
    .filter((r): r is T => !!r)
    .sort((a, b) => (Number(b.gross_alp) || 0) - (Number(a.gross_alp) || 0));
  return leader ? [leader, ...members] : members;
}

/** Names for a best / worst call-out; a tie lists every tied team. */
export function namesOf(entries: BestWorstEntry[]): string {
  return entries.map((e) => e.name).join(', ');
}
