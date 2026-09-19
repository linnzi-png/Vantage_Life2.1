// Push Month centerpiece (owner, 2026-09-19): one company-wide Gross ALP goal,
// drawn at the top of the dashboard for the length of the campaign.
//
// The shape is a hybrid the owner asked for: a fill bar for the whole run,
// and once the company is inside the final 20% a "$X to go" countdown joins
// it, so the last stretch reads as a chase rather than a slow fill. The
// days-left counter is always on. Tapping anywhere opens the detail sheet
// (PushGoalDetail) with the by-day and by-office breakdowns.
//
// The number is the server's (GET /api/dashboard/push-goal): the client never
// sums anything, and the 80% switch (show_countdown) is decided there too, so
// the bar and the callout can never disagree about where the campaign stands.
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Animated, Easing, LayoutChangeEvent } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect, Pattern, Path } from 'react-native-svg';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';
import { DISPLAY_FONT, useDisplayFonts } from '../lib/fonts';

export interface PushGoalDay { sales_day: string; alp: number; sales: number; }
export interface PushGoalOffice { office: string; alp: number; sales: number; }

export interface PushGoalData {
  label: string;
  goal_alp: number;
  start_day: string;
  end_day: string;
  today: string;
  days_remaining: number;
  started: boolean;
  ended: boolean;
  total_alp: number;
  total_sales: number;
  pct: number;
  remaining_alp: number;
  countdown_pct: number;
  show_countdown: boolean;
  by_day: PushGoalDay[];
  by_office: PushGoalOffice[];
}

export const fmtWhole = (n: number) => `$${Math.round(n).toLocaleString()}`;

/** "$1.2M" / "$640K" — the goal itself and the big total, where every digit
 *  of a seven-figure number would crowd the card. */
