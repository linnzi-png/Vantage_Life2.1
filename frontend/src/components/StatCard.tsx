// Dashboard stat card: a headline figure on the front, and on tap the same
// figure broken down by office on the back (one row per office with a bar).
// Built on FlipCard + GlowCard; the screen decides which card is open.
//
// Small type here (10 to 11px) uses textDim, never textMuted, which fails AA
// contrast on the card surface at that size (design review, 2026-09-29).
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';
import { DISPLAY_FONT, useDisplayFonts } from '../lib/fonts';
import { withAlpha } from '../lib/motion';
import FlipCard from './FlipCard';

export interface OfficeStatRow {
  office: string;
  /** What the bar measures. */
  amount: number;
  /** What the row prints. */
  display: string;
}

export const STAT_CARD_HEIGHT = 170;

// The brand navy is too dark to read as small text or an icon on the card
// surface, so text and icons drawn in it use this lighter tint of the same
// hue. The card's border, glow and bars keep the brand colour itself.
const SECONDARY_TEXT = '#5AA9E6';

type IconName = React.ComponentProps<typeof Ionicons>['name'];

export default function StatCard({
  label, value, icon, accent, delta, deltaUnit = '%', deltaLabel, rows, backTitle,
  flipped, onFlip, testID,
}: {
  label: string;
  value: string;
  icon: IconName;
  accent: string;
  /** Change against the previous window; null or undefined hides the pill. */
  delta?: number | null;
  /** '%' for ALP, sales and sits; 'pts' for close ratio (percentage points). */
  deltaUnit?: '%' | 'pts';
  /** "vs yesterday", "vs last week" or "vs last month". */
  deltaLabel: string;
  /** One row per office; may be empty or absent before the data arrives. */
  rows?: OfficeStatRow[];
  /** "ALP BY OFFICE" and the like. */
  backTitle: string;
  flipped: boolean;
  onFlip: () => void;
  testID?: string;
}) {
  const fontsReady = useDisplayFonts();
  const safeRows = rows ?? [];
  const biggest = Math.max(...safeRows.map((r) => r.amount), 0);
  const textAccent = accent === COLORS.secondary ? SECONDARY_TEXT : accent;

  return (
    <FlipCard
      testID={testID}
      height={STAT_CARD_HEIGHT}
      accent={accent}
      flipped={flipped}
      onFlip={onFlip}
      frontLabel={`${label}, ${value}. Double tap to see it by office.`}
      backLabel={`${backTitle}. Double tap to flip back.`}
      style={styles.cell}
      front={() => (
        <View style={styles.pad}>
          <View style={styles.topRow}>
            <Text style={styles.label} numberOfLines={1}>{label}</Text>
            <View style={[styles.chip, { backgroundColor: withAlpha(accent, 0.18) }]}>
              <Ionicons name={icon} size={16} color={textAccent} />
            </View>
          </View>
          <Text
            style={[styles.value, fontsReady ? styles.valueDisplay : styles.valueSystem]}
            numberOfLines={1}
            adjustsFontSizeToFit
            testID={testID ? `${testID}-value` : undefined}
          >
            {value}
          </Text>
          {typeof delta === 'number'
            ? <DeltaPill delta={delta} unit={deltaUnit} label={deltaLabel} />
            : <View style={styles.pillSpace} />}
          <Text style={[styles.hint, { color: textAccent }]}>↻ Tap for by office</Text>
        </View>
      )}
      back={() => (
        <View style={styles.pad}>
          <Text style={[styles.backTitle, { color: textAccent }]} numberOfLines={1}>{backTitle}</Text>
          <View style={styles.rows}>
            {safeRows.length === 0 ? (
              <Text style={styles.empty}>No offices to show yet.</Text>
            ) : safeRows.map((r) => (
              <View key={r.office} style={styles.officeRow}>
                <Text style={styles.officeName} numberOfLines={1}>{r.office}</Text>
                <View style={styles.barTrack}>
                  <View
                    style={[
                      styles.barFill,
                      {
                        backgroundColor: accent,
                        width: `${biggest > 0 ? Math.max((r.amount / biggest) * 100, r.amount > 0 ? 3 : 0) : 0}%`,
                      },
                    ]}
                  />
                </View>
                <Text style={styles.officeValue} numberOfLines={1}>{r.display}</Text>
              </View>
            ))}
          </View>
          <Text style={styles.flipBack}>← Tap to flip back</Text>
        </View>
      )}
    />
  );
}

function DeltaPill({ delta, unit, label }: { delta: number; unit: '%' | 'pts'; label: string }) {
  const up = delta >= 0;
  const colour = up ? COLORS.primary : COLORS.red;
  return (
    <View style={[styles.pill, { backgroundColor: withAlpha(colour, 0.14) }]}>
      <Ionicons name={up ? 'arrow-up' : 'arrow-down'} size={10} color={colour} />
      <Text style={[styles.pillTxt, { color: colour }]} numberOfLines={1}>
        {up ? '+' : ''}{delta.toFixed(1)}{unit === '%' ? '%' : ' pts'}
        <Text style={styles.pillSub}> {label}</Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  cell: { width: '48.5%', marginBottom: 12 },
  pad: { flex: 1, padding: 12 },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6 },
  label: { flex: 1, color: COLORS.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.4, textTransform: 'uppercase' },
  chip: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  value: { color: COLORS.text, marginTop: 10 },
  valueDisplay: { fontFamily: DISPLAY_FONT.extrabold, fontSize: 32, lineHeight: 36, letterSpacing: 0.2 },
  valueSystem: { fontSize: 28, lineHeight: 34, fontWeight: '900', letterSpacing: -0.5 },
  pill: { alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 3, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 3, marginTop: 6 },
  pillSpace: { height: 22, marginTop: 6 },
  pillTxt: { fontSize: 10, fontWeight: '800' },
  pillSub: { color: COLORS.textDim, fontWeight: '600' },
  hint: { position: 'absolute', left: 12, bottom: 10, fontSize: 10, fontWeight: '800', letterSpacing: 0.4 },
  backTitle: { fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  rows: { flex: 1, justifyContent: 'center', gap: 5, paddingVertical: 4 },
  officeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 18 },
  officeName: { width: 58, color: COLORS.text, fontSize: 11, fontWeight: '700' },
  barTrack: { flex: 1, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3 },
  officeValue: { minWidth: 44, textAlign: 'right', color: COLORS.text, fontSize: 11, fontWeight: '800', fontVariant: ['tabular-nums'] },
  empty: { color: COLORS.textDim, fontSize: 11, textAlign: 'center' },
  flipBack: { color: COLORS.textDim, fontSize: 10, fontWeight: '700' },
});
