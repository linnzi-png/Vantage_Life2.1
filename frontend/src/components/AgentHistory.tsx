// Per-agent production history, shown inside the agent card.
//
// Reads /api/agents/{id}/history, which is gated by visible_agent_ids() — an
// agent may read their own history, an upline may read their downline. A 403
// here means the viewer is not entitled to this agent, so it renders nothing
// rather than an error: the card itself is still useful for contact details.
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, useWindowDimensions } from 'react-native';
import { api, ApiError, COLORS } from '../lib/auth';
import { LineChart, BarChart, Point } from './Charts';

export interface HistoryWeek {
  week_start: string;
  gross_alp: number;
  sits: number;
  sales: number;
  n1: number;
  close_rate: number;
  alp_per_sale: number;
}

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;
const compact = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `$${Math.round(n)}`;
const shortDate = (iso: string) => {
  const [, m, d] = iso.split('-');
  return `${Number(m)}/${Number(d)}`;
};

export function AgentHistory({ agentId, weeks = 13 }: { agentId: string; weeks?: number }) {
  const { width } = useWindowDimensions();
  const chartW = Math.min(width, 900) - 32 - 24;

  const [series, setSeries] = useState<HistoryWeek[] | null>(null);
  // Only a 403 means "not your team" and should hide the section entirely.
  // Anything else is a real failure and must say so — silently rendering
  // nothing on every error makes a missing endpoint look like a permissions
  // rule, which is impossible to diagnose from the UI.
  const [denied, setDenied] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const loading = loadedFor !== agentId && !denied && !failed;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api<{ series: HistoryWeek[] }>(
          `/api/agents/${encodeURIComponent(agentId)}/history?weeks=${weeks}`);
        if (cancelled) return;
        setSeries(r.series);
        setDenied(false);
        setFailed(null);
      } catch (e: unknown) {
        if (cancelled) return;
        setSeries(null);
        const status = e instanceof ApiError ? e.status : 0;
        setDenied(status === 403);
        setFailed(status === 403 ? null
          : e instanceof Error ? e.message : 'Could not load production history.');
      } finally {
        if (!cancelled) setLoadedFor(agentId);
      }
    })();
    return () => { cancelled = true; };
  }, [agentId, weeks]);

  if (denied) return null;
  if (loading) {
    return <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>;
  }
  if (failed) {
    return (
      <View style={styles.section}>
        <Text style={styles.kicker}>PRODUCTION HISTORY</Text>
        <Text style={styles.failed}>{failed}</Text>
      </View>
    );
  }
  if (!series || series.length === 0) {
    return (
      <View style={styles.section}>
        <Text style={styles.kicker}>PRODUCTION HISTORY</Text>
        <Text style={styles.empty}>No production recorded yet.</Text>
      </View>
    );
  }

  const totalAlp = series.reduce((n, w) => n + w.gross_alp, 0);
  const totalSales = series.reduce((n, w) => n + w.sales, 0);
  const totalSits = series.reduce((n, w) => n + w.sits, 0);
  // Close Rate = Sales / Sits. N1 (medically unqualified) is already left out
  // of Sits at entry, so subtracting it again would exclude them twice.
  const closeRate = totalSits > 0 ? (totalSales / totalSits) * 100 : 0;
  const best = series.reduce((m, w) => (w.gross_alp > m.gross_alp ? w : m), series[0]);

  const alpPoints: Point[] = series.map((w) => ({ label: shortDate(w.week_start), value: w.gross_alp }));
  const salesPoints: Point[] = series.map((w) => ({ label: shortDate(w.week_start), value: w.sales }));

  return (
    <View style={styles.section}>
      <Text style={styles.kicker}>PRODUCTION HISTORY · LAST {series.length} WEEKS</Text>

      <View style={styles.statRow}>
        <Stat label="ALP" value={money(totalAlp)} />
        <Stat label="SALES" value={`${totalSales}`} />
        <Stat label="CLOSE" value={`${closeRate.toFixed(1)}%`} />
        <Stat label="BEST WK" value={compact(best.gross_alp)} />
      </View>

      <Text style={styles.chartLab}>GROSS ALP BY WEEK</Text>
      <LineChart data={alpPoints} width={chartW} height={120} formatValue={compact} />

      <Text style={styles.chartLab}>SALES BY WEEK</Text>
      <BarChart data={salesPoints} width={chartW} height={100} />
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLab}>{label}</Text>
      <Text style={styles.statVal}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 14, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 12 },
  loading: { paddingVertical: 20, alignItems: 'center' },
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 10, letterSpacing: 1.4 },
  empty: { color: COLORS.textMuted, fontSize: 12, marginTop: 8 },
  failed: { color: COLORS.orange, fontSize: 12, marginTop: 8 },
  statRow: { flexDirection: 'row', gap: 6, marginTop: 10 },
  stat: { flex: 1, backgroundColor: COLORS.surface2, borderRadius: 6, padding: 8 },
  statLab: { color: COLORS.textMuted, fontSize: 8, fontWeight: '900', letterSpacing: 1 },
  statVal: { color: '#fff', fontSize: 14, fontWeight: '900', marginTop: 2 },
  chartLab: { color: COLORS.textDim, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 14, marginBottom: 6 },
});
