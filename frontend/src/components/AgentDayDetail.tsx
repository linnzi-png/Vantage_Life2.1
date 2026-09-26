// Day-or-range drill-down for the agent card — lets a leader pick any sales
// day, or any range of days, and see exactly what that agent submitted,
// field by field, summed over the window. Reads GET /api/agents/{id}/day
// (start_day / end_day, owner 2026-09-24), which mirrors agent_history's
// RBAC (self or downline only, via team_scope_agent_ids()) and is read-only:
// there is no correction path here — that stays on the self-correction
// screen and the Manager Eraser, both untouched by this component. The
// calendar is the Team tab's own TeamDateSheet; "today" is the server's
// sales_day, never the device clock.
import React, { useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';
import { PULSE_FIELDS } from '../lib/cycle';
import { TeamDateSheet, DateWindow, describeWindow } from './TeamDateSheet';

interface AgentDay {
  sales_day: string;
  start_day?: string;
  end_day?: string;
  totals: Record<string, number>;
  close_rate: number;
  show_rate: number;
  alp_per_sale: number;
  has_entries: boolean;
  entry_count: number;
}

const money = (n: number) => `$${Math.round(n || 0).toLocaleString()}`;

export function AgentDayDetail({ agentId }: { agentId: string }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState<DateWindow | null>(null);
  const [day, setDay] = useState<AgentDay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The server's current sales day, read from the route itself (no dates =
  // the current day) so the calendar never trusts the device clock. Fetched
  // every time the picker opens, not once per mount: a card left open across
  // the 6 AM Detroit boundary would otherwise keep yesterday as "today" and
  // refuse the day that just opened, and one failed request would leave the
  // button dead for the rest of the mount.
  const [salesDay, setSalesDay] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const openPicker = async () => {
    if (opening) return;
    setOpening(true);
    try {
      const r = await api<AgentDay>(`/api/agents/${encodeURIComponent(agentId)}/day`);
      setSalesDay(r.sales_day);
      setPickerOpen(true);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not open the calendar. Try again.');
    } finally {
      setOpening(false);
    }
  };

  // Picking a second window before the first request lands would otherwise
  // race: whichever response arrived last won, so a slow connection could
  // show one window's production under another's label. Only the newest
  // request may write state.
  const reqRef = useRef(0);

  const pick = async (w: DateWindow) => {
    if (w.mode !== 'range') return;
    setPicked(w);
    setDay(null);
    setError(null);
    setLoading(true);
    const seq = ++reqRef.current;
    try {
      const r = await api<AgentDay>(
        `/api/agents/${encodeURIComponent(agentId)}/day?start_day=${w.start}&end_day=${w.end}`);
      if (seq === reqRef.current) setDay(r);
    } catch (e: unknown) {
      if (seq === reqRef.current) setError(e instanceof Error ? e.message : 'Could not load those days.');
    } finally {
      if (seq === reqRef.current) setLoading(false);
    }
  };

  const label = picked && salesDay ? describeWindow(picked, salesDay).toUpperCase() : 'PICK A DAY OR RANGE';

  return (
    <View style={styles.section}>
      <Text style={styles.kicker}>WHAT THEY SUBMITTED</Text>
      <TouchableOpacity
        style={[styles.dayPill, opening && { opacity: 0.6 }]}
        onPress={openPicker}
        disabled={opening}
        testID="agent-day-picker-open"
      >
        <Ionicons name="calendar-outline" size={13} color={COLORS.gold} />
        <Text style={styles.dayPillTxt}>{label}</Text>
        {opening ? <ActivityIndicator size="small" color={COLORS.textDim} /> : <Ionicons name="chevron-down" size={11} color={COLORS.textDim} />}
      </TouchableOpacity>

      {loading ? <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View> : null}
      {error ? <Text style={styles.failed}>{error}</Text> : null}

      {day && !loading && !error ? (
        day.has_entries ? (
          <View style={styles.dayCard} testID="agent-day-result">
            <View style={styles.dayStatRow}>
              <MiniStat label="ALP" value={money(day.totals.gross_alp)} />
              <MiniStat label="SALES" value={`${day.totals.sales ?? 0}`} />
              <MiniStat label="CLOSE RATIO" value={`${day.close_rate.toFixed(1)}%`} />
              <MiniStat label="SHOW RATIO" value={`${day.show_rate.toFixed(1)}%`} />
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
                {day.entry_count} submissions make up this total{day.start_day && day.end_day && day.start_day !== day.end_day
                  ? ' across these days.'
                  : ' — likely a correction or an upline proxy entry on top of the original.'}
              </Text>
            ) : null}
          </View>
        ) : (
          <Text style={styles.empty}>Nothing submitted for {label.toLowerCase()}.</Text>
        )
      ) : null}

      <TeamDateSheet
        visible={pickerOpen && !!salesDay}
        salesDay={salesDay || ''}
        value={picked ?? { mode: 'mtd' }}
        allowMonthToDate={false}
        onChange={pick}
        onClose={() => setPickerOpen(false)}
      />
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
});
