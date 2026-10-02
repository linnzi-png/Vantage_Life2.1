// The Team tab's scope chips (owner, 2026-10-01): REPORTS TO ME is now MY
// DIRECT REPORTS and filters exactly as before, and one line under the chips
// says what the two mean. The chips are not a component of their own, so this
// mounts the screen itself (app/(tabs)/team.tsx); testMatch only looks under
// src/, which is why the file lives here.
import React from 'react';
import { render, fireEvent, screen } from '@testing-library/react-native';
import TeamScreen from '../../../app/(tabs)/team';
import { api, useAuth, Role } from '../../lib/auth';
import { useTour } from '../../lib/tour';

jest.mock('../../lib/auth', () => {
  const actual = jest.requireActual<typeof import('../../lib/auth')>('../../lib/auth');
  return { ...actual, api: jest.fn(), useAuth: jest.fn() };
});
jest.mock('../../lib/tour', () => ({ useTour: jest.fn() }));

const mockedApi = jest.mocked(api);
const mockedUseAuth = jest.mocked(useAuth);
const mockedUseTour = jest.mocked(useTour);

type AuthShape = ReturnType<typeof useAuth>;
type TourShape = ReturnType<typeof useTour>;

// The exact line the owner wrote; a reworded helper should fail here.
const HELPER = 'My Team is everyone under you. My Direct Reports is only the people who report straight to you.';

function authAs(role: Role, agentId: string): AuthShape {
  return {
    user: { user_id: 'u_me', email: 'me@example.com', name: 'Me Leader', role, agent_id: agentId },
    agent: { agent_id: agentId, name: 'Me Leader', office: 'MCM', role },
    roleLabel: 'GA',
    loading: false,
    reload: jest.fn(async () => {}),
    signInDemo: jest.fn(async () => {}),
    signInApple: jest.fn(async () => {}),
    signInAuth0: jest.fn(async () => {}),
    signOut: jest.fn(async () => {}),
    deleteAccount: jest.fn(async () => {}),
    switchRole: jest.fn(async () => {}),
    setViewMode: jest.fn(async () => {}),
    markTourCompleted: jest.fn(async () => {}),
    accountBusy: false,
  };
}

// The tour anchors on this screen only register their views.
function tourIdle(): TourShape {
  return {
    active: false,
    deciding: false,
    steps: [],
    index: 0,
    start: jest.fn(),
    next: jest.fn(),
    back: jest.fn(),
    skip: jest.fn(),
    finish: jest.fn(),
    cancel: jest.fn(),
    registerAnchor: jest.fn(),
    getAnchor: jest.fn(() => null),
  };
}

// One row of GET /api/team. in_my_downline is the server's answer to "is this
// person under me, as opposed to elsewhere in my office?".
function member(agentId: string, name: string, over: Record<string, unknown> = {}) {
  return {
    agent_id: agentId, name, office: 'MCM', role: 'level_1', io_role: 'Agent',
    phone: '', email: '', is_rookie: false, archived: false,
    gross_alp: 1000, net_alp: 900, sits: 4, sales: 2, close_ratio: 50, avg_deal: 500,
    alerts: [], in_my_downline: true, overall_rank: 1, overall_rank_of: 3,
    ...over,
  };
}

function serve(team: ReturnType<typeof member>[]) {
  mockedApi.mockImplementation(async (path: string) => {
    if (path === '/api/team') return { team, uplines: [], sales_day: '2026-10-01' };
    if (path === '/api/nominations?status=threshold_met') return { nominations: [] };
    throw new Error(`unexpected ${path}`);
  });
}

const ME = member('AG_ME', 'Me Leader', { role: 'level_2', io_role: 'GA' });
const DOWNLINE = member('AG_DOWN', 'Dana Downline');
const OFFICE_PEER = member('AG_PEER', 'Pat Peer', { in_my_downline: false });

beforeEach(() => {
  mockedApi.mockReset();
  mockedUseAuth.mockReturnValue(authAs('level_2', 'AG_ME'));
  mockedUseTour.mockReturnValue(tourIdle());
});

describe('Team tab scope chips', () => {
  it('names the chips MY TEAM and MY DIRECT REPORTS and explains them in one line', async () => {
    serve([ME, DOWNLINE, OFFICE_PEER]);
    await render(<TeamScreen />);
    expect(await screen.findByText('MY DIRECT REPORTS')).toBeTruthy();
    expect(screen.getByText('MY TEAM')).toBeTruthy();
    expect(screen.getByText(HELPER)).toBeTruthy();
    // The old label is gone everywhere on the screen.
    expect(screen.queryByText(/reports to me/i)).toBeNull();
  });

  it('shows neither the chips nor the helper when nobody is in the caller\'s downline', async () => {
    serve([ME, OFFICE_PEER]);
    await render(<TeamScreen />);
    await screen.findByTestId('team-row-AG_PEER');
    expect(screen.queryByTestId('team-scope-mine')).toBeNull();
    expect(screen.queryByText('MY DIRECT REPORTS')).toBeNull();
    expect(screen.queryByText(HELPER)).toBeNull();
  });

  it('still filters on MY DIRECT REPORTS exactly as REPORTS TO ME did, and MY TEAM brings the rest back', async () => {
    serve([ME, DOWNLINE, OFFICE_PEER]);
    await render(<TeamScreen />);
    await screen.findByTestId('team-row-AG_PEER');

    await fireEvent.press(screen.getByTestId('team-scope-mine'));
    expect(screen.queryByTestId('team-row-AG_PEER')).toBeNull();
    expect(screen.getByTestId('team-row-AG_DOWN')).toBeTruthy();
    expect(screen.getByTestId('team-row-AG_ME')).toBeTruthy();
    expect(screen.getByText(HELPER)).toBeTruthy();

    await fireEvent.press(screen.getByTestId('team-scope-team'));
    expect(screen.getByTestId('team-row-AG_PEER')).toBeTruthy();
    expect(screen.getByTestId('team-row-AG_DOWN')).toBeTruthy();
  });
});
