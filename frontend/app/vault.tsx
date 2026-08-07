// Company Health — production trends per office, plus the archived-week
// comparison and WAR export. Level 4 only.
//
// Trends come from /api/vault/trends (aggregated production_entries), not from
// historical_vault snapshots: snapshots store only ALP/sits/sales, so Close Rate
// could not exclude N1 from them, and they only exist for weeks that were
// actually closed out by a Wednesday reset.
import React, { useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform, Share,
  ActivityIndicator, useWindowDimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS } from '../src/lib/auth';
import { TourAnchor } from '../src/components/TourAnchor';
import { notify } from '../src/lib/dialog';
import { LineChart, BarChart, Point } from '../src/components/Charts';

interface WeekTotals {
  gross_alp?: number;
  net_alp?: number;
  sales?: number;
  sits?: number;
}
interface Week {
  week_id: string;
  week_start: string;
  archived_at: string;
  totals: WeekTotals;
  agent_count: number;
}
interface TrendWeek {
  week_start: string;
  gross_alp: number;
  net_alp: number;
  sets: number;
  sits: number;
  sales: number;
  n1: number;
  close_rate: number;
  show_rate: number;
  alp_per_sale: number;
  agent_count: number;
  office_count: number;
}
interface DeltaEntry { a: number; b: number; delta: number; pct: number; }
interface Compare {
  a: Week;
  b: Week;
  delta: Record<string, DeltaEntry>;
}

const RANGES = [
  { key: 8, label: '8W' },
  { key: 13, label: '13W' },
  { key: 26, label: '26W' },
  { key: 0, label: 'ALL' },
] as const;

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;
const compact = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `$${Math.round(n)}`;
// "2026-06-10" -> "6/10"
const shortDate = (iso: string) => {
  const [, m, d] = iso.split('-');
  return `${Number(m)}/${Number(d)}`;
};