export function fmtCompact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 2).replace(/\.?0+$/, '')}M`;
  if (abs >= 10_000) return `$${Math.round(n / 1000).toLocaleString()}K`;
  return fmtWhole(n);
}

function daysLabel(d: PushGoalData): string {
  if (d.ended) return 'CAMPAIGN COMPLETE';
  if (!d.started) return `STARTS ${d.start_day.slice(5).replace('-', '/')}`;
  if (d.days_remaining === 0) return 'FINAL DAY';
  return `${d.days_remaining} DAY${d.days_remaining === 1 ? '' : 'S'} LEFT`;
}

const MILESTONES = [25, 50, 75];
const TRACK_H = 22;

export default function PushGoal({ data, onPress, testID = 'push-goal' }: {
  data: PushGoalData;
  onPress?: () => void;
  testID?: string;
}) {
  const [trackW, setTrackW] = useState(0);
  // Barlow Condensed for the title, the big number and the callouts — the
  // one place in the app the display face is used, which is what makes the
  // card read as the campaign centerpiece rather than another stat card.
  // Weight rides on the file, so these styles set no fontWeight.
  const fontsReady = useDisplayFonts();
  const display = fontsReady ? { fontFamily: DISPLAY_FONT.extrabold, fontWeight: 'normal' as const } : null;
  const displaySemi = fontsReady ? { fontFamily: DISPLAY_FONT.semibold, fontWeight: 'normal' as const } : null;
  // Animated.Values held in state initializers rather than refs: they are
  // created once and mutated in place by the animations, exactly as a ref
  // would be, but the interpolations below are read during render and the
  // react-hooks/refs rule (rightly) refuses ref reads there.
  const [fill] = useState(() => new Animated.Value(0));
  const [reveal] = useState(() => [new Animated.Value(0), new Animated.Value(0), new Animated.Value(0)]);
  const [pulse] = useState(() => new Animated.Value(0));

  const clampedPct = Math.min(Math.max(data.pct, 0), 100);
  const reached = data.pct >= 100;

  // Staggered entrance: the header lands, then the bar fills, then the
  // figures under it. The fill retargets on every refresh, so a policy
  // entered while the dashboard is open visibly nudges the bar forward.
  useEffect(() => {
    Animated.timing(fill, {
      toValue: clampedPct,
      duration: 1100,
      delay: 250,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false, // animates width
    }).start();
  }, [clampedPct, fill]);

  useEffect(() => {
    Animated.stagger(140, reveal.map((v) =>
      Animated.timing(v, { toValue: 1, duration: 420, easing: Easing.out(Easing.quad), useNativeDriver: true }),
    )).start();
  }, [reveal]);

  // The countdown callout breathes while it is on. Stopped when it is not, so
  // a card in the 0–80% state costs nothing.
  useEffect(() => {
    if (!data.show_countdown || reached) { pulse.stopAnimation(); pulse.setValue(0); return; }
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0, duration: 900, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [data.show_countdown, reached, pulse]);

  const fillWidth = fill.interpolate({ inputRange: [0, 100], outputRange: ['0%', '100%'] });
  const entrance = (i: number) => ({
    opacity: reveal[i],
    transform: [{ translateY: reveal[i].interpolate({ inputRange: [0, 1], outputRange: [8, 0] }) }],
  });
  const calloutScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.03] });

  return (
    <TouchableOpacity
      style={[styles.card, reached && styles.cardReached]}
      onPress={onPress}
      activeOpacity={0.85}
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={`${data.label}. ${fmtWhole(data.total_alp)} of ${fmtWhole(data.goal_alp)}, ${Math.round(data.pct)} percent. ${daysLabel(data)}. Opens the breakdown.`}
    >
      <Animated.View style={[styles.head, entrance(0)]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>PUSH MONTH</Text>
          <Text style={[styles.title, display, fontsReady && styles.titleDisplay]}>{data.label.replace(/^Push Month:\s*/i, '').toUpperCase()}</Text>
        </View>
        <View style={[styles.daysChip, data.days_remaining <= 7 && data.started && !data.ended && styles.daysChipUrgent]}>
          <Ionicons name="hourglass-outline" size={11} color={COLORS.gold} />
          <Text style={[styles.daysTxt, displaySemi, fontsReady && styles.daysTxtDisplay]} testID="push-goal-days">{daysLabel(data)}</Text>
        </View>
      </Animated.View>

      <Animated.View style={[styles.figures, entrance(1)]}>
        <Text style={[styles.total, display, fontsReady && styles.totalDisplay]} testID="push-goal-total" numberOfLines={1} adjustsFontSizeToFit>
          {fmtWhole(data.total_alp)}
        </Text>
        <View style={styles.goalCol}>
          <Text style={styles.ofGoal}>OF {fmtCompact(data.goal_alp).toUpperCase()}</Text>
          <Text style={[styles.pct, display, fontsReady && styles.pctDisplay, reached && { color: COLORS.gold }]} testID="push-goal-pct">
            {data.pct.toFixed(data.pct >= 10 ? 0 : 1)}%
          </Text>
        </View>
      </Animated.View>

      <View
        style={styles.track}
        onLayout={(e: LayoutChangeEvent) => setTrackW(e.nativeEvent.layout.width)}
        testID="push-goal-track"
      >
        {/* The gradient is drawn at the full track width and clipped by the
            animated wrapper, so the colour ramp stays put while the fill
            grows across it — green at the start, gold at the goal. */}
        <Animated.View style={[styles.fillClip, { width: fillWidth }]}>
          {trackW > 0 ? (
            <Svg width={trackW} height={TRACK_H}>
              <Defs>
                <LinearGradient id="pushGoalFill" x1="0" y1="0" x2="1" y2="0">
                  <Stop offset="0" stopColor={COLORS.primary} />
                  <Stop offset="0.7" stopColor="#7CC54A" />
                  <Stop offset="1" stopColor={COLORS.gold} />
                </LinearGradient>
                <Pattern id="pushGoalHatch" patternUnits="userSpaceOnUse" width="10" height={TRACK_H} patternTransform="rotate(28)">
                  <Path d={`M0 0 H4 V${TRACK_H} H0 Z`} fill="rgba(0,0,0,0.16)" />
                </Pattern>
              </Defs>
              <Rect x="0" y="0" width={trackW} height={TRACK_H} fill="url(#pushGoalFill)" />
              <Rect x="0" y="0" width={trackW} height={TRACK_H} fill="url(#pushGoalHatch)" />
              <Rect x="0" y="0" width={trackW} height={Math.round(TRACK_H * 0.42)} fill="rgba(255,255,255,0.12)" />
            </Svg>
          ) : null}
        </Animated.View>
        {MILESTONES.map((m) => (
          <View key={m} style={[styles.tick, { left: `${m}%` }, clampedPct >= m && styles.tickPassed]} />
        ))}
      </View>
      <View style={styles.scale}>
        <Text style={styles.scaleTxt}>{data.start_day.slice(5).replace('-', '/')}</Text>
        {MILESTONES.map((m) => (
          <Text key={m} style={[styles.scaleTxt, styles.scaleMid, clampedPct >= m && styles.scaleTxtPassed]}>{m}%</Text>
        ))}
        <Text style={[styles.scaleTxt, reached && styles.scaleTxtPassed]}>{fmtCompact(data.goal_alp).toUpperCase()}</Text>
      </View>

      <Animated.View style={[styles.foot, entrance(2)]}>
        {reached ? (
          <View style={[styles.callout, styles.calloutReached]} testID="push-goal-reached">
            <Ionicons name="trophy" size={14} color="#000" />
            <Text style={[styles.calloutTxt, display, fontsReady && styles.calloutTxtDisplay, { color: '#000' }]} numberOfLines={1} adjustsFontSizeToFit>GOAL HIT · {fmtWhole(data.total_alp - data.goal_alp)} OVER</Text>
          </View>
        ) : data.show_countdown ? (
          <Animated.View style={[styles.callout, { transform: [{ scale: calloutScale }] }]} testID="push-goal-countdown">
            <Ionicons name="flash" size={14} color={COLORS.gold} />
            <Text style={[styles.calloutTxt, display, fontsReady && styles.calloutTxtDisplay]} numberOfLines={1} adjustsFontSizeToFit>{fmtWhole(data.remaining_alp)} TO GO</Text>
          </Animated.View>
        ) : (
          <Text style={styles.footTxt}>
            {data.total_sales.toLocaleString()} {data.total_sales === 1 ? 'POLICY' : 'POLICIES'} · ALL OFFICES · SINCE {data.start_day.slice(5).replace('-', '/')}
          </Text>
        )}
        <View style={styles.more}>
          <Text style={styles.moreTxt}>BREAKDOWN</Text>
          <Ionicons name="chevron-forward" size={12} color={COLORS.textDim} />
        </View>
      </Animated.View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: COLORS.surface,
    borderWidth: 1, borderColor: COLORS.border,
    borderTopWidth: 2, borderTopColor: COLORS.gold,
    borderRadius: 6, padding: 14, marginBottom: 14,
  },
  cardReached: { borderColor: 'rgba(255,215,0,0.45)' },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  kicker: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 2.4 },
  title: { color: '#fff', fontSize: 15, fontWeight: '900', letterSpacing: 0.4, marginTop: 2, lineHeight: 18 },
  daysChip: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    borderWidth: 1, borderColor: 'rgba(255,215,0,0.35)', borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 5, backgroundColor: 'rgba(255,215,0,0.06)',
  },
  daysChipUrgent: { borderColor: COLORS.gold, backgroundColor: 'rgba(255,215,0,0.14)' },
  daysTxt: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  figures: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 12, gap: 10 },
  total: {
    flex: 1, color: '#fff', fontSize: 38, fontWeight: '900', letterSpacing: -1.2, lineHeight: 42,
    fontVariant: ['tabular-nums'],
  },
  goalCol: { alignItems: 'flex-end', paddingBottom: 4 },
  ofGoal: { color: COLORS.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  pct: { color: COLORS.primary, fontSize: 18, fontWeight: '900', letterSpacing: -0.3, fontVariant: ['tabular-nums'] },
  track: {
    height: TRACK_H, marginTop: 10, borderRadius: 4, overflow: 'hidden',
    backgroundColor: '#0A0A0A', borderWidth: 1, borderColor: 'rgba(255,255,255,0.10)',
  },
  fillClip: { position: 'absolute', left: 0, top: 0, bottom: 0, overflow: 'hidden' },
  tick: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: 'rgba(255,255,255,0.18)' },
  tickPassed: { backgroundColor: 'rgba(0,0,0,0.35)' },
  scale: { flexDirection: 'row', alignItems: 'center', marginTop: 5 },
  scaleTxt: { color: COLORS.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },
  scaleMid: { flex: 1, textAlign: 'center' },
  scaleTxtPassed: { color: COLORS.textDim },
  foot: { flexDirection: 'row', alignItems: 'center', marginTop: 12, gap: 8 },
  footTxt: { flex: 1, color: COLORS.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.8 },
  callout: {
    flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6,
    borderWidth: 1, borderColor: COLORS.gold, borderRadius: 4,
    paddingHorizontal: 10, paddingVertical: 7, backgroundColor: 'rgba(255,215,0,0.10)',
  },
  calloutReached: { backgroundColor: COLORS.gold },
  calloutTxt: { color: COLORS.gold, fontSize: 12, fontWeight: '900', letterSpacing: 1, fontVariant: ['tabular-nums'] },
  more: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  moreTxt: { color: COLORS.textDim, fontSize: 9, fontWeight: '900', letterSpacing: 1.2 },
  // Condensed metrics: the display face sets tighter and taller than the
  // system font, so each use gets its own size and tracking once loaded.
  titleDisplay: { fontSize: 22, lineHeight: 24, letterSpacing: 0.6 },
  daysTxtDisplay: { fontSize: 13, letterSpacing: 1.2 },
  totalDisplay: { fontSize: 52, lineHeight: 54, letterSpacing: -0.5 },
  pctDisplay: { fontSize: 24, letterSpacing: 0 },
  calloutTxtDisplay: { fontSize: 17, letterSpacing: 1.4 },
});
