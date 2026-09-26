// The Team tab's date control (owner, 2026-09-24, replacing the Daily /
// Weekly / Monthly selector and the LIVE / week-chip row): one button that
// opens this sheet. "Month to date" is the default; below it a calendar where
// tapping two days selects a range (one day tapped twice is a single day). A
// reporting week or a whole past month is just a range the person selects.
// Previous / next month arrows; next is disabled at the current month and
// future days are disabled. Every date here is a SALES day and "today" is
// the server's sales_day, never the device clock — the 6 AM Detroit boundary
// is the backend's to define. AgentDayDetail reuses this sheet in place of
// its old "Pick a date" list.
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export type DateWindow =
  | { mode: 'mtd' }
  | { mode: 'range'; start: string; end: string };

export const MONTH_TO_DATE: DateWindow = { mode: 'mtd' };

interface Props {
  visible: boolean;
  /** The server's current sales day (YYYY-MM-DD). Nothing after it is selectable. */
  salesDay: string;
  value: DateWindow;
  /** Offer the "Month to date" row. Off for the agent card, which has no default window. */
  allowMonthToDate?: boolean;
  onChange: (next: DateWindow) => void;
  onClose: () => void;
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function pad(n: number): string { return n < 10 ? `0${n}` : `${n}`; }
function ymd(y: number, m: number, d: number): string { return `${y}-${pad(m)}-${pad(d)}`; }
function parts(day: string): { y: number; m: number; d: number } {
  const [y, m, d] = day.split('-').map(Number);
  return { y, m, d };
}
function daysInMonth(y: number, m: number): number { return new Date(y, m, 0).getDate(); }

/** "Sep 1 – Sep 24", "Sep 16", or "Month to date · Sep 1 – Sep 24" for the button label. */
export function describeWindow(value: DateWindow, salesDay: string, echoedStart?: string | null): string {
  const short = (day: string) => {
    const { m, d } = parts(day);
    return `${MONTHS[m - 1].slice(0, 3)} ${d}`;
  };
  if (value.mode === 'mtd') {
    const start = echoedStart || `${salesDay.slice(0, 7)}-01`;
    return `Month to date · ${short(start)} – ${short(salesDay)}`;
  }
  return value.start === value.end ? short(value.start) : `${short(value.start)} – ${short(value.end)}`;
}

export function TeamDateSheet({ visible, salesDay, value, allowMonthToDate = true, onChange, onClose }: Props) {
  const today = parts(salesDay);
  const [view, setView] = useState<{ y: number; m: number }>({ y: today.y, m: today.m });
  // The two taps in progress. `end` is null between the first tap and the second.
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);

  // Each open starts from the current selection and the month it ends in.
  useEffect(() => {
    if (!visible) return;
    const anchor = parts(value.mode === 'range' ? value.end : salesDay);
    // Seeding local edit state from props when the sheet opens, not deriving it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setView({ y: anchor.y, m: anchor.m });
    setStart(value.mode === 'range' ? value.start : null);
    setEnd(value.mode === 'range' ? value.end : null);
  }, [visible, value, salesDay]);

  const atCurrentMonth = view.y === today.y && view.m === today.m;

  const cells = useMemo(() => {
    const lead = new Date(view.y, view.m - 1, 1).getDay();
    const count = daysInMonth(view.y, view.m);
    const out: (string | null)[] = [];
    for (let i = 0; i < lead; i += 1) out.push(null);
    for (let d = 1; d <= count; d += 1) out.push(ymd(view.y, view.m, d));
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [view]);

  const tap = (day: string) => {
    if (day > salesDay) return;
    if (start && !end) {
      // Second tap closes the range; the earlier day is the start whichever
      // order they were tapped, and the same day twice is a single day.
      if (day < start) { setEnd(start); setStart(day); } else { setEnd(day); }
      return;
    }
    setStart(day);
    setEnd(null);
  };

  const inRange = (day: string) => {
    if (!start) return false;
    const hi = end ?? start;
    return day >= start && day <= hi;
  };

  const prevMonth = () => setView((v) => (v.m === 1 ? { y: v.y - 1, m: 12 } : { y: v.y, m: v.m - 1 }));
  const nextMonth = () => { if (!atCurrentMonth) setView((v) => (v.m === 12 ? { y: v.y + 1, m: 1 } : { y: v.y, m: v.m + 1 })); };

  const apply = () => {
    if (!start) return;
    onChange({ mode: 'range', start, end: end ?? start });
    onClose();
  };

  const pending = start ? (end ? `${start === end ? start : `${start} to ${end}`}` : `${start} · tap the last day`) : 'Tap a day, then the last day of the range';

  // The sheet is mounted from the first render of the Team tab and the agent
  // card, before /api/team has answered, so salesDay is still '' and `today`
  // is NaN. Building the calendar JSX below would then index MONTHS with NaN
  // and crash the whole screen (seen on the web build, 2026-09-26) even
  // though the Modal was hidden — React evaluates the children eagerly.
  // Nothing is worth drawing until the sheet is open with a real day.
  if (!visible || !salesDay) return null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>DATES</Text>

          {allowMonthToDate ? (
            <TouchableOpacity
              style={[styles.mtdRow, value.mode === 'mtd' && styles.mtdRowOn]}
              onPress={() => { onChange(MONTH_TO_DATE); onClose(); }}
              testID="team-date-mtd"
            >
              <Ionicons name="calendar" size={16} color={value.mode === 'mtd' ? '#000' : COLORS.primary} />
              <Text style={[styles.mtdTxt, value.mode === 'mtd' && styles.mtdTxtOn]}>MONTH TO DATE</Text>
              {value.mode === 'mtd' ? <Ionicons name="checkmark" size={16} color="#000" /> : null}
            </TouchableOpacity>
          ) : null}

          <View style={styles.monthRow}>
            <TouchableOpacity onPress={prevMonth} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} testID="team-date-prev">
              <Ionicons name="chevron-back" size={20} color={COLORS.textDim} />
            </TouchableOpacity>
            <Text style={styles.monthTxt}>{MONTHS[view.m - 1].toUpperCase()} {view.y}</Text>
            <TouchableOpacity
              onPress={nextMonth}
              disabled={atCurrentMonth}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              testID="team-date-next"
            >
              <Ionicons name="chevron-forward" size={20} color={atCurrentMonth ? COLORS.border : COLORS.textDim} />
            </TouchableOpacity>
          </View>

