// The team views (owner: MJ 2026-09-25; Linnzi 2026-09-26, 2026-09-29, 2026-10-02).
//
// Walked the way the dashboard's flip cards are: a view can mount before its
// first response, with no competitors, with no teams, and a card can be opened
// at any moment, which typecheck cannot see. The competitor backs are mounted
// from the first frame behind their fronts and hidden from the accessibility
// tree until the card is open, so queries on a hidden face pass
// includeHiddenElements.
import React from 'react';
import { Text } from 'react-native';
import { act, render, fireEvent, screen, waitFor, within } from '@testing-library/react-native';
import { TeamViews } from '../TeamViews';
import { api, roleTitle } from '../../lib/auth';
import {
  BestWorst, BranchLine, BranchSection, BranchesResponse, Competitor, TeamWindow,
} from '../../lib/teamViews';

jest.mock('../../lib/auth', () => {
  const actual = jest.requireActual<typeof import('../../lib/auth')>('../../lib/auth');
  return { ...actual, api: jest.fn() };
});

const mockedApi = jest.mocked(api);
const hidden = { includeHiddenElements: true };
const MTD: TeamWindow = { mode: 'mtd' };

const line = (id: string, name: string, over: Partial<BranchLine> = {}): BranchLine => ({
  agent_id: id, name, io_role: 'GA', role: 'level_2', phone: '', email: '', office: 'MCM',
  team_gross_alp: 1500, team_sales: 5, team_sits: 10, team_refs: 3, head_count: 5, close_ratio: 50,
  refs_per_sit: 0.3, show_ratio: 66.7, avg_alp: 300, team_rank: 1, in_my_downline: true, member_ids: [],
  ...over,
});

const entry = (id: string, name: string, value: number) => ({ agent_id: id, name, io_role: 'GA', value });

const bestWorst = (over: Partial<BestWorst> = {}): BestWorst => ({
  alp: { best: [entry('GA_1', 'Ga One', 1500)], worst: [entry('GA_3', 'Ga Three', 500)] },
  refs_per_sit: { best: [entry('GA_1', 'Ga One', 0.3)], worst: [] },
  show_ratio: { best: [entry('GA_1', 'Ga One', 66.7)], worst: [] },
  avg_alp: { best: [entry('GA_3', 'Ga Three', 500)], worst: [entry('GA_1', 'Ga One', 300)] },
  ...over,
});

const section = (office: string, lines: BranchLine[], bw: BestWorst = bestWorst()): BranchSection =>
  ({ office, lines, best_worst: bw });

const competitor = (id: string, name: string, alp: number, office = 'MCM'): Competitor =>
  ({ agent_id: id, name, io_role: 'GA', office, team_gross_alp: alp });

const response = (over: Partial<BranchesResponse> = {}): BranchesResponse => ({
  tier: 'ga', scope: 'office', start_day: '2026-10-01', end_day: '2026-10-02',
  offices: [section('MCM', [line('GA_1', 'Ga One'), line('GA_3', 'Ga Three', {
    team_gross_alp: 500, team_rank: 2, in_my_downline: false, member_ids: [], phone: '3135550142', email: 'ga3@example.com',
  })])],
  competitors: [],
  ...over,
});

const ROWS = [
  { agent_id: 'GA_1', gross_alp: 100 },
  { agent_id: 'AG_1', gross_alp: 300 },
];
const renderMember = (r: { agent_id: string }) => <Text key={r.agent_id} testID={`member-${r.agent_id}`}>{r.agent_id}</Text>;

type Props = Partial<React.ComponentProps<typeof TeamViews>>;
const view = (props: Props = {}) => (
  <TeamViews
    tier="ga" window={MTD} windowLabel="Month to date" sortKey="gross_alp"
    rows={ROWS} renderMember={renderMember} viewerRole="level_2"
    {...props}
  />
);

