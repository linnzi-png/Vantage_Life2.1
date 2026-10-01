// The Platinum Wall: Top 3 Vets and Top 3 Rookies as two flip cards. The front
// is the top three with rank badges and bars; tapping turns the card over to
// the top 10 by Gross ALP in that group. The Platinum Rule strip sits under
// them and does not flip.
//
// The TENURE NOT SET panel and its hint are gone (owner, 2026-10-01): the
// server still returns `unranked`, but the wall no longer draws it.
//
// Both fronts are always exactly three rows tall and names run to one line, so
// the two cards stay the same height whatever the data (design review,
// 2026-09-29). Small type uses textDim, not textMuted.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';
import { withAlpha } from '../lib/motion';
import FlipCard from './FlipCard';

export interface WallItem {
  agent_id: string; name: string; office: string; gross_alp: number; sales: number;
  // null = tenure never recorded, which is most of the roster.
  is_rookie?: boolean | null; role?: string; io_role?: string; phone?: string; email?: string;
  // A removed person whose logged production still counts for the window.
  archived?: boolean;
}
/** One row of a top 10 list: rank, name, office and Gross ALP only. */
export interface Top10Item { rank: number; agent_id: string; name: string; office: string; gross_alp: number; }
export interface PlatinumRulePost { shoutout_id: string; agent_name: string; office: string; reason: string; posted_by?: string; }

const PLATINUM = '#E5E4E2';
// Tall enough for the back: header, ten 12px rows with 5px gaps, the flip-back line.
export const WALL_CARD_HEIGHT = 264;
const FRONT_ROWS = 3;
const FRONT_ROW_HEIGHT = 46;

export const WALL_VETS_ID = 'wall-vets';
export const WALL_ROOKIES_ID = 'wall-rookies';

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;

