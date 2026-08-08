// Executive Dashboard — default screen
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator, TouchableOpacity, Modal } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, roleTitle } from '../../src/lib/auth';
import StatCard from '../../src/components/StatCard';
import PlatinumWall, { WallItem, PlatinumRulePost } from '../../src/components/PlatinumWall';
import { AgentContactSheet, AgentContact } from '../../src/components/AgentContactSheet';
import OfficeTabs, { OfficeRow } from '../../src/components/OfficeTabs';
import GateBanner from '../../src/components/GateBanner';
import Ticker, { TickerItem } from '../../src/components/Ticker';
import { AgentHistory } from '../../src/components/AgentHistory';
import { PeriodSelector, usePersistedPeriod, Period } from '../../src/components/PeriodSelector';
import { TourAnchor } from '../../src/components/TourAnchor';

interface Summary {
  total_alp: number; total_net_alp: number; total_sits: number; total_sales: number;
  delta_pct_vs_yesterday: number; sales_day: string; gate: any; is_full_agency: boolean;
  is_history?: boolean; period?: Period;
}

const HISTORY_DAYS = 30;

export default function DashboardScreen() {
  const { user, agent, roleLabel } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [ticker, setTicker] = useState<TickerItem[]>([]);
  const [vets, setVets] = useState<WallItem[]>([]);
  const [rookies, setRookies] = useState<WallItem[]>([]);
  // Top producers whose tenure was never recorded — shown in their own panel
  // rather than dropped, which is what made the wall look empty.
  const [unranked, setUnranked] = useState<WallItem[]>([]);
  const [platinum, setPlatinum] = useState<PlatinumRulePost[]>([]);
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [contactAgent, setContactAgent] = useState<AgentContact | null>(null);
  // Read-only history: null = live today; a YYYY-MM-DD string = that past sales day.
  const [viewDay, setViewDay] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [todayDay, setTodayDay] = useState<string | null>(null);
  // Dashboard defaults to Daily (the specific-day picker only applies here);
  // Weekly/Monthly show a rolling window and hide the day picker.
  const [period, changePeriod] = usePersistedPeriod('vl_dashboard_period', 'daily');

  const onChangePeriod = (p: Period) => {
    changePeriod(p);
    if (p !== 'daily') setViewDay(null); // a rolling window has no single "day"
  };

  // One label for every section, so the wall and the office tiles state the
  // same window the summary header does. Without it those sections silently
  // re-scoped from a day to a week to a month and read as stale.
  const windowLabel = period !== 'daily'
    ? period.toUpperCase()
    : viewDay ?? 'TODAY';

  const fetchAll = useCallback(async () => {
    try {
      // Daily uses the (optionally historical) day; weekly/monthly use a rolling
      // window. Every section takes the same window so nothing on screen can
      // disagree with anything else — the wall used to ignore it entirely and
      // was therefore always empty for a historical day. Ticker stays live.
      const q = period !== 'daily' ? `?period=${period}` : (viewDay ? `?sales_day=${viewDay}` : '');
      const [s, t, p, o] = await Promise.all([
        api<Summary>(`/api/dashboard/summary${q}`),
        api<{ items: TickerItem[] }>('/api/dashboard/ticker'),
        api<{ vets: WallItem[]; rookies: WallItem[]; unranked?: WallItem[]; platinum_rule?: PlatinumRulePost[] }>(
          `/api/dashboard/platinum-wall${q}`),
        api<{ offices: OfficeRow[] }>(`/api/dashboard/offices${q}`),
      ]);
      setSummary(s); setTicker(t.items); setVets(p.vets); setRookies(p.rookies);
      setUnranked(p.unranked || []); setPlatinum(p.platinum_rule || []); setOffices(o.offices);
      if (!viewDay && period === 'daily') setTodayDay(s.sales_day);
    } catch (e) {
      console.warn('Dashboard fetch error:', e);
    }
  }, [viewDay, period]);

  const dayOptions = React.useMemo(() => {
    const anchor = todayDay || summary?.sales_day;
    if (!anchor) return [];
    const base = new Date(`${anchor}T12:00:00`);
    return Array.from({ length: HISTORY_DAYS }, (_, i) =>
      new Date(base.getTime() - i * 86400000).toISOString().slice(0, 10));
  }, [todayDay, summary?.sales_day]);

  const fmtDay = (d: string) =>
    `${d} · ${new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()}`;

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
      <TourAnchor id="dash-header" style={styles.header} testID="dashboard-header">
        <View>
          <Text style={styles.brand}>VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text></Text>
          <Text style={styles.sub}>{user?.name} · <Text style={{ color: COLORS.primary }}>{roleTitle(agent?.io_role, user?.role) || roleLabel}</Text></Text>
        </View>
        {period === 'daily' ? (
          <TouchableOpacity
            style={[styles.dayPill, viewDay ? styles.dayPillHistory : null]}
            onPress={() => setPickerOpen(true)}
            testID="day-picker-open"
          >
            <Ionicons name="calendar-outline" size={12} color={viewDay ? COLORS.gold : COLORS.primary} />
            <Text style={styles.dayPillTxt}>{viewDay ?? (summary?.sales_day || '—')}</Text>
            <Ionicons name="chevron-down" size={10} color={COLORS.textDim} />
          </TouchableOpacity>
        ) : null}
      </TourAnchor>

      <TourAnchor id="dash-period" style={styles.periodBar}>
        <PeriodSelector value={period} onChange={onChangePeriod} testID="dashboard-period" />
      </TourAnchor>

      {viewDay ? (
        <TouchableOpacity style={styles.historyBar} onPress={() => setViewDay(null)} testID="history-return">
          <Ionicons name="time-outline" size={13} color={COLORS.gold} />
          <Text style={styles.historyBarTxt}>VIEWING {viewDay} · READ-ONLY</Text>
          <Text style={styles.historyBarBack}>BACK TO TODAY</Text>
        </TouchableOpacity>
      ) : null}

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
            <Text style={styles.sectionTitle}>
              {period !== 'daily'
                ? `${period.toUpperCase()} ${summary.is_full_agency ? 'GLOBAL' : 'TEAM'} PRODUCTION`
                : summary.is_history
                ? `PRODUCTION · ${summary.sales_day}`
                : summary.is_full_agency ? "TODAY'S GLOBAL PRODUCTION" : "TODAY'S TEAM PRODUCTION"}
            </Text>
            <TourAnchor id="dash-stats" style={styles.cardsRow}>
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
            </TourAnchor>

            <TourAnchor id="dash-wall">
              <PlatinumWall
                vets={vets}
                rookies={rookies}
                unranked={unranked}
                platinum={platinum}
                windowLabel={windowLabel}
                onPress={(it: WallItem) => setContactAgent({
                  name: it.name, role: it.role || 'level_1', io_role: it.io_role,
                  phone: it.phone, email: it.email, office: it.office,
                })}
              />
            </TourAnchor>

            <OfficeTabs offices={offices} windowLabel={windowLabel} />

            {user?.agent_id ? <AgentHistory agentId={user.agent_id} /> : null}

            <View style={{ height: 40 }} />
          </>
        )}
      </ScrollView>

      <TourAnchor id="dash-ticker">
        <Ticker items={ticker} />
      </TourAnchor>
      <AgentContactSheet agent={contactAgent} onClose={() => setContactAgent(null)} />

      <Modal visible={pickerOpen} transparent animationType="fade" onRequestClose={() => setPickerOpen(false)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setPickerOpen(false)}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>VIEW A SALES DAY</Text>
            <ScrollView style={{ maxHeight: 420 }}>
              <TouchableOpacity
                style={styles.dayRow}
                onPress={() => { setViewDay(null); setPickerOpen(false); }}
                testID="day-option-today"
              >
                <Text style={[styles.dayRowTxt, { color: COLORS.primary, fontWeight: '900' }]}>TODAY · LIVE</Text>
                {!viewDay ? <Ionicons name="checkmark" size={14} color={COLORS.primary} /> : null}
              </TouchableOpacity>
              {dayOptions.slice(1).map((d) => (
                <TouchableOpacity
                  key={d}
                  style={styles.dayRow}
                  onPress={() => { setViewDay(d); setPickerOpen(false); }}
                  testID={`day-option-${d}`}
                >
                  <Text style={styles.dayRowTxt}>{fmtDay(d)}</Text>
                  {viewDay === d ? <Ionicons name="checkmark" size={14} color={COLORS.gold} /> : null}
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 12 },
  brand: { color: '#fff', fontSize: 20, fontWeight: '900', letterSpacing: 1.5 },
  sub: { color: COLORS.textDim, fontSize: 11, marginTop: 2, letterSpacing: 0.5 },
  periodBar: { paddingHorizontal: 16, paddingBottom: 8 },
  dayPill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4 },
  dayPillHistory: { borderColor: COLORS.gold },
  dayPillTxt: { color: COLORS.text, fontSize: 11, fontWeight: '700', fontVariant: ['tabular-nums' as any] },
  historyBar: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    marginHorizontal: 16, marginBottom: 6, paddingHorizontal: 12, paddingVertical: 8,
    borderWidth: 1, borderColor: COLORS.gold, borderRadius: 4, backgroundColor: 'rgba(255,215,0,0.07)',
  },
  historyBarTxt: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 1, flex: 1 },
  historyBarBack: { color: '#fff', fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', padding: 24 },
  modalCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 8, padding: 16 },
  modalTitle: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginBottom: 10 },
  dayRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 11, borderTopWidth: 1, borderTopColor: COLORS.border,
  },
  dayRowTxt: { color: '#fff', fontSize: 13, fontWeight: '600', fontVariant: ['tabular-nums' as any] },
  scroll: { paddingHorizontal: 16, paddingTop: 6, paddingBottom: 30 },
  sectionTitle: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginBottom: 10, marginTop: 6 },
  cardsRow: { flexDirection: 'row' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  notLinked: { color: '#fff', fontWeight: '800', fontSize: 16, marginTop: 12, textAlign: 'center' },
  notLinkedSub: { color: COLORS.textDim, marginTop: 6, textAlign: 'center' },
});