function serve(body: BranchesResponse) {
  mockedApi.mockImplementation(async (path: string) => {
    if (path.startsWith('/api/team/branches')) return body;
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => mockedApi.mockReset());

describe('loading, empty and failed', () => {
  it('mounts before the first response, then shows the teams', async () => {
    let resolve: (v: BranchesResponse) => void = () => {};
    mockedApi.mockImplementation(() => new Promise((r) => { resolve = r as typeof resolve; }));
    await render(view());
    expect(screen.queryByTestId('team-line-GA_1')).toBeNull();
    resolve(response());
    expect(await screen.findByTestId('team-line-GA_1')).toBeTruthy();
    expect(screen.getByTestId('team-line-GA_3')).toBeTruthy();
  });

  it('says so when the tier has no teams, instead of showing a blank board', async () => {
    serve(response({ offices: [], competitors: [] }));
    await render(view());
    expect(await screen.findByText('No ga teams in this window.')).toBeTruthy();
  });

  it('shows a failure as a failure, with a retry that asks again', async () => {
    mockedApi.mockRejectedValueOnce(new Error('Server error'));
    mockedApi.mockResolvedValue(response());
    await render(view());
    expect(await screen.findByText('Server error')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('team-views-load-retry'));
    expect(await screen.findByTestId('team-line-GA_1')).toBeTruthy();
    expect(mockedApi).toHaveBeenCalledTimes(2);
  });

  it('asks for the chosen tier and range', async () => {
    serve(response());
    await render(view({ tier: 'sa', window: { mode: 'range', start: '2026-09-10', end: '2026-09-12' } }));
    await screen.findByTestId('team-line-GA_1');
    expect(mockedApi).toHaveBeenCalledWith('/api/team/branches?tier=sa&start_day=2026-09-10&end_day=2026-09-12');
  });

  it('ignores a slow answer for a tier the caller has already left', async () => {
    const pending: Record<string, (v: BranchesResponse) => void> = {};
    mockedApi.mockImplementation((path: string) => new Promise((r) => { pending[path] = r as (v: BranchesResponse) => void; }));
    await render(view({ tier: 'sa' }));
    await screen.rerender(view({ tier: 'mga' }));
    pending['/api/team/branches?tier=mga'](response({ tier: 'mga', offices: [section('MCM', [line('MGA_1', 'Mga One')])] }));
    expect(await screen.findByTestId('team-line-MGA_1')).toBeTruthy();
    // The late answer lands inside act(), so its state update is applied before
    // anything is asserted; without that this test passed even with no guard.
    await act(async () => {
      pending['/api/team/branches?tier=sa'](response({ tier: 'sa', offices: [section('MCM', [line('SA_1', 'Sa One')])] }));
    });
    expect(mockedApi).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId('team-line-SA_1')).toBeNull();
    expect(screen.getByTestId('team-line-MGA_1')).toBeTruthy();
  });
});

describe('team lines', () => {
  it('print the team total and the ratios on the line', async () => {
    serve(response());
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    expect(screen.getAllByText('$1,500').length).toBeGreaterThan(0);
    const ga1 = within(screen.getByTestId('team-line-GA_1'));
    expect(ga1.getByText('5 sales · 50% close · 0.30 refs/sit')).toBeTruthy();
    expect(ga1.getByText('66.7% show · $300 avg ALP')).toBeTruthy();
    expect(ga1.getByText(`${roleTitle('GA', 'level_2')} · 5 people`)).toBeTruthy();
    expect(ga1.getByText('$1,500')).toBeTruthy();
    expect(ga1.getByText('TEAM ALP')).toBeTruthy();
  });

  it('say "person" for a team of one and show a dash for a team with nothing', async () => {
    serve(response({ offices: [section('MCM', [line('GA_9', 'Ga Nine', { head_count: 1, team_gross_alp: 0 })])] }));
    await render(view());
    await screen.findByTestId('team-line-GA_9');
    const ga9 = within(screen.getByTestId('team-line-GA_9'));
    expect(ga9.getByText(`${roleTitle('GA', 'level_2')} · 1 person`)).toBeTruthy();
    expect(ga9.getByText('—')).toBeTruthy();
  });

  it('follow the metric button chosen on the screen', async () => {
    const lines = [
      line('GA_1', 'Ga One', { team_gross_alp: 900, team_sales: 1 }),
      line('GA_3', 'Ga Three', { team_gross_alp: 100, team_sales: 9 }),
    ];
    serve(response({ offices: [section('MCM', lines)] }));
    await render(view({ sortKey: 'gross_alp' }));
    await screen.findByTestId('team-line-GA_1');
    const order = () => screen.getAllByTestId(/^team-line-GA_\d$/).map((n) => n.props.testID);
    expect(order()).toEqual(['team-line-GA_1', 'team-line-GA_3']);
    await screen.rerender(view({ sortKey: 'sales' }));
    expect(order()).toEqual(['team-line-GA_3', 'team-line-GA_1']);
  });

  it('name each office only when there is more than one', async () => {
    serve(response());
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    expect(screen.queryByText('MCM')).toBeNull();
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One')]), section('AMP', [line('GA_4', 'Ga Four', { office: 'AMP' })])] }));
    await screen.rerender(view({ refreshKey: 1 }));
    expect(await screen.findByText('AMP')).toBeTruthy();
    expect(screen.getByText('MCM')).toBeTruthy();
  });
});

describe('a team under the caller', () => {
  it('expands to its people and closes on a second tap', async () => {
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One', { member_ids: ['AG_1'] })])] }));
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    expect(screen.queryByTestId('team-line-members-GA_1')).toBeNull();
    await fireEvent.press(screen.getByTestId('team-line-GA_1'));
    expect(screen.getByTestId('team-line-members-GA_1')).toBeTruthy();
    // The leader, then the members, each drawn by the screen's own row renderer.
    expect(screen.getAllByTestId(/^member-/).map((n) => n.props.testID)).toEqual(['member-GA_1', 'member-AG_1']);
    await fireEvent.press(screen.getByTestId('team-line-GA_1'));
    expect(screen.queryByTestId('team-line-members-GA_1')).toBeNull();
  });

  it('opens one team at a time', async () => {
    serve(response({ offices: [section('MCM', [
      line('GA_1', 'Ga One', { member_ids: ['AG_1'] }),
      line('GA_2', 'Ga Two', { team_gross_alp: 400, team_rank: 2, member_ids: ['AG_1'] }),
    ])] }));
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    await fireEvent.press(screen.getByTestId('team-line-GA_1'));
    await fireEvent.press(screen.getByTestId('team-line-GA_2'));
    expect(screen.queryByTestId('team-line-members-GA_1')).toBeNull();
    expect(screen.getByTestId('team-line-members-GA_2')).toBeTruthy();
  });

  it('says so when none of its people have rows for the window', async () => {
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One', { member_ids: ['AG_9'] })])] }));
    await render(view({ rows: [] }));
    await screen.findByTestId('team-line-GA_1');
    await fireEvent.press(screen.getByTestId('team-line-GA_1'));
    expect(screen.getByText('No one on this team has numbers in this window.')).toBeTruthy();
  });

  it('closes when the window changes, because it is a different set of teams', async () => {
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One', { member_ids: ['AG_1'] })])] }));
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    await fireEvent.press(screen.getByTestId('team-line-GA_1'));
    expect(screen.getByTestId('team-line-members-GA_1')).toBeTruthy();
    await screen.rerender(view({ window: { mode: 'range', start: '2026-09-01', end: '2026-09-02' } }));
    await waitFor(() => expect(screen.queryByTestId('team-line-members-GA_1')).toBeNull());
  });
});

describe('a team outside the caller\'s downline', () => {
  it('opens contact details and nothing else: no people, no history', async () => {
    serve(response());
    await render(view());
    await screen.findByTestId('team-line-GA_3');
    await fireEvent.press(screen.getByTestId('team-line-GA_3'));
    expect((await screen.findAllByText('(313) 555-0142')).length).toBeGreaterThan(0);
    expect(screen.queryByTestId('team-line-members-GA_3')).toBeNull();
    // A contact card with no agent_id never asks for that person's history or day.
    expect(mockedApi.mock.calls.every(([p]) => String(p).startsWith('/api/team/branches'))).toBe(true);
  });
});

describe('best and worst', () => {
  it('names the best and worst team in each of the four categories', async () => {
    serve(response());
    await render(view());
    await screen.findByTestId('best-worst-alp');
    expect(screen.getByText('BEST Ga One · $1,500')).toBeTruthy();
    expect(screen.getByText('WORST Ga Three · $500')).toBeTruthy();
    for (const k of ['alp', 'refs_per_sit', 'show_ratio', 'avg_alp']) {
      expect(screen.getByTestId(`best-worst-${k}`)).toBeTruthy();
    }
    expect(screen.getByText('BEST Ga Three · $500')).toBeTruthy(); // average ALP is a different race
  });

  it('lists every tied team and shows a dash when everyone ties', async () => {
    const tied = bestWorst({
      alp: { best: [entry('A', 'Amy', 0), entry('B', 'Bob', 0)], worst: [] },
    });
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One')], tied)] }));
    await render(view());
    await screen.findByTestId('best-worst-alp');
    expect(screen.getByText('BEST Amy, Bob · $0')).toBeTruthy();
    expect(screen.getAllByText('WORST —').length).toBeGreaterThan(0);
  });

  it('mounts with a best / worst block that is missing a category', async () => {
    const partial = { alp: bestWorst().alp } as unknown as BestWorst;
    serve(response({ offices: [section('MCM', [line('GA_1', 'Ga One')], partial)] }));
    await render(view());
    expect(await screen.findByTestId('best-worst-show_ratio')).toBeTruthy();
  });
});

describe('competitor cards (mount empty, then open)', () => {
  const comps = [competitor('GA_3', 'Ga Three', 500), competitor('GA_5', 'Ga Five', 300)];

  it('shows no competition row until there are competitors, then fills in', async () => {
    serve(response({ competitors: [] }));
    await render(view());
    await screen.findByTestId('team-line-GA_1');
    expect(screen.queryByTestId('team-competitors')).toBeNull();
    serve(response({ competitors: comps }));
    await screen.rerender(view({ refreshKey: 1 }));
    expect(await screen.findByTestId('team-competitors')).toBeTruthy();
    expect(screen.getByText('YOUR COMPETITION · TOP 2 BY TEAM ALP')).toBeTruthy();
  });

  it('draws the back while it is still hidden behind the front', async () => {
    serve(response({ competitors: comps }));
    await render(view());
    await screen.findByTestId('competitor-GA_3');
    expect(screen.getAllByText('$500', hidden).length).toBeGreaterThan(0);
    expect(screen.getAllByText('TEAM ALP', hidden).length).toBeGreaterThan(0);
  });

  it('shows the team ALP and the window, and nothing else, when opened', async () => {
    serve(response({ competitors: comps }));
    await render(view({ windowLabel: 'Sep 1 – Sep 12' }));
    await screen.findByTestId('competitor-GA_3');
    await fireEvent.press(screen.getByTestId('competitor-GA_3-front'));
    expect(screen.getAllByText('Sep 1 – Sep 12', hidden).length).toBeGreaterThan(0);
    // No members, no contact, no ratios anywhere on a competitor.
    expect(screen.queryByTestId('team-line-members-GA_3')).toBeNull();
    expect(screen.queryByText('(313) 555-0142')).toBeNull();
  });

  it('closes again when its open back is tapped', async () => {
    serve(response({ competitors: comps }));
    await render(view());
    await screen.findByTestId('competitor-GA_3');
    await fireEvent.press(screen.getByTestId('competitor-GA_3-front'));
    await fireEvent.press(screen.getByTestId('competitor-GA_3-back'));
    expect(screen.getByTestId('competitor-GA_3-front')).toBeTruthy();
  });

  it('opens a second card by closing the first', async () => {
    serve(response({ competitors: comps }));
    await render(view());
    await screen.findByTestId('competitor-GA_3');
    await fireEvent.press(screen.getByTestId('competitor-GA_3-front'));
    await fireEvent.press(screen.getByTestId('competitor-GA_5-front'));
    // Only the card last tapped is open; the first one's front takes taps again.
    await fireEvent.press(screen.getByTestId('competitor-GA_3-front'));
    expect(screen.getByTestId('competitor-GA_5-front')).toBeTruthy();
  });

  it('survives a competitor with no figure yet', async () => {
    serve(response({ competitors: [{ ...competitor('GA_7', 'Ga Seven', 0), team_gross_alp: undefined as unknown as number }] }));
    await render(view());
    await screen.findByTestId('competitor-GA_7');
    await fireEvent.press(screen.getByTestId('competitor-GA_7-front'));
    expect(screen.getAllByText('$0', hidden).length).toBeGreaterThan(0);
  });
});
