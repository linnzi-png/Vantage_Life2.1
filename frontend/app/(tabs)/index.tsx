// Executive Dashboard — default screen
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, roleTitle } from '../../src/lib/auth';
import StatCard from '../../src/components/StatCard';
import PlatinumWall from '../../src/components/PlatinumWall';
import OfficeTabs, { OfficeRow } from '../../src/components/OfficeTabs';
import GateBanner from '../../src/components/GateBanner';
import Ticker, { TickerItem } from '../../src/components/Ticker';

interface Summary {
  total_alp: number; total_net_alp: number; total_sits: number; total_sales: number;
  delta_pct_vs_yesterday: number; sales_day: string; gate: any; is_full_agency: boolean;
}

export default function DashboardScreen() {
  const { user, agent, roleLabel } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [ticker, setTicker] = useState<TickerItem[]>([]);
  const [vets, setVets] = useState<any[]>([]);
  const [rookies, setRookies] = useState<any[]>([]);
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [s, t, p, o] = await Promise.all([
        api<Summary>('/api/dashboard/summary'),
        api<{ items: TickerItem[] }>('/api/dashboard/ticker'),
        api<{ vets: any[]; rookies: any[] }>('/api/dashboard/platinum-wall'),
        api<{ offices: OfficeRow[] }>('/api/dashboard/offices'),
      ]);
      setSummary(s); setTicker(t.items); setVets(p.vets); setRookies(p.rookies); setOffices(o.offices);
    } catch (e) {
      console.warn('Dashboard fetch error:', e);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000); // 30s polling for live ticker
    return () => clearInterval(interval);
  }, [fetchAll]);

  const onRefresh = async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); };

  const fmtMoney = (n: number) => `$${Math.round(n).toLocaleString()}`;

  if (!user?.agent_id) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={36} color={COLORS.orange} />
          <Text style={styles.notLinked}>This account isn't linked to an agent profile yet.</Text>
          <Text style={styles.notLinkedSub}>Try the Demo Login screen and pick "AGENT" to test the Pulse flow.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header} testID="dashboard-header">
        <View>
          <Text style={styles.brand}>VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text></Text>
          <Text style={styles.sub}>{user?.name} · <Text style={{ color: COLORS.primary }}>{roleTitle(agent?.io_role, user?.role) || roleLabel}</Text></Text>
        </View>
        <View style={styles.dayPill}>
          <Ionicons name="calendar-outline" size={12} color={COLORS.primary} />
          <Text style={styles.dayPillTxt}>{summary?.sales_day || '—'}</Text>
        </View>
      </View>

      {summary?.gate ? <GateBanner gate={summary.gate} /> : null}

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
      >
        {!summary ? (
          <ActivityIndicator color={COLORS.primary} style={{ marginTop: 40 }} />
        ) : (
          <>
            <Text style={styles.sectionTitle}>{summary.is_full_agency ? "TODAY'S GLOBAL PRODUCTION" : "TODAY'S TEAM PRODUCTION"}</Text>
            <View style={styles.cardsRow}>
              <StatCard
                label="Total Team ALP"
                value={fmtMoney(summary.total_alp)}
                deltaPct={summary.delta_pct_vs_yesterday}
                accent={COLORS.primary}
                testID="stat-total-alp"
              />
              <View style={{ width: 8 }} />
              <StatCard
                label="Agency Sits"
                value={summary.total_sits.toLocaleString()}
                accent={COLORS.secondary}
                testID="stat-total-sits"
              />
              <View style={{ width: 8 }} />
              <StatCard
                label="Total Sales"
                value={summary.total_sales.toLocaleString()}
                accent={COLORS.gold}
                testID="stat-total-sales"
              />
            </View>

            <PlatinumWall vets={vets} rookies={rookies} />

            <OfficeTabs offices={offices} />

            <View style={{ height: 40 }} />
          </>
        )}
      </ScrollView>

      <Ticker items={ticker} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 12 },
  brand: { color: '#fff', fontSize: 20, fontWeight: '900', letterSpacing: 1.5 },
  sub: { color: COLORS.textDim, fontSize: 11, marginTop: 2, letterSpacing: 0.5 },
  dayPill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4 },
  dayPillTxt: { color: COLORS.text, fontSize: 11, fontWeight: '700', fontVariant: ['tabular-nums' as any] },
  scroll: { paddingHorizontal: 16, paddingTop: 6, paddingBottom: 30 },
  sectionTitle: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginBottom: 10, marginTop: 6 },
  cardsRow: { flexDirection: 'row' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  notLinked: { color: '#fff', fontWeight: '800', fontSize: 16, marginTop: 12, textAlign: 'center' },
  notLinkedSub: { color: COLORS.textDim, marginTop: 6, textAlign: 'center' },
});
