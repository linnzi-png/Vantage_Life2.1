// Executive Dashboard — default screen
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, Modal } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth } from '../../src/lib/auth';
import StatCard from '../../src/components/StatCard';
import PlatinumWall, { WallItem, PlatinumRulePost } from '../../src/components/PlatinumWall';
import { AgentContactSheet, AgentContact } from '../../src/components/AgentContactSheet';
import OfficeTabs, { OfficeRow } from '../../src/components/OfficeTabs';
import GateBanner from '../../src/components/GateBanner';
import Ticker, { TickerItem } from '../../src/components/Ticker';
import { PeriodSelector, usePersistedPeriod, Period } from '../../src/components/PeriodSelector';
import { TourAnchor } from '../../src/components/TourAnchor';
import { LoadState } from '../../src/components/LoadState';
import PushGoal, { PushGoalData } from '../../src/components/PushGoal';
import { PushGoalDetail } from '../../src/components/PushGoalDetail';

// What the summary covers, from the server (owner, 2026-09-19): the header
// mixed "global", "team" and "agency" for one scope, so now one word runs
// through the section title and all three stat labels.
type Scope = 'agency' | 'office' | 'team' | 'you';

interface Summary {
  total_alp: number; total_net_alp: number; total_sits: number; total_sales: number;
  delta_pct_vs_yesterday: number; sales_day: string; gate: any; is_full_agency: boolean;
  is_history?: boolean; period?: Period; scope?: Scope;
}

