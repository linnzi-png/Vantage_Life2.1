// The date sheet took the Team tab down twice in one week (2026-09-26 and
// 2026-09-28), both times on the same sequence: mounted hidden before the
// server's sales day had arrived, then opened once it had. Typecheck cannot
// see that, so these tests walk that exact sequence. Every date is a sales
// day string; "today" is whatever the server said, never the device clock.
import React from 'react';
import { render, fireEvent, screen } from '@testing-library/react-native';
import { TeamDateSheet, MONTH_TO_DATE, describeWindow, DateWindow } from '../TeamDateSheet';

const noop = () => {};

describe('TeamDateSheet', () => {
  it('renders nothing while hidden with no sales day yet (the mount before /api/team answers)', async () => {
    await render(
      <TeamDateSheet visible={false} salesDay="" value={MONTH_TO_DATE} onChange={noop} onClose={noop} />,
    );
    expect(screen.toJSON()).toBeNull();
  });

  it('opens cleanly after being mounted with an empty sales day (the first-tap crash)', async () => {
    await render(
      <TeamDateSheet visible={false} salesDay="" value={MONTH_TO_DATE} onChange={noop} onClose={noop} />,
    );
    // The sales day arrives, then the person taps the date button.
    await screen.rerender(
      <TeamDateSheet visible={false} salesDay="2026-09-28" value={MONTH_TO_DATE} onChange={noop} onClose={noop} />,
    );
    await screen.rerender(
      <TeamDateSheet visible salesDay="2026-09-28" value={MONTH_TO_DATE} onChange={noop} onClose={noop} />,
    );
    expect(screen.getByText('SEPTEMBER 2026')).toBeTruthy();
    expect(screen.getByTestId('team-date-2026-09-28')).toBeTruthy();
    // Nothing after the sales day is selectable.
    expect(screen.getByTestId('team-date-2026-09-29')).toBeDisabled();
  });

  it('opens on the month the current selection ends in, not the sales day', async () => {
    const value: DateWindow = { mode: 'range', start: '2026-08-24', end: '2026-08-30' };
    await render(
      <TeamDateSheet visible salesDay="2026-09-28" value={value} onChange={noop} onClose={noop} />,
    );
    expect(screen.getByText('AUGUST 2026')).toBeTruthy();
  });

  it('two taps select a range, earlier day first whichever order they were tapped', async () => {
    const onChange = jest.fn();
    const onClose = jest.fn();
    await render(
      <TeamDateSheet visible salesDay="2026-09-28" value={MONTH_TO_DATE} onChange={onChange} onClose={onClose} />,
    );
    await fireEvent.press(screen.getByTestId('team-date-2026-09-20'));
    await fireEvent.press(screen.getByTestId('team-date-2026-09-14'));
    await fireEvent.press(screen.getByText('SHOW RANGE'));
    expect(onChange).toHaveBeenCalledWith({ mode: 'range', start: '2026-09-14', end: '2026-09-20' });
    expect(onClose).toHaveBeenCalled();
  });

  it('the previous-month arrow moves the calendar and the next arrow is disabled at the current month', async () => {
    await render(
      <TeamDateSheet visible salesDay="2026-09-28" value={MONTH_TO_DATE} onChange={noop} onClose={noop} />,
    );
    expect(screen.getByTestId('team-date-next')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('team-date-prev'));
    expect(screen.getByText('AUGUST 2026')).toBeTruthy();
    expect(screen.getByTestId('team-date-2026-08-01')).toBeTruthy();
  });

  it('the month to date row is offered only where allowed and applies MONTH_TO_DATE', async () => {
    const onChange = jest.fn();
    await render(
      <TeamDateSheet visible salesDay="2026-09-28" value={{ mode: 'range', start: '2026-09-01', end: '2026-09-02' }} onChange={onChange} onClose={noop} />,
    );
    await fireEvent.press(screen.getByTestId('team-date-mtd'));
    expect(onChange).toHaveBeenCalledWith(MONTH_TO_DATE);
    await screen.rerender(
      <TeamDateSheet visible salesDay="2026-09-28" value={MONTH_TO_DATE} allowMonthToDate={false} onChange={onChange} onClose={noop} />,
    );
    expect(screen.queryByTestId('team-date-mtd')).toBeNull();
  });
});

describe('describeWindow', () => {
  it('labels month to date from the echoed start when the server sent one', async () => {
    expect(describeWindow(MONTH_TO_DATE, '2026-09-28', '2026-09-01')).toBe('Month to date · Sep 1 – Sep 28');
    expect(describeWindow(MONTH_TO_DATE, '2026-09-28')).toBe('Month to date · Sep 1 – Sep 28');
  });

  it('labels a single day and a range', async () => {
    expect(describeWindow({ mode: 'range', start: '2026-09-16', end: '2026-09-16' }, '2026-09-28')).toBe('Sep 16');
    expect(describeWindow({ mode: 'range', start: '2026-09-14', end: '2026-09-20' }, '2026-09-28')).toBe('Sep 14 – Sep 20');
  });

  it('does not throw on a day string it cannot read', async () => {
    expect(() => describeWindow({ mode: 'range', start: '', end: '' }, '2026-09-28')).not.toThrow();
  });
});