          <View style={styles.week}>
            {WEEKDAYS.map((w, i) => <Text key={`${w}${i}`} style={styles.weekday}>{w}</Text>)}
          </View>
          <View style={styles.grid}>
            {cells.map((day, i) => {
              if (!day) return <View key={`blank-${i}`} style={styles.cell} />;
              const future = day > salesDay;
              const on = inRange(day);
              const edge = day === start || day === (end ?? start);
              return (
                <TouchableOpacity
                  key={day}
                  style={[styles.cell, on && styles.cellOn, edge && on && styles.cellEdge]}
                  disabled={future}
                  onPress={() => tap(day)}
                  testID={`team-date-${day}`}
                >
                  <Text style={[styles.cellTxt, future && styles.cellTxtFuture, on && styles.cellTxtOn, day === salesDay && !on && styles.cellTxtToday]}>
                    {parts(day).d}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={styles.pending} testID="team-date-pending">{pending}</Text>

          <View style={styles.actions}>
            <TouchableOpacity style={styles.cancel} onPress={onClose}>
              <Text style={styles.cancelTxt}>CANCEL</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.applyBtn, !start && { opacity: 0.4 }]} onPress={apply} disabled={!start} testID="team-date-apply">
              <Text style={styles.applyTxt}>{start && (!end || start === end) ? 'SHOW THIS DAY' : 'SHOW RANGE'}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    backgroundColor: '#111', borderTopLeftRadius: 18, borderTopRightRadius: 18,
    padding: 18, paddingBottom: 28, borderTopWidth: 1, borderColor: COLORS.border,
  },
  handle: { width: 38, height: 4, borderRadius: 2, backgroundColor: COLORS.border, alignSelf: 'center', marginBottom: 12 },
  title: { color: COLORS.primary, fontWeight: '900', fontSize: 12, letterSpacing: 1.6, marginBottom: 10 },
  mtdRow: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 10, padding: 12, marginBottom: 12,
  },
  mtdRowOn: { backgroundColor: COLORS.gold, borderColor: COLORS.gold },
  mtdTxt: { flex: 1, color: '#fff', fontWeight: '900', fontSize: 12, letterSpacing: 1 },
  mtdTxtOn: { color: '#000' },
  monthRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 4, marginBottom: 6 },
  monthTxt: { color: '#fff', fontWeight: '900', fontSize: 13, letterSpacing: 1.2 },
  week: { flexDirection: 'row' },
  weekday: { flex: 1, textAlign: 'center', color: COLORS.textMuted, fontSize: 10, fontWeight: '900', paddingVertical: 4 },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  cell: { width: `${100 / 7}%`, aspectRatio: 1.25, alignItems: 'center', justifyContent: 'center' },
  cellOn: { backgroundColor: 'rgba(255,215,0,0.18)' },
  cellEdge: { backgroundColor: COLORS.gold, borderRadius: 8 },
  cellTxt: { color: '#fff', fontSize: 13, fontWeight: '700' },
  cellTxtFuture: { color: COLORS.border },
  cellTxtOn: { color: '#000', fontWeight: '900' },
  cellTxtToday: { color: COLORS.primary, fontWeight: '900' },
  pending: { color: COLORS.textDim, fontSize: 11, marginTop: 8, fontStyle: 'italic' },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 12 },
  cancel: { flex: 1, alignItems: 'center', paddingVertical: 12 },
  cancelTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1 },
  applyBtn: { flex: 1.4, alignItems: 'center', paddingVertical: 12, borderRadius: 10, backgroundColor: COLORS.primary },
  applyTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 1 },
});
