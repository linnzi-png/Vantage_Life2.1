// The producer card's "What they submitted" block: the exact path the
// APP Testing Crew hit on 2026-09-28. The card mounts with no sales day, the
// person taps the pill, the card asks the server for the current sales day,
// and only then does the calendar open. Every `api` call is mocked; nothing
// here touches the network.
import React from 'react';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { AgentDayDetail } from '../AgentDayDetail';
import { api } from '../../lib/auth';

jest.mock('../../lib/auth', () => {
  const actual = jest.requireActual<typeof import('../../lib/auth')>('../../lib/auth');
  return { ...actual, api: jest.fn() };
});

const mockedApi = jest.mocked(api);

const dayPayload = (over: Partial<{ sales_day: string; has_entries: boolean; gross_alp: number; sales: number }> = {}) => ({
  sales_day: over.sales_day ?? '2026-09-28',
  totals: { gross_alp: over.gross_alp ?? 0, sales: over.sales ?? 0, sits: 0, sets: 0, n1: 0 },
  close_rate: 0,
  show_rate: 0,
  alp_per_sale: 0,
  has_entries: over.has_entries ?? false,
  entry_count: over.has_entries ? 1 : 0,
});

beforeEach(() => { mockedApi.mockReset(); });

describe('AgentDayDetail', () => {
  it('mounts without a sales day and opens the calendar only after the server supplies one', async () => {
    mockedApi.mockResolvedValueOnce(dayPayload());
    await render(<AgentDayDetail agentId="a1" />);
    expect(screen.getByText('PICK A DAY OR RANGE')).toBeTruthy();
    expect(screen.queryByText('SEPTEMBER 2026')).toBeNull();

    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));

    await waitFor(() => expect(screen.getByText('SEPTEMBER 2026')).toBeTruthy());
    expect(mockedApi).toHaveBeenCalledWith('/api/agents/a1/day');
    expect(screen.getByTestId('team-date-2026-09-28')).toBeTruthy();
    expect(screen.getByTestId('team-date-2026-09-29')).toBeDisabled();
    // No "Month to date" row on the producer card — it has no default window.
    expect(screen.queryByTestId('team-date-mtd')).toBeNull();
  });

  it('asks for the picked range, labels the pill with it and shows the totals', async () => {
    mockedApi
      .mockResolvedValueOnce(dayPayload())
      .mockResolvedValueOnce(dayPayload({ has_entries: true, gross_alp: 1234, sales: 3 }));
    await render(<AgentDayDetail agentId="a1" />);
    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));
    await waitFor(() => expect(screen.getByText('SEPTEMBER 2026')).toBeTruthy());

    await fireEvent.press(screen.getByTestId('team-date-2026-09-14'));
    await fireEvent.press(screen.getByTestId('team-date-2026-09-20'));
    await fireEvent.press(screen.getByText('SHOW RANGE'));

    await waitFor(() => expect(screen.getByTestId('agent-day-result')).toBeTruthy());
    expect(mockedApi).toHaveBeenLastCalledWith('/api/agents/a1/day?start_day=2026-09-14&end_day=2026-09-20');
    expect(screen.getByText('SEP 14 – SEP 20')).toBeTruthy();
    expect(screen.getAllByText('$1,234').length).toBeGreaterThan(0);
  });

  it('re-reads the sales day on every open, so a card left open across 6 AM offers the new day', async () => {
    mockedApi
      .mockResolvedValueOnce(dayPayload({ sales_day: '2026-09-28' }))
      .mockResolvedValueOnce(dayPayload({ sales_day: '2026-09-29' }));
    await render(<AgentDayDetail agentId="a1" />);

    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));
    await waitFor(() => expect(screen.getByTestId('team-date-2026-09-29')).toBeDisabled());
    await fireEvent.press(screen.getByText('CANCEL'));

    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));
    await waitFor(() => expect(screen.getByTestId('team-date-2026-09-29')).toBeEnabled());
    expect(mockedApi).toHaveBeenCalledTimes(2);
  });

  it('leaves the pill usable when the sales-day request fails', async () => {
    mockedApi.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(dayPayload());
    await render(<AgentDayDetail agentId="a1" />);

    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));
    await waitFor(() => expect(screen.getByTestId('agent-day-picker-open')).toBeEnabled());
    expect(screen.queryByText('SEPTEMBER 2026')).toBeNull();

    await fireEvent.press(screen.getByTestId('agent-day-picker-open'));
    await waitFor(() => expect(screen.getByText('SEPTEMBER 2026')).toBeTruthy());
  });
});
