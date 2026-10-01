// The dashboard's flip cards mount their backs from the first frame, hidden
// behind the front, and a card can be opened at any moment: before the first
// response lands, with an empty office list, or after the data changes. The
// date sheet crashed twice on exactly that kind of sequence, and typecheck
// cannot see it, so each flip here is walked mount-empty-then-open.
//
// The backs are hidden from the accessibility tree until their card is open,
// so queries on a hidden face pass includeHiddenElements.
import React, { useState } from 'react';
import { AccessibilityInfo } from 'react-native';
import { render, fireEvent, screen } from '@testing-library/react-native';
import StatCard, { OfficeStatRow } from '../StatCard';
import PlatinumWall, { WallItem, Top10Item, WALL_VETS_ID, WALL_ROOKIES_ID } from '../PlatinumWall';
import { nextFlipped } from '../FlipCard';

const hidden = { includeHiddenElements: true };
const noop = () => {};

const OFFICES: OfficeStatRow[] = [
  { office: 'Gojcaj', amount: 12000, display: '$12,000' },
  { office: 'Alwatan', amount: 6000, display: '$6,000' },
  { office: 'Rust', amount: 0, display: '$0' },
];

const stat = (props: Partial<React.ComponentProps<typeof StatCard>> = {}) => (
  <StatCard
    label="Agency ALP"
    value="$18,000"
    icon="trending-up"
    accent="#319842"
    deltaLabel="vs yesterday"
    backTitle="ALP BY OFFICE"
    flipped={false}
    onFlip={noop}
    testID="stat-total-alp"
    {...props}
  />
);

const item = (n: number, over: Partial<WallItem> = {}): WallItem => ({
  agent_id: `a${n}`, name: `Agent ${n}`, office: 'Gojcaj', gross_alp: 10000 - n * 1000, sales: n, ...over,
});
const top = (n: number): Top10Item => ({
  rank: n, agent_id: `a${n}`, name: `Agent ${n}`, office: 'Gojcaj', gross_alp: 10000 - n * 500,
});

describe('StatCard', () => {
  it('mounts with no office rows (before the summary carries by_office), then opens', async () => {
    await render(stat({ rows: undefined }));
    await screen.rerender(stat({ rows: undefined, flipped: true }));
    expect(screen.getByText('No offices to show yet.')).toBeTruthy();
    expect(screen.getByText('ALP BY OFFICE')).toBeTruthy();
  });

  it('mounts with an empty list, then fills in while open', async () => {
    await render(stat({ rows: [], flipped: true }));
    await screen.rerender(stat({ rows: OFFICES, flipped: true }));
    expect(screen.getByText('Gojcaj')).toBeTruthy();
    expect(screen.getByText('$12,000')).toBeTruthy();
    expect(screen.getByText('Rust')).toBeTruthy();
  });

  it('draws the back while it is still hidden behind the front', async () => {
    await render(stat({ rows: OFFICES }));
    expect(screen.getByText('Alwatan', hidden)).toBeTruthy();
  });

  it('mounts already open', async () => {
    await render(stat({ rows: OFFICES, flipped: true }));
    expect(screen.getByText('$6,000')).toBeTruthy();
  });

  it('shows no delta pill without a previous window, and prints one with it', async () => {
    await render(stat({ delta: null }));
    expect(screen.queryByText(/vs yesterday/)).toBeNull();
    await screen.rerender(stat({ delta: 12.5 }));
    expect(screen.getByText(/\+12\.5%/)).toBeTruthy();
    await screen.rerender(stat({ delta: -3, deltaUnit: 'pts', deltaLabel: 'vs last week' }));
    expect(screen.getByText(/-3\.0 pts/)).toBeTruthy();
    expect(screen.getByText(/vs last week/)).toBeTruthy();
  });

  it('asks its parent to flip when the front is tapped', async () => {
    const onFlip = jest.fn();
    await render(stat({ onFlip }));
    await fireEvent.press(screen.getByTestId('stat-total-alp-front'));
    expect(onFlip).toHaveBeenCalledTimes(1);
  });

  it('asks its parent to flip back when the open back is tapped', async () => {
    const onFlip = jest.fn();
    await render(stat({ rows: OFFICES, flipped: true, onFlip }));
    await fireEvent.press(screen.getByTestId('stat-total-alp-back'));
    expect(onFlip).toHaveBeenCalledTimes(1);
  });
});

