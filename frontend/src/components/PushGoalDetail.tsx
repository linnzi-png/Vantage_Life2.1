// The Push Month breakdown sheet: the same company-wide total the dashboard
// card shows, split by office and by sales day. Read-only, and every figure
// on it comes from the one /api/dashboard/push-goal response the card already
// holds, so opening it costs no request and can never disagree with the bar.
//
// By office, not by team, and no per-agent rows: MJ was asked and declined a
// per-team breakdown (spec, 2026-09-19), and four office totals are the whole
// of what a level_1 reads past their own office here.
import React from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';
import { PushGoalData, fmtWhole, fmtCompact } from './PushGoal';

function fmtDay(d: string): string {
  const [y, m, dd] = d.split('-').map(Number);
  const date = new Date(y, (m || 1) - 1, dd || 1);
  return `${date.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()} ${m}/${dd}`;
}

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(value / max, 1) * 100 : 0;
  return (
    <View style={styles.bar}>
      <View style={[styles.barFill, { width: `${pct}%`, backgroundColor: color }]} />
    </View>
  );
}

export function PushGoalDetail({ data, onClose }: { data: PushGoalData | null; onClose: () => void }) {
  if (!data) return null;
  const officeMax = Math.max(...data.by_office.map((o) => o.alp), 0);
  const dayMax = Math.max(...data.by_day.map((d) => d.alp), 0);
  // Newest night first — that is the one everybody opens this for.
  const days = [...data.by_day].reverse();
  const bestDay = data.by_day.reduce<typeof data.by_day[number] | null>(
    (best, d) => (d.alp > (best?.alp ?? 0) ? d : best), null);
  const nightsSoFar = data.by_day.length;
  const avgPerNight = nightsSoFar > 0 ? data.total_alp / nightsSoFar : 0;
  // What the remaining nights each need to average to land the goal. Plain
  // arithmetic on the server's numbers, shown as a pace, not a forecast.
  const nightsLeft = data.days_remaining + (data.started && !data.ended ? 1 : 0);
  const neededPerNight = nightsLeft > 0 ? data.remaining_alp / nightsLeft : 0;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} testID="push-goal-detail-close" />
        <View style={styles.sheet} testID="push-goal-detail">
          <View style={styles.handle} />
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.kicker}>PUSH MONTH · BREAKDOWN</Text>
              <Text style={styles.title}>{fmtWhole(data.total_alp)} <Text style={styles.titleDim}>OF {fmtCompact(data.goal_alp).toUpperCase()}</Text></Text>
            </View>
            <TouchableOpacity onPress={onClose} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} accessibilityLabel="Close">
              <Ionicons name="close" size={22} color={COLORS.textDim} />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false}>
            <View style={styles.stats}>
              <Stat label="Policies" value={data.total_sales.toLocaleString()} />
              <Stat label="Avg / Night" value={fmtCompact(avgPerNight)} />
              <Stat
                label={data.remaining_alp > 0 && nightsLeft > 0 ? 'Need / Night' : 'Remaining'}
                value={data.remaining_alp > 0 && nightsLeft > 0 ? fmtCompact(neededPerNight) : fmtCompact(data.remaining_alp)}
                accent={data.remaining_alp > 0 ? COLORS.gold : COLORS.primary}
              />
            </View>

            <Text style={styles.section}>BY OFFICE</Text>
            <View style={styles.list} testID="push-goal-by-office">
              {data.by_office.map((o, i) => (
                <View key={o.office} style={styles.row} testID={`push-goal-office-${o.office}`}>
                  <View style={styles.rowHead}>
                    <Text style={[styles.rank, i === 0 && o.alp > 0 && { color: COLORS.gold }]}>{i + 1}</Text>
                    <Text style={styles.rowName} numberOfLines={1}>{o.office.toUpperCase()}</Text>
                    <Text style={styles.rowSub}>{o.sales} {o.sales === 1 ? 'policy' : 'policies'}</Text>
                    <Text style={styles.rowValue}>{fmtWhole(o.alp)}</Text>
                  </View>
                  <Bar value={o.alp} max={officeMax} color={i === 0 && o.alp > 0 ? COLORS.gold : COLORS.primary} />
                </View>
              ))}
            </View>

            <Text style={styles.section}>BY DAY · SINCE {data.start_day.slice(5).replace('-', '/')}</Text>
            <View style={styles.list} testID="push-goal-by-day">
              {days.length === 0 ? (
                <Text style={styles.empty}>The campaign has not started yet.</Text>
              ) : days.map((d) => {
                const isToday = d.sales_day === data.today;
                const isBest = bestDay?.sales_day === d.sales_day && d.alp > 0;
                return (
                  <View key={d.sales_day} style={styles.row} testID={`push-goal-day-${d.sales_day}`}>
                    <View style={styles.rowHead}>
                      <Text style={[styles.rowName, styles.dayName, isToday && { color: COLORS.primary }]}>
                        {isToday ? 'TONIGHT' : fmtDay(d.sales_day)}
                      </Text>
                      {isBest ? (
                        <View style={styles.bestChip}><Text style={styles.bestTxt}>BEST NIGHT</Text></View>
                      ) : null}
                      <Text style={styles.rowSub}>{d.sales} {d.sales === 1 ? 'policy' : 'policies'}</Text>
                      <Text style={[styles.rowValue, d.alp === 0 && { color: COLORS.textMuted }]}>{fmtWhole(d.alp)}</Text>
                    </View>
                    <Bar value={d.alp} max={dayMax} color={isBest ? COLORS.gold : isToday ? COLORS.primary : COLORS.secondary} />
                  </View>
                );
              })}
            </View>
            <Text style={styles.footnote}>
              Gross ALP, all four offices, from the {data.start_day.slice(5).replace('-', '/')} sales day through {data.end_day.slice(5).replace('-', '/')}. Nights roll at 6 AM Eastern.
            </Text>
            <View style={{ height: 12 }} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <View style={[styles.stat, accent ? { borderTopColor: accent } : null]}>
      <Text style={styles.statLabel}>{label.toUpperCase()}</Text>
      <Text style={styles.statValue} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    maxHeight: '90%', backgroundColor: '#1A1A1A',
    borderTopLeftRadius: 16, borderTopRightRadius: 16,
    padding: 20, paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    borderTopWidth: 2, borderTopColor: COLORS.gold,
  },
  handle: { width: 36, height: 4, backgroundColor: COLORS.border, borderRadius: 2, alignSelf: 'center', marginBottom: 16 },
  head: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14 },
  kicker: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 2.2 },
  title: { color: '#fff', fontSize: 24, fontWeight: '900', letterSpacing: -0.6, marginTop: 4, fontVariant: ['tabular-nums'] },
  titleDim: { color: COLORS.textDim, fontSize: 13, letterSpacing: 1 },
  stats: { flexDirection: 'row', gap: 8, marginBottom: 6 },
  stat: {
    flex: 1, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderTopWidth: 2, borderTopColor: COLORS.secondary, borderRadius: 6, padding: 10,
  },
  statLabel: { color: COLORS.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.2 },
  statValue: { color: '#fff', fontSize: 17, fontWeight: '900', marginTop: 4, letterSpacing: -0.3, fontVariant: ['tabular-nums'] },
  section: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 2, marginTop: 16, marginBottom: 8 },
  list: { gap: 6 },
  row: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 10 },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  rank: { color: COLORS.textDim, fontSize: 12, fontWeight: '900', width: 14 },
  rowName: { flex: 1, color: '#fff', fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  dayName: { fontVariant: ['tabular-nums'] },
  rowSub: { color: COLORS.textMuted, fontSize: 10, fontWeight: '700' },
  rowValue: { color: '#fff', fontSize: 13, fontWeight: '900', fontVariant: ['tabular-nums'], minWidth: 70, textAlign: 'right' },
  bar: { height: 6, borderRadius: 3, backgroundColor: '#0A0A0A', overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3 },
  bestChip: { borderWidth: 1, borderColor: COLORS.gold, borderRadius: 3, paddingHorizontal: 5, paddingVertical: 1 },
  bestTxt: { color: COLORS.gold, fontSize: 8, fontWeight: '900', letterSpacing: 0.8 },
  empty: { color: COLORS.textDim, fontSize: 12, padding: 10 },
  footnote: { color: COLORS.textMuted, fontSize: 10, lineHeight: 15, marginTop: 14 },
});
