// The text-message log in the Admin Panel's Announce section (batch 2, PR C):
// closed on mount, fetched only when opened, and an empty log says so.
import React from 'react';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { AnnouncePanel } from '../AnnouncePanel';
import { api } from '../../lib/auth';

jest.mock('../../lib/auth', () => {
  const actual = jest.requireActual<typeof import('../../lib/auth')>('../../lib/auth');
  return { ...actual, api: jest.fn() };
});

const mockedApi = jest.mocked(api);

function serve(smsLog: unknown[]) {
  mockedApi.mockImplementation(async (path: string) => {
    if (path === '/api/admin/offices') return { offices: [{ office: 'MCM', agents: 3 }] };
    if (path === '/api/announcements/sms-status') return { available: true };
    if (path === '/api/admin/announcements') return { announcements: [] };
    if (path === '/api/admin/sms-log') return { sms_log: smsLog };
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => mockedApi.mockReset());

async function openPanel() {
  await render(<AnnouncePanel />);
  await fireEvent.press(screen.getByTestId('announce-open'));
  await waitFor(() => expect(screen.getByTestId('announce-sms-log-toggle')).toBeTruthy());
}

describe('AnnouncePanel text message log', () => {
  it('does not fetch the log until it is opened', async () => {
    serve([]);
    await openPanel();
    expect(mockedApi).not.toHaveBeenCalledWith('/api/admin/sms-log');
    expect(screen.queryByTestId('announce-sms-log-0')).toBeNull();
  });

  it('shows who was texted, the outcome and any reason', async () => {
    serve([
      { announcement_id: 'ann_1', agent_id: 'AG_1', name: 'Agent One', office: 'MCM', to: '***0100', status: 'sent', reason: null, ts: '2026-10-01T15:00:00Z' },
      { announcement_id: 'ann_1', agent_id: 'AG_2', name: 'Agent Two', office: 'AMP', to: null, status: 'skipped', reason: 'phone does not normalise', ts: '2026-10-01T15:00:01Z' },
    ]);
    await openPanel();
    await fireEvent.press(screen.getByTestId('announce-sms-log-toggle'));
    await waitFor(() => expect(screen.getByTestId('announce-sms-log-1')).toBeTruthy());
    expect(screen.getByText(/Agent One.*\*\*\*0100/)).toBeTruthy();
    expect(screen.getByText('SENT')).toBeTruthy();
    expect(screen.getByText('SKIPPED')).toBeTruthy();
    expect(screen.getByText(/phone does not normalise/)).toBeTruthy();
  });

  it('says so when nothing has been sent', async () => {
    serve([]);
    await openPanel();
    await fireEvent.press(screen.getByTestId('announce-sms-log-toggle'));
    await waitFor(() => expect(screen.getByTestId('announce-sms-log-empty')).toBeTruthy());
  });
});