const SCOPE_WORD: Record<Scope, string> = { agency: 'Agency', office: 'Office', team: 'Team', you: 'Your' };

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
  const [wallScopeLabel, setWallScopeLabel] = useState<'agency' | 'office' | 'team' | null>(null);
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  // Push Month (owner, 2026-09-19). Company-wide and unscoped by design, so
  // it ignores the period and day controls below it: whatever window the
  // rest of the dashboard is on, the goal is always "since 9/18, to date".
  // Kept on failure — the last good total is still true, and a campaign
  // centerpiece flickering out on a flaky poll would be worse than staleness.
  const [pushGoal, setPushGoal] = useState<PushGoalData | null>(null);
  const [pushGoalOpen, setPushGoalOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [contactAgent, setContactAgent] = useState<AgentContact | null>(null);
  // Read-only history: null = live today; a YYYY-MM-DD string = that past sales day.
  const [viewDay, setViewDay] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [todayDay, setTodayDay] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Which window the summary on screen was fetched for. Switching
  // Daily/Weekly/Monthly or picking a past day keeps the previous summary
  // while the new request is in flight; without this, a failed scope change
  // would be masked and last week's figures would sit under the new label.
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  // The wall and the office tiles are scoped too, so they need their own
  // scope and error: leaving their arrays untouched when their request fails
  // made an outage render as the wall's "No production in this period", and
  // across a scope change it relabelled one window's producers as another's.
  const [wallScope, setWallScope] = useState<string | null>(null);
  const [wallError, setWallError] = useState<string | null>(null);
  const [officesScope, setOfficesScope] = useState<string | null>(null);
  const [officesError, setOfficesError] = useState<string | null>(null);
  // Dashboard defaults to Daily (the specific-day picker only applies here);
  // Weekly/Monthly show a rolling window and hide the day picker.
  const [period, changePeriod] = usePersistedPeriod('vl_dashboard_period', 'daily');
  // Guards against out-of-order responses: switching tabs quickly (daily ->
  // weekly -> monthly) fires overlapping fetchAll() calls, and a slower
  // earlier request can resolve after a faster later one and clobber the
  // screen with stale data for whatever tab is no longer selected. Bumped at
  // the start of every fetchAll(); a response is applied only if it's still
  // the most recently issued one by the time it resolves.
  const fetchIdRef = React.useRef(0);

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

  const scopeKey = period !== 'daily' ? `period:${period}` : `day:${viewDay ?? 'today'}`;
  const summaryMatchesScope = loadedScope === scopeKey;
  const wallMatchesScope = wallScope === scopeKey;
  const officesMatchScope = officesScope === scopeKey;

  const fetchAll = useCallback(async () => {
    const requestId = ++fetchIdRef.current;
    const scope = period !== 'daily' ? `period:${period}` : `day:${viewDay ?? 'today'}`;
    try {
      // Daily uses the (optionally historical) day; weekly/monthly use a rolling
      // window. Every section takes the same window so nothing on screen can
      // disagree with anything else — the wall used to ignore it entirely and
      // was therefore always empty for a historical day. Ticker stays live.
      const q = period !== 'daily' ? `?period=${period}` : (viewDay ? `?sales_day=${viewDay}` : '');
      // allSettled, not all: with Promise.all a single failing section —
      // the ticker, say — rejected the whole batch, so none of the four
      // setState calls ran, `summary` stayed null, and the screen showed a
      // bare spinner forever. Each section now lands or fails on its own.
      const [s, t, p, o, g] = await Promise.allSettled([
        api<Summary>(`/api/dashboard/summary${q}`),
        api<{ items: TickerItem[] }>('/api/dashboard/ticker'),
        api<{ vets: WallItem[]; rookies: WallItem[]; unranked?: WallItem[]; platinum_rule?: PlatinumRulePost[]; scope?: 'agency' | 'office' | 'team' }>(
          `/api/dashboard/platinum-wall${q}`),
        api<{ offices: OfficeRow[] }>(`/api/dashboard/offices${q}`),
        api<PushGoalData>('/api/dashboard/push-goal'),
      ]);
      // A newer fetchAll() started while this one was in flight — its
      // response (for whatever tab is now selected) already landed or will
      // land instead. Applying this older response now would overwrite
      // correct data with stale data for a tab that's no longer active.
      if (fetchIdRef.current !== requestId) return;

      // The summary is the screen: without it there are no cards and no
      // header, so its failure is the one the user has to be told about.
      if (s.status === 'fulfilled') {
        setSummary(s.value);
        setLoadedScope(scope);
        setError(null);
        if (!viewDay && period === 'daily') setTodayDay(s.value.sales_day);
      } else {
        const e = s.reason;
        setError(e instanceof Error ? e.message : 'The dashboard could not be loaded.');
      }

      // The ticker is unscoped and live, so stale items are still true — a
      // failed tick just leaves the last ones running.
      if (t.status === 'fulfilled') setTicker(t.value.items);

      // Same reasoning as the ticker: the goal is unscoped, so the previous
      // figure is still true when a refresh fails.
      if (g.status === 'fulfilled') setPushGoal(g.value);

      // The wall and the office tiles ARE scoped, so a failure cannot leave
      // their previous contents standing: they would be presented under the
      // new windowLabel as if they belonged to it. Each records the scope its
      // data answers, and the render below refuses to show a mismatch.
      if (p.status === 'fulfilled') {
        setVets(p.value.vets);
        setRookies(p.value.rookies);
        setUnranked(p.value.unranked || []);
        setPlatinum(p.value.platinum_rule || []);
        setWallScopeLabel(p.value.scope ?? null);
        setWallScope(scope);
        setWallError(null);
      } else {
        const e = p.reason;
        setWallError(e instanceof Error ? e.message : 'The Platinum Wall could not be loaded.');
      }

      if (o.status === 'fulfilled') {
        setOffices(o.value.offices);
        setOfficesScope(scope);
        setOfficesError(null);
      } else {
        const e = o.reason;
        setOfficesError(e instanceof Error ? e.message : 'Office production could not be loaded.');
      }
    } catch (e) {
      if (fetchIdRef.current === requestId) console.warn('Dashboard fetch error:', e);
    } finally {
      if (fetchIdRef.current === requestId) setLoading(false);
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
    // Fetching + polling an external API on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchAll();
    const interval = setInterval(fetchAll, 30000); // 30s polling for live ticker
    return () => clearInterval(interval);
  }, [fetchAll]);

  const onRefresh = async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); };

  const fmtMoney = (n: number) => `$${Math.round(n).toLocaleString()}`;

  // Section copy. The window word and the scope word are decided once here so
  // the header, the three cards, the wall and the office tabs all agree.
  const scope: Scope = summary?.scope ?? (summary?.is_full_agency ? 'agency' : 'team');
  const scopeWord = SCOPE_WORD[scope];
  const windowWord = period === 'weekly' ? 'This week' : period === 'monthly' ? 'This month'
    : viewDay ? viewDay : 'Today';
  const coverage: Record<Scope, string> = {
    agency: 'every office combined',
    office: agent?.office ? `${agent.office} only` : 'your office only',
    team: 'everyone who reports to you',
    you: 'your own numbers',
  };
  const wallCoverage = wallScopeLabel === 'agency' ? 'every office' : wallScopeLabel === 'team' ? 'your downline' : 'your office';

  if (!user?.agent_id) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={36} color={COLORS.orange} />
          <Text style={styles.notLinked}>This account isn&apos;t linked to an agent profile yet.</Text>
          <Text style={styles.notLinkedSub}>Try the Demo Login screen and pick &quot;AGENT&quot; to test the Pulse flow.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <TourAnchor id="dash-header" style={styles.header} testID="dashboard-header">
        <View>
          <Text style={styles.brand}>VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text></Text>
          <Text style={styles.sub}>{user?.name} · <Text style={{ color: COLORS.primary }}>{roleLabel}</Text></Text>
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
        {/* The campaign centerpiece sits above everything, outside the
            summary's LoadState: it has its own request, and the goal should
            be on screen even while a period change is re-fetching the rest. */}
        {pushGoal ? <PushGoal data={pushGoal} onPress={() => setPushGoalOpen(true)} /> : null}
        <LoadState
          // A summary fetched for another window is not an answer for this
          // one, so a period or day change shows the spinner rather than the
          // previous window's figures under the new label.
          loading={loading || !summaryMatchesScope}
          // Masked only for a failure that leaves a correct summary on
          // screen: those numbers are still the last good ones for this
          // window. A failed scope change has no such summary, so it
          // surfaces with RETRY.
          error={summary && summaryMatchesScope ? null : error}
          onRetry={fetchAll}
          loadingText="Loading production…"
          testID="dashboard"
        >
          {!summary || !summaryMatchesScope ? null : (
          <>
            <Text style={styles.sectionTitle} testID="dashboard-section-title">
              {`${scopeWord.toUpperCase()} PRODUCTION`}
            </Text>
            <Text style={styles.sectionSub} testID="dashboard-section-sub">
              {`${windowWord} · ${coverage[scope]}`}
            </Text>
            <TourAnchor id="dash-stats" style={styles.cardsRow}>
              <StatCard
                label={`${scopeWord} ALP`}
                value={fmtMoney(summary.total_alp)}
                deltaPct={summary.delta_pct_vs_yesterday}
                accent={COLORS.primary}
                testID="stat-total-alp"
              />
              <View style={{ width: 8 }} />
              <StatCard
                label={`${scopeWord} Sits`}
                value={summary.total_sits.toLocaleString()}
                accent={COLORS.secondary}
                testID="stat-total-sits"
              />
              <View style={{ width: 8 }} />
              <StatCard
                label={`${scopeWord} Sales`}
                value={summary.total_sales.toLocaleString()}
                accent={COLORS.gold}
                testID="stat-total-sales"
              />
            </TourAnchor>

            <TourAnchor id="dash-wall">
              <LoadState
                loading={!wallMatchesScope && !wallError}
                error={wallMatchesScope ? null : wallError}
                onRetry={fetchAll}
                loadingText="Loading the wall…"
                testID="dashboard-wall"
              >
              <PlatinumWall
                vets={vets}
                rookies={rookies}
                unranked={unranked}
                platinum={platinum}
                windowLabel={windowLabel}
                subtitle={`Top 3 producers · ${wallCoverage}`}
                onPress={(it: WallItem) => setContactAgent({
                  name: it.name, role: it.role || 'level_1', io_role: it.io_role,
                  phone: it.phone, email: it.email, office: it.office,
                })}
              />
              </LoadState>
            </TourAnchor>

            <LoadState
              loading={!officesMatchScope && !officesError}
              error={officesMatchScope ? null : officesError}
              onRetry={fetchAll}
              loadingText="Loading offices…"
              testID="dashboard-offices"
            >
              <OfficeTabs
                offices={offices}
                windowLabel={windowLabel}
                subtitle={scope === 'agency' ? 'Every office side by side' : 'Only what you can see, filed by office'}
              />
            </LoadState>

            <View style={{ height: 40 }} />
          </>
          )}
        </LoadState>
      </ScrollView>

      <TourAnchor id="dash-ticker">
        <Ticker items={ticker} />
      </TourAnchor>
      <AgentContactSheet agent={contactAgent} onClose={() => setContactAgent(null)} />
      {pushGoalOpen ? <PushGoalDetail data={pushGoal} onClose={() => setPushGoalOpen(false)} /> : null}

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
  sectionTitle: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginTop: 6 },
  sectionSub: { color: COLORS.textMuted, fontSize: 11, marginTop: 2, marginBottom: 10 },
  cardsRow: { flexDirection: 'row' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  notLinked: { color: '#fff', fontWeight: '800', fontSize: 16, marginTop: 12, textAlign: 'center' },
  notLinkedSub: { color: COLORS.textDim, marginTop: 6, textAlign: 'center' },
});
