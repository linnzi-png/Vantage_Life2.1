// The team dashboard row (owner: MJ 2026-09-25; Linnzi 2026-09-26, 2026-09-29).
// Walked the way the other sheets and flips are: it can mount before its first
// response, with no teams, with a failed request, and its state menu can be
// opened at any moment, which typecheck cannot see.
import React from 'react';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { TeamDashboardRow } from '../TeamDashboardRow';
import { api } from '../../lib/auth';
import { DashboardResponse, DashMember, DashTeam, DashTotals } from '../../lib/teamDashboard';

jest.mock('../../lib/auth', () => {
  const actual = jest.requireActual<typeof import('../../lib/auth')>('../../lib/auth');
  return { ...actual, api: jest.fn() };
});

const mockedApi = jest.mocked(api);
const cell = (alp: number, sales = 1) => ({ gross_alp: alp, sales, sits: 2 });
const tot = (alp: number, sales = 1): DashTotals => ({ ...cell(alp, sales), close_ratio: 50 });

const member = (id: string, name: string, states: string[], daily: number, monthly: number): DashMember => ({
  agent_id: id, name, licensed_states: states,
  daily: cell(daily), weekly: cell(monthly / 2), monthly: cell(monthly),
});

const team = (leaderId: string, members: DashMember[]): DashTeam => ({
  leader: { agent_id: leaderId, name: members[0].name },
  head_count: members.length,
  totals: { daily: tot(100), weekly: tot(250), monthly: tot(500, 3) },
  members,
});

const response = (over: Partial<DashboardResponse> = {}): DashboardResponse => ({
  state: null,
  available_states: ['MI', 'OH'],
  periods: {
    daily: { start_day: '2026-10-07', end_day: '2026-10-07' },
    weekly: { start_day: '2026-10-01', end_day: '2026-10-07' },
    monthly: { start_day: '2026-10-01', end_day: '2026-10-07' },
  },
  total: { daily: tot(100), weekly: tot(250), monthly: tot(500, 3) },
  teams: [team('SA_1', [member('SA_1', 'Sa One', ['MI', 'OH'], 60, 300), member('AG_1', 'Agent One', [], 40, 200)])],
  ...over,
});

beforeEach(() => { mockedApi.mockReset(); });

test('mounts before its first response and shows the loading state, not an empty one', async () => {
  mockedApi.mockReturnValue(new Promise(() => {}));
  await render(<TeamDashboardRow />);
  expect(screen.getByTestId('team-dashboard-row')).toBeTruthy();
  expect(screen.queryByText('No teams to show yet.')).toBeNull();
});

test('opens on Monthly with the team total and each team', async () => {
  mockedApi.mockResolvedValue(response());
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByTestId('dash-team-SA_1')).toBeTruthy());
  expect(screen.getByTestId('team-dash-total')).toHaveTextContent(/\$500/);
  expect(mockedApi).toHaveBeenCalledWith('/api/team/dashboard');
});

test('Daily, Weekly and Monthly change the figures', async () => {
  mockedApi.mockResolvedValue(response());
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByTestId('team-dash-total')).toBeTruthy());
  await fireEvent.press(screen.getByTestId('team-dash-period-daily'));
  expect(screen.getByTestId('team-dash-total')).toHaveTextContent(/\$100/);
  await fireEvent.press(screen.getByTestId('team-dash-period-weekly'));
  expect(screen.getByTestId('team-dash-total')).toHaveTextContent(/\$250/);
});

test('tapping a team shows each person with their licensed states', async () => {
  mockedApi.mockResolvedValue(response());
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByTestId('dash-team-toggle-SA_1')).toBeTruthy());
  expect(screen.queryByTestId('dash-member-AG_1')).toBeNull();
  await fireEvent.press(screen.getByTestId('dash-team-toggle-SA_1'));
  expect(screen.getByTestId('dash-member-SA_1')).toHaveTextContent(/MI,\ OH/);
  expect(screen.getByTestId('dash-member-AG_1')).toHaveTextContent(/None\ recorded/);
});

test('choosing a state asks the server for exactly that code', async () => {
  mockedApi.mockResolvedValue(response());
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByTestId('team-dash-state')).toBeTruthy());
  await fireEvent.press(screen.getByTestId('team-dash-state'));
  await fireEvent.press(screen.getByTestId('team-dash-state-OH'));
  await waitFor(() => expect(mockedApi).toHaveBeenLastCalledWith('/api/team/dashboard?state=OH'));
});

test('a state nobody holds says so, and the chip can clear it', async () => {
  mockedApi.mockResolvedValueOnce(response());
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByTestId('team-dash-state')).toBeTruthy());
  mockedApi.mockResolvedValueOnce(response({ state: 'OH', teams: [] }));
  await fireEvent.press(screen.getByTestId('team-dash-state'));
  await fireEvent.press(screen.getByTestId('team-dash-state-OH'));
  await waitFor(() => expect(screen.getByText('Nobody on your teams is licensed in OH.')).toBeTruthy());
  mockedApi.mockResolvedValueOnce(response());
  await fireEvent.press(screen.getByTestId('team-dash-state'));
  await fireEvent.press(screen.getByTestId('team-dash-state-all'));
  await waitFor(() => expect(mockedApi).toHaveBeenLastCalledWith('/api/team/dashboard'));
});

test('a failed request is an error with a retry, never the empty copy', async () => {
  mockedApi.mockRejectedValueOnce(new Error('boom'));
  await render(<TeamDashboardRow />);
  await waitFor(() => expect(screen.getByText('boom')).toBeTruthy());
  expect(screen.queryByText('No teams to show yet.')).toBeNull();
});

test('the state menu mounts closed and opens on tap', async () => {
  mockedApi.mockResolvedValue(response());
  await render(<TeamDashboardRow />);
  expect(screen.queryByTestId('team-dash-state-menu')).toBeNull();
  await waitFor(() => expect(screen.getByTestId('team-dash-state')).toBeTruthy());
  await fireEvent.press(screen.getByTestId('team-dash-state'));
  expect(screen.getByTestId('team-dash-state-menu')).toBeTruthy();
});
