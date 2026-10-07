// The licensed-states picker with pending states (Linnzi, 2026-09-29).
// Walked the way the other sheets are: it mounts closed with no target, then
// opens, and a state is never both licensed and pending.
import React from 'react';
import { render, fireEvent, screen } from '@testing-library/react-native';
import { LicensedStatesSheet } from '../LicensedStatesSheet';

type Target = React.ComponentProps<typeof LicensedStatesSheet>['target'];
const noop = async () => {};

test('mounts closed with no target, then opens on one', async () => {
  const { rerender } = await render(<LicensedStatesSheet target={null} onSave={noop} onClose={() => {}} />);
  expect(screen.queryByTestId('licensed-states-summary')).toBeNull();
  const target: Target = { name: 'Pat Lee', licensed_states: ['MI'], pending_states: ['IA'], pending_reminder: true };
  await rerender(<LicensedStatesSheet target={target} onSave={noop} onClose={() => {}} />);
  expect(screen.getByTestId('licensed-states-summary')).toHaveTextContent(/MI/);
  expect(screen.getByTestId('licensed-states-pending-summary')).toHaveTextContent(/IA/);
});

test('Puerto Rico can be picked', async () => {
  const onSave = jest.fn(noop);
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee' }} onSave={onSave} onClose={() => {}} />);
  await fireEvent.press(screen.getByTestId('licensed-state-PR'));
  await fireEvent.press(screen.getByTestId('licensed-states-save'));
  expect(onSave).toHaveBeenCalledWith(['PR'], [], true);
});

test('pending mode picks pending states and shows the weekly switch, on by default', async () => {
  const onSave = jest.fn(noop);
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee', licensed_states: ['MI'] }} onSave={onSave} onClose={() => {}} />);
  expect(screen.queryByTestId('licensed-states-remind')).toBeNull();
  await fireEvent.press(screen.getByTestId('licensed-mode-pending'));
  expect(screen.getByTestId('licensed-states-remind').props.value).toBe(true);
  await fireEvent.press(screen.getByTestId('licensed-state-IA'));
  await fireEvent.press(screen.getByTestId('licensed-states-save'));
  expect(onSave).toHaveBeenCalledWith(['MI'], ['IA'], true);
});

test('the switch can be turned off and is sent', async () => {
  const onSave = jest.fn(noop);
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee', pending_states: ['IA'] }} onSave={onSave} onClose={() => {}} />);
  await fireEvent.press(screen.getByTestId('licensed-mode-pending'));
  await fireEvent(screen.getByTestId('licensed-states-remind'), 'valueChange', false);
  await fireEvent.press(screen.getByTestId('licensed-states-save'));
  expect(onSave).toHaveBeenCalledWith([], ['IA'], false);
});

test('an agent whose switch was saved off opens with it off', async () => {
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee', pending_states: ['IA'], pending_reminder: false }} onSave={noop} onClose={() => {}} />);
  await fireEvent.press(screen.getByTestId('licensed-mode-pending'));
  expect(screen.getByTestId('licensed-states-remind').props.value).toBe(false);
});

test('licensing a pending state moves it out of pending', async () => {
  const onSave = jest.fn(noop);
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee', pending_states: ['IA', 'NE'] }} onSave={onSave} onClose={() => {}} />);
  await fireEvent.press(screen.getByTestId('licensed-state-IA'));
  await fireEvent.press(screen.getByTestId('licensed-states-save'));
  expect(onSave).toHaveBeenCalledWith(['IA'], ['NE'], true);
});

test('a licensed state cannot be marked pending', async () => {
  const onSave = jest.fn(noop);
  await render(<LicensedStatesSheet target={{ name: 'Pat Lee', licensed_states: ['MI'] }} onSave={onSave} onClose={() => {}} />);
  await fireEvent.press(screen.getByTestId('licensed-mode-pending'));
  await fireEvent.press(screen.getByTestId('licensed-state-MI'));
  await fireEvent.press(screen.getByTestId('licensed-states-save'));
  expect(onSave).toHaveBeenCalledWith(['MI'], [], true);
});
