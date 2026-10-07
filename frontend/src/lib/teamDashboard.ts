// The Team tab's dashboard row (owner: MJ 2026-09-25; Linnzi 2026-09-26 and
// 2026-09-29): the viewer's own scope by SA team on Daily / Weekly / Monthly,
// with licensed states shown and usable as a filter. Shapes mirror
// GET /api/team/dashboard in backend/server.py.
import { Period } from '../components/PeriodSelector';

export interface DashCell { gross_alp: number; sales: number; sits: number }
export interface DashTotals extends DashCell { close_ratio: number }

export interface DashPerson {
  agent_id: string;
  name: string;
  role?: string;
  io_role?: string;
}

export interface DashMember extends DashPerson {
  licensed_states: string[];
  daily: DashCell;
  weekly: DashCell;
  monthly: DashCell;
}

export interface DashTeam {
  leader: DashPerson | null;
  head_count: number;
  totals: Record<Period, DashTotals>;
  members: DashMember[];
}

export interface DashboardResponse {
  state: string | null;
  available_states: string[];
  periods: Record<Period, { start_day: string; end_day: string }>;
  total: Record<Period, DashTotals>;
  teams: DashTeam[];
}

/** The request path; the state is sent as its two-letter code or not at all. */
export function dashboardPath(state: string | null): string {
  return state ? `/api/team/dashboard?state=${encodeURIComponent(state)}` : '/api/team/dashboard';
}

/** What the empty list says when a state filter leaves nobody. */
export function noOneLicensedText(state: string): string {
  return `Nobody on your teams is licensed in ${state}.`;
}