export default function PlatinumWall(
  {
    vets, rookies, top10Vets = [], top10Rookies = [], platinum = [], windowLabel, subtitle,
    flippedCard = null, onFlipCard,
  }: {
    vets: WallItem[]; rookies: WallItem[];
    /** From /dashboard/platinum-wall; absent from an older server. */
    top10Vets?: Top10Item[];
    top10Rookies?: Top10Item[];
    platinum?: PlatinumRulePost[];
    windowLabel?: string;
    /** One line under the title saying what the wall ranks over (owner,
     *  2026-09-19: every dashboard section states its own scope). */
    subtitle?: string;
    /** Which card on the screen is turned over, if any. */
    flippedCard?: string | null;
    onFlipCard?: (id: string) => void;
  },
) {
  const flip = (id: string) => () => onFlipCard?.(id);
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title}>PLATINUM WALL</Text>
        {windowLabel ? <Text style={styles.window}>{windowLabel}</Text> : null}
      </View>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      <View style={styles.row}>
        <WallCard
          id={WALL_VETS_ID}
          title="TOP 3 VETS"
          backTitle="TOP 10 VETS"
          color={COLORS.gold}
          icon="ribbon"
          items={vets}
          top10={top10Vets}
          flipped={flippedCard === WALL_VETS_ID}
          onFlip={flip(WALL_VETS_ID)}
          testID="platinum-vets"
        />
        <WallCard
          id={WALL_ROOKIES_ID}
          title="TOP 3 ROOKIES"
          backTitle="TOP 10 ROOKIES"
          color={COLORS.orange}
          icon="rocket"
          items={rookies}
          top10={top10Rookies}
          flipped={flippedCard === WALL_ROOKIES_ID}
          onFlip={flip(WALL_ROOKIES_ID)}
          testID="platinum-rookies"
        />
      </View>
      {platinum.length ? (
        <View style={styles.rule} testID="platinum-rule-strip">
          <View style={styles.panelHeader}>
            <Ionicons name="medal" size={14} color={PLATINUM} />
            <Text style={[styles.panelTitle, { color: PLATINUM }]}>PLATINUM RULE</Text>
          </View>
          {platinum.map((p) => (
            <View key={p.shoutout_id} style={styles.item}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{p.agent_name} <Text style={styles.meta}>· {p.office}</Text></Text>
                <Text style={[styles.meta, { fontStyle: 'italic' }]} numberOfLines={2}>&quot;{p.reason}&quot;</Text>
              </View>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function WallCard({ id, title, backTitle, color, icon, items, top10, flipped, onFlip, testID }: {
  id: string;
  title: string;
  backTitle: string;
  color: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  items: WallItem[];
  top10: Top10Item[];
  flipped: boolean;
  onFlip: () => void;
  testID: string;
}) {
  const top = items.slice(0, FRONT_ROWS);
  const biggest = Math.max(...top.map((i) => i.gross_alp), 0);
  return (
    <FlipCard
      testID={testID}
      height={WALL_CARD_HEIGHT}
      accent={color}
      flipped={flipped}
      onFlip={onFlip}
      style={styles.cell}
      frontLabel={`${title}. Double tap to see the top 10 leaderboard.`}
      backLabel={`${backTitle}. Double tap to flip back.`}
      front={() => (
        <View style={styles.pad} key={`${id}-front`}>
          <View style={styles.panelHeader}>
            <Ionicons name={icon} size={14} color={color} />
            <Text style={[styles.panelTitle, { color }]}>{title}</Text>
          </View>
          <View style={styles.frontRows}>
            {top.length === 0 ? (
              <Text style={styles.empty}>No production in this period.</Text>
            ) : top.map((it, i) => (
              // A plain row, not a button: the whole card is one tap target that
              // flips to the top 10 (owner, 2026-10-01).
              <View
                key={it.agent_id}
                style={styles.frontRow}
                accessible
                accessibilityLabel={`${i + 1}. ${it.name}, ${money(it.gross_alp)}`}
                testID={`platinum-item-${it.agent_id}`}
              >
                <View style={[styles.badge, { backgroundColor: withAlpha(color, 0.2), borderColor: withAlpha(color, 0.55) }]}>
                  <Text style={[styles.badgeTxt, { color }]}>{i + 1}</Text>
                </View>
                <View style={styles.rowBody}>
                  <View style={styles.rowTop}>
                    <Text style={styles.name} numberOfLines={1}>{it.name}</Text>
                    <Text style={styles.alp}>{money(it.gross_alp)}</Text>
                  </View>
                  <View style={styles.bar}>
                    <View style={[styles.barFill, { backgroundColor: color, width: `${biggest > 0 ? Math.max((it.gross_alp / biggest) * 100, 4) : 0}%` }]} />
                  </View>
                </View>
              </View>
            ))}
          </View>
          <Text style={[styles.hint, { color }]}>→ Tap to see top 10 leaderboard</Text>
        </View>
      )}
      back={() => (
        <View style={styles.pad} key={`${id}-back`}>
          <View style={styles.panelHeader}>
            <Ionicons name={icon} size={14} color={color} />
            <Text style={[styles.panelTitle, { color }]}>{backTitle}</Text>
          </View>
          <View style={styles.backRows}>
            {top10.length === 0 ? (
              <Text style={styles.empty}>No production in this period.</Text>
            ) : top10.map((it) => (
              <View key={it.agent_id} style={styles.backRow}>
                <Text style={[styles.backRank, { color }]}>{it.rank}</Text>
                <Text style={styles.backName} numberOfLines={1}>{it.name}</Text>
                <Text style={styles.backAlp}>{money(it.gross_alp)}</Text>
              </View>
            ))}
          </View>
          <Text style={styles.flipBack}>← Tap to flip back</Text>
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 8 },
  head: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 },
  title: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  window: { color: COLORS.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1 },
  subtitle: { color: COLORS.textDim, fontSize: 11, marginTop: -4, marginBottom: 10 },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  cell: { width: '48.5%' },
  pad: { flex: 1, padding: 10 },
  panelHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 },
  panelTitle: { fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  frontRows: { flex: 1 },
  frontRow: { minHeight: FRONT_ROW_HEIGHT, flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  badge: { width: 22, height: 22, borderRadius: 11, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  badgeTxt: { fontSize: 12, fontWeight: '900' },
  rowBody: { flex: 1 },
  rowTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6 },
  name: { flex: 1, color: COLORS.text, fontSize: 12, fontWeight: '700' },
  alp: { color: COLORS.primary, fontSize: 12, fontWeight: '900', fontVariant: ['tabular-nums'] },
  bar: { height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.08)', marginTop: 5, overflow: 'hidden' },
  barFill: { height: 4, borderRadius: 2 },
  hint: { fontSize: 10, fontWeight: '800', letterSpacing: 0.3, marginTop: 4 },
  backRows: { flex: 1, justifyContent: 'center', gap: 5 },
  backRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  backRank: { width: 16, textAlign: 'center', fontSize: 12, fontWeight: '900' },
  backName: { flex: 1, color: COLORS.text, fontSize: 12, fontWeight: '600' },
  backAlp: { color: COLORS.primary, fontSize: 12, fontWeight: '800', fontVariant: ['tabular-nums'] },
  flipBack: { color: COLORS.textDim, fontSize: 10, fontWeight: '700', marginTop: 4 },
  empty: { color: COLORS.textDim, fontSize: 11, paddingVertical: 8, textAlign: 'center' },
  rule: {
    marginTop: 12, padding: 10, borderRadius: 8, borderWidth: 1, borderColor: COLORS.border,
    borderTopWidth: 2, borderTopColor: PLATINUM, backgroundColor: COLORS.surface,
  },
  item: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderTopWidth: 1, borderTopColor: COLORS.border },
  meta: { color: COLORS.textDim, fontSize: 10 },
});