export default function VaultScreen() {
  const { width } = useWindowDimensions();
  const chartW = Math.min(width, 900) - 32 - 28; // screen padding + card padding

  const [offices, setOffices] = useState<string[]>([]);
  const [office, setOffice] = useState<string | null>(null);
  const [series, setSeries] = useState<TrendWeek[]>([]);
  // Sentinel: `undefined` = nothing loaded yet, distinct from a null office.
  const [loadedFor, setLoadedFor] = useState<string | null | undefined>(undefined);
  const [range, setRange] = useState<number>(13);

  const [weeks, setWeeks] = useState<Week[]>([]);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  // Offices come from the data — never a hardcoded list.
  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ offices: string[] }>('/api/vault/offices');
        setOffices(r.offices);
        setOffice(r.offices[0] ?? null);
      } catch {
        setOffices([]);
      }
    })();
  }, []);

  // Loading is derived, not set synchronously in the effect: whenever the
  // office we last loaded for differs from the selected one, we are loading.
  // Setting a loading flag in the effect body triggers a cascading render.
  const loading = loadedFor !== office;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const q = office ? `?office=${encodeURIComponent(office)}` : '';
      try {
        const r = await api<{ series: TrendWeek[] }>(`/api/vault/trends${q}`);
        if (cancelled) return;
        setSeries(r.series);
      } catch (e: unknown) {
        if (cancelled) return;
        notify('Could not load trends', e instanceof Error ? e.message : 'Please try again.');
        setSeries([]);
      } finally {
        // Marks this office as resolved even on failure, so a failed load shows
        // the empty state instead of spinning forever.
        if (!cancelled) setLoadedFor(office);
      }
    })();
    return () => { cancelled = true; };
  }, [office]);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ weeks: Week[] }>('/api/vault/weeks');
        setWeeks(r.weeks);
      } catch {}
    })();
  }, []);

  useEffect(() => {
    if (a && b && a !== b) {
      api<Compare>(`/api/vault/compare?week_a=${a}&week_b=${b}`).then(setCmp).catch(() => setCmp(null));
    } else { setCmp(null); }
  }, [a, b]);

  const shown = useMemo(
    () => (range > 0 ? series.slice(-range) : series),
    [series, range],
  );

  const kpi = useMemo(() => {
    if (shown.length === 0) return null;
    const totalAlp = shown.reduce((n, w) => n + w.gross_alp, 0);
    const totalSales = shown.reduce((n, w) => n + w.sales, 0);
    const totalSits = shown.reduce((n, w) => n + w.sits, 0);
    const totalN1 = shown.reduce((n, w) => n + w.n1, 0);
    const eligible = totalSits - totalN1; // N1 excluded per business rule
    const last = shown[shown.length - 1];
    const prev = shown.length > 1 ? shown[shown.length - 2] : null;
    const wow = prev && prev.gross_alp > 0
      ? ((last.gross_alp - prev.gross_alp) / prev.gross_alp) * 100
      : null;
    const best = shown.reduce((m, w) => (w.gross_alp > m.gross_alp ? w : m), shown[0]);
    return {
      totalAlp,
      totalSales,
      avgWeek: totalAlp / shown.length,
      closeRate: eligible > 0 ? (totalSales / eligible) * 100 : 0,
      alpPerSale: totalSales > 0 ? totalAlp / totalSales : 0,
      last,
      wow,
      best,
    };
  }, [shown]);

  const alpPoints: Point[] = useMemo(
    () => shown.map((w) => ({ label: shortDate(w.week_start), value: w.gross_alp })), [shown]);
  const salesPoints: Point[] = useMemo(
    () => shown.map((w) => ({ label: shortDate(w.week_start), value: w.sales })), [shown]);
  const closePoints: Point[] = useMemo(
    () => shown.map((w) => ({ label: shortDate(w.week_start), value: w.close_rate })), [shown]);

  const exportWeek = async (weekStart: string) => {
    setExporting(weekStart);
    try {
      const data = await api<unknown>(`/api/vault/export?week_start=${weekStart}`);
      const json = JSON.stringify(data, null, 2);
      const filename = `war_export_${weekStart}.json`;
      if (Platform.OS === 'web' && typeof document !== 'undefined') {
        const href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
        const link = document.createElement('a');
        link.href = href; link.download = filename; link.click();
        URL.revokeObjectURL(href);
      } else {
        await Share.share({ message: json, title: filename });
      }
    } catch (e: unknown) {
      notify('Export failed', e instanceof Error ? e.message : 'Could not export this week.');
    } finally {
      setExporting(null);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'COMPANY HEALTH', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>

        {/* Office tabs — one per office with production data. */}
        {offices.length > 0 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
            {offices.map((o) => {
              const sel = o === office;
              return (
                <TouchableOpacity
                  key={o}
                  onPress={() => setOffice(o)}
                  style={[styles.tab, sel && styles.tabOn]}
                  testID={`vault-office-${o}`}
                >
                  <Text style={[styles.tabTxt, sel && styles.tabTxtOn]}>{o.toUpperCase()}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        ) : null}

        <View style={styles.rangeRow}>
          {RANGES.map((r) => (
            <TouchableOpacity
              key={r.label}
              onPress={() => setRange(r.key)}
              style={[styles.rangeBtn, range === r.key && styles.rangeBtnOn]}
              testID={`vault-range-${r.label}`}
            >
              <Text style={[styles.rangeTxt, range === r.key && styles.rangeTxtOn]}>{r.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {loading ? (
          <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>
        ) : !kpi ? (
          <View style={styles.card}>
            <Text style={styles.emptyTxt}>No production data for this office yet.</Text>
          </View>
        ) : (
          <>
            {/* Headline: latest week + week-over-week move. */}
            <View style={styles.heroCard} testID="vault-hero">
              <Text style={styles.heroLabel}>WEEK OF {kpi.last.week_start}</Text>
              <Text style={styles.heroValue}>{money(kpi.last.gross_alp)}</Text>
              <View style={styles.heroRow}>
                {kpi.wow !== null ? (
                  <View style={[styles.pill, { backgroundColor: kpi.wow >= 0 ? 'rgba(49,152,66,0.15)' : 'rgba(255,59,48,0.15)' }]}>
                    <Ionicons name={kpi.wow >= 0 ? 'arrow-up' : 'arrow-down'} size={11} color={kpi.wow >= 0 ? COLORS.primary : COLORS.red} />
                    <Text style={[styles.pillTxt, { color: kpi.wow >= 0 ? COLORS.primary : COLORS.red }]}>
                      {kpi.wow >= 0 ? '+' : ''}{kpi.wow.toFixed(1)}% vs prior week
                    </Text>
                  </View>
                ) : null}
                <Text style={styles.heroMeta}>
                  {kpi.last.sales} sales · {kpi.last.agent_count} agents
                </Text>
              </View>
            </View>

            <View style={styles.kpiGrid}>
              <Kpi label="PERIOD ALP" value={money(kpi.totalAlp)} />
              <Kpi label="AVG / WEEK" value={money(kpi.avgWeek)} />
              <Kpi label="SALES" value={kpi.totalSales.toLocaleString()} />
              <Kpi label="CLOSE RATE" value={`${kpi.closeRate.toFixed(1)}%`} hint="N1 excluded" />
              <Kpi label="ALP / SALE" value={money(kpi.alpPerSale)} />
              <Kpi label="BEST WEEK" value={compact(kpi.best.gross_alp)} hint={kpi.best.week_start} />
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>GROSS ALP BY WEEK</Text>
              <LineChart data={alpPoints} width={chartW} formatValue={compact} />
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>SALES BY WEEK</Text>
              <BarChart data={salesPoints} width={chartW} />
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>CLOSE RATE BY WEEK</Text>
              <Text style={styles.cardNote}>Sales ÷ (Sits − N1) — N1 excluded per business rule.</Text>
              <LineChart data={closePoints} width={chartW} color={COLORS.gold} formatValue={(n) => `${n}%`} />
            </View>
          </>
        )}

        {/* Archived-week snapshots: comparison + WAR export. */}
        <TourAnchor id="vault-weeks">
          <Text style={[styles.kicker, { marginTop: 20 }]}>ARCHIVED WEEK SNAPSHOTS</Text>
          <Text style={styles.intro}>
            Created by the Wednesday reset. Pick two to compare side-by-side, or export one as a WAR-format backup.
          </Text>
        </TourAnchor>

        {weeks.length === 0 ? (
          <Text style={styles.emptyTxt}>No archived snapshots yet.</Text>
        ) : (
          <View style={styles.weekGrid}>
            {weeks.map((w) => {
              const isA = a === w.week_start; const isB = b === w.week_start;
              return (
                <TouchableOpacity
                  key={w.week_id}
                  onPress={() => {
                    if (isA) setA(null);
                    else if (isB) setB(null);
                    else if (!a) setA(w.week_start);
                    else if (!b) setB(w.week_start);
                    else setA(w.week_start); // replace A
                  }}
                  style={[styles.weekCard, (isA || isB) && { borderColor: isA ? COLORS.primary : COLORS.gold, borderWidth: 2 }]}
                  testID={`vault-week-${w.week_start}`}
                >
                  {isA ? <View style={[styles.tag, { backgroundColor: COLORS.primary }]}><Text style={styles.tagTxt}>A</Text></View> : null}
                  {isB ? <View style={[styles.tag, { backgroundColor: COLORS.gold }]}><Text style={styles.tagTxt}>B</Text></View> : null}
                  <Text style={styles.weekDate}>{w.week_start}</Text>
                  <Text style={styles.weekAlp}>{money(w.totals?.gross_alp || 0)}</Text>
                  <Text style={styles.weekMeta}>{w.totals?.sales || 0} sales · {w.agent_count} agents</Text>
                  <TouchableOpacity
                    onPress={() => exportWeek(w.week_start)}
                    disabled={exporting === w.week_start}
                    style={styles.exportBtn}
                    testID={`vault-export-${w.week_start}`}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  >
                    <Ionicons name="download-outline" size={12} color={COLORS.primary} />
                    <Text style={styles.exportTxt}>{exporting === w.week_start ? 'EXPORTING…' : 'EXPORT'}</Text>
                  </TouchableOpacity>
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {cmp ? (
          <View style={styles.compareCard} testID="vault-compare">
            <Text style={styles.kicker}>WEEK COMPARISON</Text>
            <View style={styles.cmpHeader}>
              <Text style={[styles.cmpCol, { color: COLORS.primary }]}>A · {cmp.a.week_start}</Text>
              <Text style={[styles.cmpCol, { color: COLORS.gold, textAlign: 'right' }]}>B · {cmp.b.week_start}</Text>
            </View>
            {(['gross_alp', 'net_alp', 'sales', 'sits'] as const).map((m) => {
              const d = cmp.delta[m];
              if (!d) return null;
              const pos = d.delta >= 0;
              const isMoney = m === 'gross_alp' || m === 'net_alp';
              return (
                <View key={m} style={styles.cmpRow}>
                  <Text style={styles.cmpLab}>{m.replace('_', ' ').toUpperCase()}</Text>
                  <View style={styles.cmpValues}>
                    <Text style={styles.cmpAVal}>{isMoney ? money(d.a) : Math.round(d.a).toLocaleString()}</Text>
                    <View style={[styles.deltaPill, { backgroundColor: pos ? 'rgba(49,152,66,0.15)' : 'rgba(255,59,48,0.15)' }]}>
                      <Ionicons name={pos ? 'arrow-up' : 'arrow-down'} size={11} color={pos ? COLORS.primary : COLORS.red} />
                      <Text style={[styles.deltaPillTxt, { color: pos ? COLORS.primary : COLORS.red }]}>{pos ? '+' : ''}{d.pct.toFixed(1)}%</Text>
                    </View>
                    <Text style={styles.cmpBVal}>{isMoney ? money(d.b) : Math.round(d.b).toLocaleString()}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <View style={styles.kpi}>
      <Text style={styles.kpiLab}>{label}</Text>
      <Text style={styles.kpiVal}>{value}</Text>
      {hint ? <Text style={styles.kpiHint}>{hint}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  loading: { padding: 40, alignItems: 'center' },
  emptyTxt: { color: COLORS.textMuted, fontSize: 12, paddingVertical: 12 },

  tabs: { gap: 6, paddingBottom: 4 },
  tab: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  tabOn: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  tabTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '800' },
  tabTxtOn: { color: '#fff' },

  rangeRow: { flexDirection: 'row', gap: 6, marginTop: 12 },
  rangeBtn: { flex: 1, alignItems: 'center', paddingVertical: 7, borderRadius: 6, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  rangeBtnOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  rangeTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '900' },
  rangeTxtOn: { color: '#000' },

  heroCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopWidth: 2, borderTopColor: COLORS.gold, borderRadius: 6, padding: 16, marginTop: 12 },
  heroLabel: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  heroValue: { color: '#fff', fontSize: 34, fontWeight: '900', marginTop: 4 },
  heroRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8, flexWrap: 'wrap' },
  heroMeta: { color: COLORS.textDim, fontSize: 12 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 12 },
  pillTxt: { fontWeight: '900', fontSize: 11 },

  kpiGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  kpi: { width: '31.5%', minWidth: 100, flexGrow: 1, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 10 },
  kpiLab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  kpiVal: { color: '#fff', fontSize: 17, fontWeight: '900', marginTop: 3 },
  kpiHint: { color: COLORS.textMuted, fontSize: 9, marginTop: 1 },

  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 12 },
  cardTitle: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.4, marginBottom: 8 },
  cardNote: { color: COLORS.textMuted, fontSize: 10, marginTop: -4, marginBottom: 8 },

  weekGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  weekCard: { width: '48%', flexGrow: 1, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 12 },
  weekDate: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  weekAlp: { color: '#fff', fontSize: 18, fontWeight: '900', marginTop: 4 },
  weekMeta: { color: COLORS.textMuted, fontSize: 10, marginTop: 2 },
  exportBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8, alignSelf: 'flex-start', borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 5 },
  exportTxt: { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  tag: { position: 'absolute', top: 6, right: 6, width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  tagTxt: { color: '#000', fontWeight: '900', fontSize: 11 },

  compareCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopWidth: 2, borderTopColor: COLORS.primary, borderRadius: 6, padding: 14, marginTop: 16 },
  cmpHeader: { flexDirection: 'row', justifyContent: 'space-between', marginVertical: 8 },
  cmpCol: { fontWeight: '900', fontSize: 11, letterSpacing: 1, flex: 1 },
  cmpRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  cmpLab: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  cmpValues: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, gap: 6 },
  cmpAVal: { color: '#fff', fontWeight: '900', fontSize: 13, flex: 1 },
  cmpBVal: { color: '#fff', fontWeight: '900', fontSize: 13, flex: 1, textAlign: 'right' },
  deltaPill: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12 },
  deltaPillTxt: { fontWeight: '900', fontSize: 11 },
});
