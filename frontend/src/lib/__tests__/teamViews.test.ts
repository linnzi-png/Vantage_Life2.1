// The pure rules behind the Team tab's team views. No React, no network.
import {
  BranchLine, CATEGORIES, branchesPath, formatMoney, lineSortField, membersOf, namesOf, sortLines,
} from '../teamViews';

const line = (id: string, name: string, over: Partial<BranchLine> = {}): BranchLine => ({
  agent_id: id, name, io_role: 'GA', role: 'level_2', phone: '', email: '', office: 'MCM',
  team_gross_alp: 1000, team_sales: 4, team_sits: 8, team_refs: 2, head_count: 3, close_ratio: 50,
  refs_per_sit: 0.25, show_ratio: 60, avg_alp: 250, team_rank: 1, in_my_downline: true, member_ids: [],
  ...over,
});

describe('formatMoney', () => {
  it('rounds to whole dollars with thousands separators and never prints NaN', () => {
    expect(formatMoney(10499.6)).toBe('$10,500');
    expect(formatMoney(0)).toBe('$0');
    expect(formatMoney(undefined)).toBe('$0');
    expect(formatMoney(null)).toBe('$0');
  });
});

describe('CATEGORIES', () => {
  it('are the four categories in the order they are called out', () => {
    expect(CATEGORIES.map((c) => c.key)).toEqual(['alp', 'refs_per_sit', 'show_ratio', 'avg_alp']);
  });
  it('format each value the way it is read', () => {
    const f = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.format]));
    expect(f.alp(1500)).toBe('$1,500');
    expect(f.refs_per_sit(1.5)).toBe('1.50');
    expect(f.show_ratio(66.666)).toBe('66.7%');
    expect(f.avg_alp(449.6)).toBe('$450');
    expect(f.refs_per_sit(NaN)).toBe('0.00');
  });
});

describe('sorting', () => {
  it('maps each metric button to the team figure that means the same thing', () => {
    expect(lineSortField('gross_alp')).toBe('team_gross_alp');
    expect(lineSortField('sales')).toBe('team_sales');
    expect(lineSortField('close_ratio')).toBe('close_ratio');
    expect(lineSortField('avg_deal')).toBe('avg_alp');
    expect(lineSortField('something_else')).toBe('team_gross_alp');
  });

  it('puts the highest first, breaks a tie by name and leaves the input alone', () => {
    const a = line('A', 'Zed', { team_sales: 5 });
    const b = line('B', 'Amy', { team_sales: 5 });
    const c = line('C', 'Bob', { team_sales: 9 });
    const input = [a, b, c];
    expect(sortLines(input, 'sales').map((l) => l.agent_id)).toEqual(['C', 'B', 'A']);
    expect(input.map((l) => l.agent_id)).toEqual(['A', 'B', 'C']);
  });

  it('treats a missing figure as zero rather than throwing', () => {
    const odd = line('A', 'Amy', { team_sales: undefined as unknown as number });
    expect(sortLines([odd, line('B', 'Bob', { team_sales: 1 })], 'sales').map((l) => l.agent_id)).toEqual(['B', 'A']);
  });
});

describe('branchesPath', () => {
  it('asks month to date with no range', () => {
    expect(branchesPath('ga', { mode: 'mtd' })).toBe('/api/team/branches?tier=ga');
  });
  it('carries a chosen range', () => {
    expect(branchesPath('sa', { mode: 'range', start: '2026-09-10', end: '2026-09-12' }))
      .toBe('/api/team/branches?tier=sa&start_day=2026-09-10&end_day=2026-09-12');
  });
  it('falls back to month to date for a range with a missing bound', () => {
    expect(branchesPath('mga', { mode: 'range', start: '2026-09-10' })).toBe('/api/team/branches?tier=mga');
  });
});

describe('membersOf', () => {
  const rows = [
    { agent_id: 'GA_1', gross_alp: 100 },
    { agent_id: 'AG_1', gross_alp: 300 },
    { agent_id: 'AG_4', gross_alp: 500 },
    { agent_id: 'OTHER', gross_alp: 9000 },
  ];

  it('lists the leader first, then the members by Gross ALP, and no one else', () => {
    const l = line('GA_1', 'Ga One', { member_ids: ['AG_1', 'AG_4'] });
    expect(membersOf(l, rows).map((r) => r.agent_id)).toEqual(['GA_1', 'AG_4', 'AG_1']);
  });

  it('skips a member the board did not return, and works with no leader row', () => {
    const l = line('GA_9', 'Ga Nine', { member_ids: ['AG_1', 'GONE'] });
    expect(membersOf(l, rows).map((r) => r.agent_id)).toEqual(['AG_1']);
  });

  it('is empty for a team that is a total and nothing more', () => {
    const l = line('GA_3', 'Ga Three', { in_my_downline: false, member_ids: [] });
    expect(membersOf(l, rows)).toEqual([]);
  });
});

describe('namesOf', () => {
  it('lists every tied team', () => {
    expect(namesOf([
      { agent_id: 'A', name: 'Amy', io_role: 'SA', value: 5 },
      { agent_id: 'B', name: 'Bob', io_role: 'SA', value: 5 },
    ])).toBe('Amy, Bob');
    expect(namesOf([])).toBe('');
  });
});
