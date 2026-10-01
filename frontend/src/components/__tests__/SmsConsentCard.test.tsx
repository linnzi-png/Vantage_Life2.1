// The one-time text-message consent card (batch 2, PR 0). Mounted from the
// root layout on every open, so the important cases are the ones where it
// must stay hidden: auth still loading, no agent profile, an answer already
// recorded, or the guided walkthrough on screen.
import React from 'react';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import SmsConsentCard, { SMS_CONSENT_HEADING } from '../SmsConsentCard';
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

const agentBase = { agent_id: 'AG_1', name: 'Ag One', office: 'MI RGA', role: 'level_1' as const, phone: '(734) 555-0100' };

function authState(over: Partial<AuthShape>): AuthShape {
  const base = {
    user: { user_id: 'u1', role: 'level_1', agent_id: 'AG_1' },
    agent: { ...agentBase },
    roleLabel: 'Agent',
    loading: false,
    reload: jest.fn(async () => {}),
    accountBusy: false,
  };
  // The card reads only user, agent, loading and reload; the rest of the
  // context is irrelevant to it, so the cast keeps the fixture honest about
  // what is actually being exercised.
  return { ...base, ...over } as unknown as AuthShape;
}

function tourState(active: boolean, deciding = false): TourShape {
  return { active, deciding } as unknown as TourShape;
}

beforeEach(() => {
  mockedApi.mockReset();
  mockedUseTour.mockReturnValue(tourState(false));
});

describe('SmsConsentCard', () => {
  it('shows for a linked agent who has never been asked', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    await render(<SmsConsentCard />);
    expect(screen.getByText(SMS_CONSENT_HEADING)).toBeTruthy();
    expect(screen.getByText('YES, TEXT ME')).toBeTruthy();
    expect(screen.getByText('NO THANKS')).toBeTruthy();
  });

  it('stays hidden while auth is loading, with no profile, or once an answer is recorded', async () => {
    mockedUseAuth.mockReturnValue(authState({ loading: true, agent: null }));
    await render(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();

    mockedUseAuth.mockReturnValue(authState({ user: { user_id: 'u2', role: 'finance_admin', agent_id: null } as never, agent: null }));
    await screen.rerender(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();

    mockedUseAuth.mockReturnValue(authState({
      agent: { ...agentBase, sms_consent: { status: 'opted_out', changed_at: '2026-09-29T00:00:00Z', source: 'onboarding_card' } },
    }));
    await screen.rerender(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();
  });

  it('stays hidden for a Financial Administrator even with a profile and a phone number', async () => {
    // Regression: their profile links (agent_id set), so the card used to show,
    // and either answer hit a route that refuses the role with a 403 popup.
    mockedUseAuth.mockReturnValue(authState({
      user: { user_id: 'u3', role: 'finance_admin', agent_id: 'AG_FA' } as never,
      agent: { ...agentBase, agent_id: 'AG_FA', role: 'finance_admin' as never },
    }));
    await render(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();
    expect(mockedApi).not.toHaveBeenCalled();
  });

  it('stays hidden when the profile has no phone number', async () => {
    mockedUseAuth.mockReturnValue(authState({ agent: { ...agentBase, phone: '' } }));
    await render(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();
  });

  it('waits while the walkthrough is still deciding whether to launch (first sign-in)', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    mockedUseTour.mockReturnValue(tourState(false, true));
    await render(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();

    // The tour decided to run: still hidden.
    mockedUseTour.mockReturnValue(tourState(true, false));
    await screen.rerender(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();
  });

  it('shows again for a different person who signs in on the same running app', async () => {
    const reload = jest.fn(async () => {});
    mockedUseAuth.mockReturnValue(authState({ reload }));
    mockedApi.mockResolvedValueOnce({ ok: true, sms_consent: { status: 'opted_in', changed_at: 'x', source: 'onboarding_card', phone: '(734) 555-0100' } });
    await render(<SmsConsentCard />);
    await fireEvent.press(screen.getByTestId('sms-consent-yes'));
    await waitFor(() => expect(screen.queryByTestId('sms-consent-card')).toBeNull());

    // Sign-out, then a second person with no recorded answer signs in.
    mockedUseAuth.mockReturnValue(authState({ user: null as never, agent: null }));
    await screen.rerender(<SmsConsentCard />);
    mockedUseAuth.mockReturnValue(authState({
      user: { user_id: 'u2', role: 'level_1', agent_id: 'AG_2' } as never,
      agent: { ...agentBase, agent_id: 'AG_2', name: 'Ag Two' },
    }));
    await screen.rerender(<SmsConsentCard />);
    expect(screen.getByTestId('sms-consent-card')).toBeTruthy();
  });

  it('waits while the guided walkthrough is on screen and appears once it ends', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    mockedUseTour.mockReturnValue(tourState(true));
    await render(<SmsConsentCard />);
    expect(screen.queryByTestId('sms-consent-card')).toBeNull();

    mockedUseTour.mockReturnValue(tourState(false));
    await screen.rerender(<SmsConsentCard />);
    expect(screen.getByTestId('sms-consent-card')).toBeTruthy();
  });

  it('YES records an opt-in from the card, refreshes the profile and closes for good', async () => {
    const reload = jest.fn(async () => {});
    mockedUseAuth.mockReturnValue(authState({ reload }));
    mockedApi.mockResolvedValueOnce({ ok: true, sms_consent: { status: 'opted_in', changed_at: 'x', source: 'onboarding_card' } });
    await render(<SmsConsentCard />);

    await fireEvent.press(screen.getByTestId('sms-consent-yes'));

    await waitFor(() => expect(screen.queryByTestId('sms-consent-card')).toBeNull());
    expect(mockedApi).toHaveBeenCalledWith('/api/me/sms-consent', {
      method: 'POST',
      body: JSON.stringify({ opted_in: true, source: 'onboarding_card' }),
    });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('NO THANKS records an opt-out the same way', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    mockedApi.mockResolvedValueOnce({ ok: true, sms_consent: { status: 'opted_out', changed_at: 'x', source: 'onboarding_card' } });
    await render(<SmsConsentCard />);

    await fireEvent.press(screen.getByTestId('sms-consent-no'));

    await waitFor(() => expect(screen.queryByTestId('sms-consent-card')).toBeNull());
    expect(mockedApi).toHaveBeenCalledWith('/api/me/sms-consent', {
      method: 'POST',
      body: JSON.stringify({ opted_in: false, source: 'onboarding_card' }),
    });
  });

  it('keeps the card up when the save fails so the person can try again', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    mockedApi.mockRejectedValueOnce(new Error('offline'));
    await render(<SmsConsentCard />);

    await fireEvent.press(screen.getByTestId('sms-consent-yes'));

    await waitFor(() => expect(screen.getByTestId('sms-consent-yes')).toBeEnabled());
    expect(screen.getByTestId('sms-consent-card')).toBeTruthy();
  });
});
