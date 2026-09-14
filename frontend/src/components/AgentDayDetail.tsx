// Single-day drill-down for the agent card — lets a leader pick any recent
// sales day and see exactly what that agent submitted that day, field by
// field. Reads GET /api/agents/{id}/day, which mirrors agent_history's RBAC
// (self or downline only, via visible_agent_ids()) and is read-only: there is
// no correction path here — that stays on the self-correction screen and the
// Manager Eraser, both untouched by this component.
import React, { useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { PULSE_FIELDS, recentSalesDaysDetroit, currentSalesDayDetroit } from '../lib/cycle';

// How far back the picker reaches. Matches the window AgentHistory already
// pulls (13 weeks ≈ 91 days) so a leader can drill into any day the chart
// above is already showing.
const DAY_WINDOW = 90;

interface AgentDay {
  sales_day: string;
  totals: Record<string, number>;
  close_rate: number;
  show_rate: number;
  alp_per_sale: number;
  has_entries: boolean;
  entry_count: number;
}

const money = (n: number) => `$${Math.round(n || 0).toLocaleString()}`;

function fmtDay(d: string): string {
  const [y, m, dd] = d.split('-').map(Number);
  const date = new Date(y, (m || 1) - 1, dd || 1);
  return `${d} · ${date.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()}`;
}

export function AgentDayDetail({ agentId }: { agentId: string }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickedDay, setPickedDay] = useState<string | null>(null);
  const [day, setDay] = useState<AgentDay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Newest-first, anchored on the currently open sales day in Detroit — the
  // zone the backend defines a sales_day in, not the device's. Rebuilt every
  // time the picker opens rather than memoized once: a card left open across
  // the 6 AM boundary would otherwise keep labelling yesterday as TODAY and
  // never offer the day that just opened.
  const [dayOptions, setDayOptions] = useState<string[]>(() => recentSalesDaysDetroit(DAY_WINDOW));
  const [today, setToday] = useState<string>(() => currentSalesDayDetroit());

  const openPicker = () => {
    setDayOptions(recentSalesDaysDetroit(DAY_WINDOW));
    setToday(currentSalesDayDetroit());
    setPickerOpen(true);
  };

  // Picking a second date before the first request lands would otherwise race:
  // whichever response arrived last won, so a slow connection could show one
  // day's production under another day's label. Only the newest request may
  // write state.
  const reqRef = useRef(0);

  const pick = async (d: string) => {
    setPickerOpen(false);
    setPickedDay(d);
    setDay(null);
    setError(null);
    setLoading(true);
    const seq = ++reqRef.current;
    try {
      const r = await api<AgentDay>(`/api/agents/${encodeURIComponent(agentId)}/day?sales_day=${d}`);
      if (seq === reqRef.current) setDay(r);
    } catch (e: unknown) {
      if (seq === reqRef.current) setError(e instanceof Error ? e.message : 'Could not load that day.');
    } finally {
      if (seq === reqRef.current) setLoading(false);
    }
  };

  return (
    <View style={styles.section}>
      <Text style={styles.kicker}>WHAT THEY SUBMITTED ON A SPECIFIC DAY</Text>
      <TouchableOpacity style={styles.dayPill} onPress={openPicker} testID="agent-day-picker-open">
        <Ionicons name="calendar-outline" size={13} color={COLORS.gold} />
        <Text style={styles.dayPillTxt}>{pickedDay ? fmtDay(pickedDay) : 'PICK A DATE'}</Text>
        <Ionicons name="chevron-down" size={11} color={COLORS.textDim} />
      </TouchableOpacity>

      {loading ? <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View> : null}
      {error ? <Text style={styles.failed}>{error}</Text> : null}

      {day && !loading && !error ? (
        day.has_entries ? (
          <View style={styles.dayCard} testID="agent-day-result">
            <View style={styles.dayStatRow}>
              <MiniStat label="ALP" value={money(day.totals.gross_alp)} />
              <MiniStat label="SALES" value={`${day.totals.sales ?? 0}`} />
              <MiniStat label="CLOSE" value={`${day.close_rate.toFixed(1)}%`} />
              <MiniStat label="SIT RATE" value={`${day.show_rate.toFixed(1)}%`} />
            </View>
            <View style={styles.fieldList}>
              {PULSE_FIELDS.map((f, i) => (
                <View
                  key={f.key}
                  style={[styles.fieldRow, i === PULSE_FIELDS.length - 1 && { borderBottomWidth: 0 }]}
                >
                  <Text style={styles.fieldLabel}>{f.label}</Text>
                  <Text style={styles.fieldValue}>
                    {f.type === 'money' ? money(day.totals[f.key]) : `${day.totals[f.key] ?? 0}`}
                  </Text>
                </View>
              ))}
            </View>
            {day.entry_count > 1 ? (
              <Text style={styles.note}>
                {day.entry_count} submissions make up this total — likely a correction or an upline proxy entry on top of the original.
              </Text>
            ) : null}
          </View>
        ) : (
          <Text style={styles.empty}>Nothing submitted for {pickedDay}.</Text>
        )
      ) : null}

      <Modal visible={pickerOpen} transparent animationType="fade" onRequestClose={() => setPickerOpen(false)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setPickerOpen(false)}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>PICK A DAY · LAST {DAY_WINDOW} DAYS</Text>
            <ScrollView style={{ maxHeight: 420 }}>
              {dayOptions.map((d) => {
                const isToday = d === today;
                const isPicked = pickedDay === d;
                return (
                  <TouchableOpacity
                    key={d}
                    style={styles.dayRow}
                    onPress={() => pick(d)}
                    testID={`agent-day-option-${d}`}
                  >
                    <Text style={[styles.dayRowTxt, isToday && { color: COLORS.primary, fontWeight: '900' }]}>
                      {fmtDay(d)}{isToday ? ' · TODAY' : ''}
                    </Text>
                    {isPicked ? <Ionicons name="checkmark" size={14} color={COLORS.gold} /> : null}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLab}>{label}</Text>
      <Text style={styles.statVal}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 14, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 12 },
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 10, letterSpacing: 1.4, marginBottom: 8 },
  dayPill: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
    backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7,
  },
  dayPillTxt: { color: '#fff', fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  loading: { paddingVertical: 16, alignItems: 'center' },
  failed: { color: COLORS.orange, fontSize: 12, marginTop: 10 },
  empty: { color: COLORS.textMuted, fontSize: 12, marginTop: 10, fontStyle: 'italic' },
  dayCard: { marginTop: 10 },
  dayStatRow: { flexDirection: 'row', gap: 6 },
  stat: { flex: 1, backgroundColor: COLORS.surface2, borderRadius: 6, padding: 8 },
  statLab: { color: COLORS.textMuted, fontSize: 8, fontWeight: '900', letterSpacing: 1 },
  statVal: { color: '#fff', fontSize: 14, fontWeight: '900', marginTop: 2 },
  fieldList: { marginTop: 10, backgroundColor: COLORS.surface, borderRadius: 8, borderWidth: 1, borderColor: COLORS.border },
  fieldRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 12, paddingVertical: 9,
    borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  fieldLabel: { color: COLORS.textDim, fontSize: 12, flex: 1, paddingRight: 8 },
  fieldValue: { color: '#fff', fontSize: 13, fontWeight: '800' },
  note: { color: COLORS.textMuted, fontSize: 11, marginTop: 8, fontStyle: 'italic' },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', padding: 24 },
  modalCard: { backgroundColor: '#1A1A1A', borderRadius: 12, padding: 16, borderWidth: 1, borderColor: COLORS.border },
  modalTitle: { color: COLORS.primary, fontWeight: '900', fontSize: 12, letterSpacing: 1, marginBottom: 10 },
  dayRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  dayRowTxt: { color: '#fff', fontSize: 13, fontWeight: '700' },
});
