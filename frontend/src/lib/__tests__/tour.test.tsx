// The guided walkthrough auto-launches once per person, ever (batch 2,
// PR A): the only trigger is a signed-in user with no tour_completed_at
// from the server. These tests drive TourProvider through the auth context
// and read its state through a probe component.
import React from 'react';
import { Text } from 'react-native';
import { render, screen, waitFor, act } from '@testing-library/react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { TourProvider, useTour } from '../tour';
import { useAuth } from '../auth';

jest.mock('../auth', () => {
  const actual = jest.requireActual<typeof import('../auth')>('../auth');
  return { ...actual, useAuth: jest.fn() };
});

const mockedUseAuth = jest.mocked(useAuth);
type AuthShape = ReturnType<typeof useAuth>;

function Probe() {
  const { active, deciding, skip } = useTour();
  return (
    <>
      <Text testID="tour-active">{active ? 'yes' : 'no'}</Text>
      <Text testID="tour-deciding">{deciding ? 'yes' : 'no'}</Text>
      <Text testID="tour-skip" onPress={skip}>skip</Text>
    </>
  );
}

function authState(over: Partial<AuthShape> & { markTourCompleted?: jest.Mock }): AuthShape {
  const base = {
    user: { user_id: 'u1', role: 'level_1', agent_id: 'AG_1', tour_completed_at: null },
    agent: { agent_id: 'AG_1', name: 'Ag One', office: 'MI RGA', role: 'level_1' },
    loading: false,
    markTourCompleted: jest.fn(async () => {}),
  };
  return { ...base, ...over } as unknown as AuthShape;
}

const mount = () => render(<TourProvider><Probe /></TourProvider>);

beforeEach(async () => {
  jest.useFakeTimers();
  await AsyncStorage.clear();
});
afterEach(() => { jest.useRealTimers(); });

describe('TourProvider auto-launch', () => {
  it('launches on a first sign-in (no server stamp, no device flag) after the paint delay', async () => {
    mockedUseAuth.mockReturnValue(authState({}));
    await mount();
    expect(screen.getByTestId('tour-deciding').props.children).toBe('yes');
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    await act(async () => { jest.advanceTimersByTime(700); });
    await waitFor(() => expect(screen.getByTestId('tour-active').props.children).toBe('yes'));
    expect(screen.getByTestId('tour-deciding').props.children).toBe('no');
  });

  it('does not launch when the server says the person has already completed it', async () => {
    mockedUseAuth.mockReturnValue(authState({
      user: { user_id: 'u1', role: 'level_1', agent_id: 'AG_1', tour_completed_at: '2026-09-01T00:00:00Z' } as never,
    }));
    await mount();
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    expect(screen.getByTestId('tour-deciding').props.children).toBe('no');
  });

  it('does not relaunch after a role change once completed', async () => {
    const markTourCompleted = jest.fn(async () => {});
    const stamped = { user_id: 'u1', role: 'level_sa', agent_id: 'AG_1', tour_completed_at: '2026-09-29T00:00:00Z' };
    mockedUseAuth.mockReturnValue(authState({ user: stamped as never, markTourCompleted }));
    await mount();
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    // Promoted again: still stamped, still quiet.
    mockedUseAuth.mockReturnValue(authState({ user: { ...stamped, role: 'level_2' } as never, markTourCompleted }));
    await screen.rerender(<TourProvider><Probe /></TourProvider>);
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    expect(markTourCompleted).not.toHaveBeenCalled();
  });

  it('migrates an old device flag: marks the server done and does not show the tour', async () => {
    // A phone that finished the tour under the old scheme, at an older
    // content version and under a role the person no longer holds.
    await AsyncStorage.setItem('vl_tour_done_u1_level_2', JSON.stringify({ v: 3, completedAt: 'x' }));
    const markTourCompleted = jest.fn(async () => {});
    mockedUseAuth.mockReturnValue(authState({ markTourCompleted }));
    await mount();
    await waitFor(() => expect(markTourCompleted).toHaveBeenCalledTimes(1));
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    expect(screen.getByTestId('tour-deciding').props.children).toBe('no');
  });

  it('skip stamps the server and writes the device guard', async () => {
    const markTourCompleted = jest.fn(async () => {});
    mockedUseAuth.mockReturnValue(authState({ markTourCompleted }));
    await mount();
    await act(async () => { jest.advanceTimersByTime(700); });
    await waitFor(() => expect(screen.getByTestId('tour-active').props.children).toBe('yes'));
    await act(async () => { screen.getByTestId('tour-skip').props.onPress(); });
    expect(screen.getByTestId('tour-active').props.children).toBe('no');
    expect(markTourCompleted).toHaveBeenCalledTimes(1);
    const flag = await AsyncStorage.getItem('vl_tour_done_u1_level_1');
    expect(flag).toBeTruthy();
  });
});
