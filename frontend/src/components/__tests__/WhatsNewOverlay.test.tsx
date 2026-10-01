// WHAT'S NEW (batch 2, PR B). Mounted from the root layout on every open, so
// the sequence that matters is: mount with auth loading, auth resolves, the
// tour decides, the unseen list arrives, the person taps through, each one
// is marked seen. Every api call is mocked.
import React from 'react';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import WhatsNewOverlay, { Announcement, WhatsNewDeck } from '../WhatsNewOverlay';
import { api, useAuth } from '../../lib/auth';
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

const ann = (id: string, title: string, cards = 2): Announcement => ({
  announcement_id: id,
  title,
  cards: Array.from({ length: cards }, (_, i) => ({ heading: `${title} card ${i + 1}`, body: `Body ${i + 1}` })),
  audience: { scope: 'agency' },
  created_at: '2026-09-30T00:00:00Z',
});

const auth = (over: Partial<{ loading: boolean; user: { user_id: string } | null }> = {}): AuthShape =>
  ({ loading: false, user: { user_id: 'u1' }, ...over } as unknown as AuthShape);
const tour = (active = false, deciding = false): TourShape => ({ active, deciding } as unknown as TourShape);

beforeEach(() => {
  mockedApi.mockReset();
  mockedUseTour.mockReturnValue(tour());
});

describe('WhatsNewOverlay', () => {
  it('shows nothing while auth loads, then nothing when the unseen list is empty', async () => {
    mockedUseAuth.mockReturnValue(auth({ loading: true, user: null }));
    await render(<WhatsNewOverlay />);
    expect(mockedApi).not.toHaveBeenCalled();
    expect(screen.queryByTestId('whats-new-overlay')).toBeNull();

    mockedUseAuth.mockReturnValue(auth());
    mockedApi.mockResolvedValueOnce({ announcements: [] });
    await screen.rerender(<WhatsNewOverlay />);
    await waitFor(() => expect(mockedApi).toHaveBeenCalledWith('/api/announcements/unseen'));
    expect(screen.queryByTestId('whats-new-overlay')).toBeNull();
  });

  it('waits for the tour to finish deciding and does not fetch while it is active', async () => {
    mockedUseAuth.mockReturnValue(auth());
    mockedUseTour.mockReturnValue(tour(false, true));
    await render(<WhatsNewOverlay />);
    expect(mockedApi).not.toHaveBeenCalled();
    mockedUseTour.mockReturnValue(tour(true, false));
    await screen.rerender(<WhatsNewOverlay />);
    expect(mockedApi).not.toHaveBeenCalled();
    mockedUseTour.mockReturnValue(tour(false, false));
    mockedApi.mockResolvedValueOnce({ announcements: [ann('a1', 'Date range')] });
    await screen.rerender(<WhatsNewOverlay />);
    await waitFor(() => expect(screen.getByTestId('whats-new-overlay')).toBeTruthy());
    expect(screen.getByText("WHAT'S NEW")).toBeTruthy();
    expect(screen.getByText('Date range')).toBeTruthy();
  });

  it('walks the cards, marks seen on DONE, then shows the next announcement and marks that seen on SKIP', async () => {
    mockedUseAuth.mockReturnValue(auth());
    mockedApi
      .mockResolvedValueOnce({ announcements: [ann('a1', 'First', 2), ann('a2', 'Second', 3)] })
      .mockResolvedValue({ ok: true });
    await render(<WhatsNewOverlay />);
    await waitFor(() => expect(screen.getByText('First')).toBeTruthy());
    expect(screen.getByText('First card 1')).toBeTruthy();
    expect(screen.queryByTestId('whats-new-back')).toBeNull();

    await fireEvent.press(screen.getByTestId('whats-new-next'));
    expect(screen.getByText('First card 2')).toBeTruthy();
    expect(screen.getByTestId('whats-new-back')).toBeTruthy();
    expect(screen.queryByTestId('whats-new-skip')).toBeNull(); // last card has DONE, no skip
    await fireEvent.press(screen.getByTestId('whats-new-next')); // DONE

    await waitFor(() => expect(screen.getByText('Second')).toBeTruthy());
    expect(mockedApi).toHaveBeenCalledWith('/api/announcements/a1/seen', { method: 'POST' });
    expect(screen.getByText('Second card 1')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('whats-new-skip'));
    await waitFor(() => expect(screen.queryByTestId('whats-new-overlay')).toBeNull());
    expect(mockedApi).toHaveBeenCalledWith('/api/announcements/a2/seen', { method: 'POST' });
    expect(mockedApi).toHaveBeenCalledTimes(3);
  });

  it('fetches once per identity and re-arms after a sign-out', async () => {
    mockedUseAuth.mockReturnValue(auth());
    mockedApi.mockResolvedValueOnce({ announcements: [] });
    await render(<WhatsNewOverlay />);
    await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(1));
    await screen.rerender(<WhatsNewOverlay />);
    expect(mockedApi).toHaveBeenCalledTimes(1);

    mockedUseAuth.mockReturnValue(auth({ user: null }));
    await screen.rerender(<WhatsNewOverlay />);
    mockedUseAuth.mockReturnValue(auth({ user: { user_id: 'u2' } }));
    mockedApi.mockResolvedValueOnce({ announcements: [ann('a9', 'For u2')] });
    await screen.rerender(<WhatsNewOverlay />);
    await waitFor(() => expect(screen.getByText('For u2')).toBeTruthy());
    expect(mockedApi).toHaveBeenCalledTimes(2);
  });
});

describe('WhatsNewDeck', () => {
  it('replays with a custom done label and BACK returns to the previous card', async () => {
    const onDone = jest.fn();
    await render(<WhatsNewDeck announcement={ann('h1', 'History', 2)} onDone={onDone} doneLabel="CLOSE" />);
    await fireEvent.press(screen.getByTestId('whats-new-next'));
    expect(screen.getByText('CLOSE')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('whats-new-back'));
    expect(screen.getByText('History card 1')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('whats-new-next'));
    await fireEvent.press(screen.getByTestId('whats-new-next'));
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