describe('PlatinumWall', () => {
  const wall = (props: Partial<React.ComponentProps<typeof PlatinumWall>> = {}) => (
    <PlatinumWall vets={[]} rookies={[]} {...props} />
  );

  it('mounts with nothing (the wall before its response), then opens the vets', async () => {
    await render(wall());
    await screen.rerender(wall({ flippedCard: WALL_VETS_ID }));
    expect(screen.getByText('TOP 10 VETS')).toBeTruthy();
    expect(screen.getAllByText('No production in this period.', hidden).length).toBeGreaterThan(0);
  });

  it('mounts with a top 3 but no top 10 (an older server), then opens the rookies', async () => {
    await render(wall({ rookies: [item(1), item(2)] }));
    await screen.rerender(wall({ rookies: [item(1), item(2)], flippedCard: WALL_ROOKIES_ID }));
    expect(screen.getByText('TOP 10 ROOKIES')).toBeTruthy();
  });

  it('fills the top 10 in while the card is open, in rank order', async () => {
    const ten = Array.from({ length: 10 }, (_, i) => top(i + 1));
    await render(wall({ vets: [item(1), item(2), item(3)], flippedCard: WALL_VETS_ID }));
    await screen.rerender(wall({ vets: [item(1), item(2), item(3)], top10Vets: ten, flippedCard: WALL_VETS_ID }));
    expect(screen.getByText('Agent 10')).toBeTruthy();
    expect(screen.getByText('$5,000')).toBeTruthy();
    expect(screen.getAllByText('← Tap to flip back', hidden).length).toBeGreaterThan(0);
  });

  it('shows at most three rows on a front, and the tap-for-top-10 line', async () => {
    const five = [1, 2, 3, 4, 5].map((n) => item(n));
    await render(wall({ vets: five }));
    expect(screen.getByTestId('platinum-item-a3')).toBeTruthy();
    expect(screen.queryByTestId('platinum-item-a4')).toBeNull();
    expect(screen.getAllByText('→ Tap to see top 10 leaderboard').length).toBe(2);
  });

  it('no longer draws a TENURE NOT SET panel or its hint', async () => {
    await render(wall({ vets: [item(1)] }));
    expect(screen.queryByText(/TENURE NOT SET/)).toBeNull();
    expect(screen.queryByText(/Set Veteran or Rookie/)).toBeNull();
  });

  it('keeps the Platinum Rule strip', async () => {
    await render(wall({
      platinum: [{ shoutout_id: 's1', agent_name: 'J. Rivera', office: 'Rust', reason: 'Stayed late to help' }],
    }));
    expect(screen.getByTestId('platinum-rule-strip')).toBeTruthy();
    expect(screen.getByText('PLATINUM RULE')).toBeTruthy();
  });

  it('asks the screen to flip the card that was tapped', async () => {
    const onFlipCard = jest.fn();
    await render(wall({ vets: [item(1)], onFlipCard }));
    await fireEvent.press(screen.getByTestId('platinum-rookies-front'));
    expect(onFlipCard).toHaveBeenCalledWith(WALL_ROOKIES_ID);
  });
});

describe('one card open at a time', () => {
  it('nextFlipped opens a tapped card, closes the open one, and swaps when another is tapped', () => {
    expect(nextFlipped(null, 'a')).toBe('a');
    expect(nextFlipped('a', 'a')).toBeNull();
    expect(nextFlipped('a', 'b')).toBe('b');
  });

  it('tapping a second card across the stat grid and the wall flips the first back', async () => {
    function Screen() {
      const [open, setOpen] = useState<string | null>(null);
      return (
        <>
          {stat({ rows: OFFICES, flipped: open === 'stat-alp', onFlip: () => setOpen((c) => nextFlipped(c, 'stat-alp')) })}
          <PlatinumWall
            vets={[item(1)]}
            rookies={[]}
            flippedCard={open}
            onFlipCard={(id) => setOpen((c) => nextFlipped(c, id))}
          />
        </>
      );
    }
    await render(<Screen />);
    // Nothing open: the stat back is hidden, the vets back is hidden.
    expect(screen.queryByText('ALP BY OFFICE')).toBeNull();
    await fireEvent.press(screen.getByTestId('stat-total-alp-front'));
    expect(screen.getByText('ALP BY OFFICE')).toBeTruthy();
    // Opening the vets turns the stat card back over.
    await fireEvent.press(screen.getByTestId('platinum-vets-front'));
    expect(screen.queryByText('ALP BY OFFICE')).toBeNull();
    expect(screen.getByText('TOP 10 VETS')).toBeTruthy();
    // Tapping the open back closes it.
    await fireEvent.press(screen.getByTestId('platinum-vets-back'));
    expect(screen.queryByText('TOP 10 VETS')).toBeNull();
  });
});

describe('Reduce Motion', () => {
  it('swaps faces without animating when the system asks for reduced motion', async () => {
    const spy = jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);
    await render(stat({ rows: OFFICES }));
    await screen.rerender(stat({ rows: OFFICES, flipped: true }));
    expect(screen.getByText('Gojcaj')).toBeTruthy();
    await screen.rerender(stat({ rows: OFFICES, flipped: false }));
    expect(screen.queryByText('Gojcaj')).toBeNull();
    spy.mockRestore();
  });
});
