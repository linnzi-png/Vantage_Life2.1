// Team View — Level 2+
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, levelNum, roleTitle } from '../../src/lib/auth';
import { AgentContactSheet, AgentContact, formatPhone } from '../../src/components/AgentContactSheet';
import { QuickEntryForm, QuickEntryTarget } from '../../src/components/QuickEntryForm';
import { PeriodSelector, usePersistedPeriod } from '../../src/components/PeriodSelector';
import { SearchBar } from '../../src/components/SearchBar';
import { TourAnchor } from '../../src/components/TourAnchor';

interface TeamRow {
  agent_id: string; name: string; office: string; role: string; io_role: string;
  phone: string; email: string; is_rookie: boolean;
  gross_alp: number; net_alp: number; sits: number; sales: number; close_ratio: number; avg_deal: number; alerts: string[];
}

const ALERT_LABELS: Record<string, { label: string; color: string }> = {
  low_close_ratio: { label: 'Low Close', color: COLORS.red },
  low_avg_deal:    { label: 'Low Avg',   color: COLORS.orange },
  no_pulse:        { label: 'No Pulse',  color: COLORS.yellow },
};

export default function TeamScreen() {
  const { user } = useAuth();
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [upline, setUpline] = useState<AgentContact | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sortKey, setSortKey] = useState<keyof TeamRow>('gross_alp');
  const [selected, setSelected] = useState<TeamRow | null>(null);
  const [uplineOpen, setUplineOpen] = useState(false);
  const [readyNoms, setReadyNoms] = useState(0);
  const [period, changePeriod] = usePersistedPeriod('vl_team_period', 'weekly');
  const [quickEntryTarget, setQuickEntryTarget] = useState<QuickEntryTarget | null>(null);
  const [missingQueue, setMissingQueue] = useState<TeamRow[]>([]); // remaining "no_pulse" agents queued for auto-advance
  // null = live rolling window (period). A week_start pins the view to that
  // past reporting week instead, so a manager can review it as it stood.
  const [weekStart, setWeekStart] = useState<string | null>(null);
  const [weekOptions, setWeekOptions] = useState<string[]>([]);

  const fetchAll = async () => {
    try {
      const [r, u, n] = await Promise.all([
        api<{ team: TeamRow[] }>(
          weekStart ? `/api/team?week_start=${weekStart}` : `/api/team?period=${period}`),
        api<{ upline: AgentContact | null }>('/api/my-upline').catch(() => ({ upline: null })),
        api<{ nominations: any[] }>('/api/nominations?status=threshold_met').catch(() => ({ nominations: [] })),
      ]);
      setRows(r.team);
      setUpline(u.upline);
      setReadyNoms(n.nominations.length);
    } catch {}
  };
  // Re-fetch whenever the period changes; keep the 30s live refresh going.
  useEffect(() => {
    fetchAll();
    // A pinned past week is static — no point polling it every 30s.
    if (weekStart) return;
    const i = setInterval(fetchAll, 30000);
    return () => clearInterval(i);
  }, [period, weekStart]);

  useEffect(() => {
    let cancelled = false;
    api<{ weeks: string[] }>('/api/team/weeks')
      .then((r) => { if (!cancelled) setWeekOptions(r.weeks); })
      .catch(() => { if (!cancelled) setWeekOptions([]); });
    return () => { cancelled = true; };
  }, []);

  const [query, setQuery] = useState('');
  const sorted = [...rows].sort((a, b) => (Number(b[sortKey]) || 0) - (Number(a[sortKey]) || 0));
  const q = query.trim().toLowerCase();
  // Any upline (SA/GA and above, level 2+) may enter Nightly Numbers on a
  // downline teammate's behalf, matching can_enter_for on the backend.
  const canEnter = levelNum(user?.role) >= 2;
  const missingTonight = rows.filter((r) => r.alerts?.includes('no_pulse'));

  const openQuickEntry = (row: TeamRow) => {
    setSelected(null);
    setQuickEntryTarget({ agent_id: row.agent_id, name: row.name });
  };

  const startMissingQueue = () => {
    if (missingTonight.length === 0) return;
    setMissingQueue(missingTonight.slice(1));
    setQuickEntryTarget({ agent_id: missingTonight[0].agent_id, name: missingTonight[0].name });
  };

  const advanceQueue = async () => {
    await fetchAll();
    setMissingQueue((q) => {
      if (q.length === 0) {
        setQuickEntryTarget(null);
        return q;
      }
      const [next, ...rest] = q;
      setQuickEntryTarget({ agent_id: next.agent_id, name: next.name });
      return rest;
    });
  };
  const visible = q
    ? sorted.filter((r) => `${r.name} ${r.office} ${roleTitle(r.io_role, r.role)}`.toLowerCase().includes(q))
    : sorted;

  if (levelNum(user?.role) < 2) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.empty}>
          <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
          <Text style={styles.emptyTxt}>Team View is for GA, MGA, and RGA roles.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const sortBtn = (key: keyof TeamRow, label: string) => (
    <TouchableOpacity
      onPress={() => setSortKey(key)}
      style={[styles.sortBtn, sortKey === key && styles.sortBtnActive]}
      testID={`team-sort-${key}`}
      hitSlop={{ top: 9, bottom: 9, left: 0, right: 0 }}
    >
      <Text
        style={[styles.sortTxt, sortKey === key && styles.sortTxtActive]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.7}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={[styles.head, { flexDirection: 'row', alignItems: 'center' }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>HIERARCHY VIEW · LIVE</Text>
          <Text style={styles.title}>TEAM PRODUCTION</Text>
        </View>
        <TourAnchor id="team-nominations">
          <TouchableOpacity style={styles.nomBtn} onPress={() => router.push('/nominations')} testID="open-nominations">
            <Ionicons name="medal" size={14} color="#E5E4E2" />
            <Text style={styles.nomBtnTxt}>NOMINATIONS</Text>
            {readyNoms > 0 ? (
              <View style={styles.badge} testID="nominations-badge">
                <Text style={styles.badgeTxt}>{readyNoms}</Text>
              </View>
            ) : null}
          </TouchableOpacity>
        </TourAnchor>
      </View>

      {upline && levelNum(user?.role) < 4 ? (
        <TouchableOpacity
          style={styles.uplineCard}
          onPress={() => setUplineOpen(true)}
          activeOpacity={0.75}
          testID="team-upline-card"
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.uplineKicker}>YOUR {roleTitle(upline.io_role, upline.role).toUpperCase()}</Text>
            <Text style={styles.uplineName}>{upline.name}</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            {upline.phone ? <Ionicons name="call" size={15} color={COLORS.primary} /> : null}
            {upline.phone ? <Ionicons name="chatbubble" size={15} color={COLORS.secondary} /> : null}
            <Ionicons name="chevron-forward" size={14} color={COLORS.textDim} />
          </View>
        </TouchableOpacity>
      ) : null}

      <View style={styles.periodBar}>
        <PeriodSelector value={period} onChange={changePeriod} testID="team-period" />
        {weekOptions.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.weekPicker}
          >
            <TouchableOpacity
              onPress={() => setWeekStart(null)}
              style={[styles.weekChip, !weekStart && styles.weekChipOn]}
              testID="team-week-live"
            >
              <Text style={[styles.weekChipTxt, !weekStart && styles.weekChipTxtOn]}>LIVE</Text>
            </TouchableOpacity>
            {weekOptions.map((w) => (
              <TouchableOpacity
                key={w}
                onPress={() => setWeekStart(w === weekStart ? null : w)}
                style={[styles.weekChip, w === weekStart && styles.weekChipOn]}
                testID={`team-week-${w}`}
              >
                <Text style={[styles.weekChipTxt, w === weekStart && styles.weekChipTxtOn]}>
                  {(() => { const [, m, d] = w.split('-'); return `${Number(m)}/${Number(d)}`; })()}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        ) : null}
      </View>

      {canEnter && missingTonight.length > 0 ? (
        <TourAnchor id="team-missing">
        <TouchableOpacity
          style={styles.missingCard}
          onPress={startMissingQueue}
          activeOpacity={0.75}
          testID="missing-tonight-card"
        >
          <View style={styles.iconWrapMissing}>
            <Ionicons name="alert" size={16} color={COLORS.yellow} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.missingKicker}>MISSING TONIGHT · {missingTonight.length}</Text>
            <Text style={styles.missingNames} numberOfLines={1}>
              {missingTonight.slice(0, 3).map((r) => r.name).join(', ')}{missingTonight.length > 3 ? `, +${missingTonight.length - 3} more` : ''}
            </Text>
          </View>
          <Text style={styles.missingAction}>ENTER ALL</Text>
          <Ionicons name="chevron-forward" size={14} color={COLORS.textDim} />
        </TouchableOpacity>
        </TourAnchor>
      ) : null}

      <View style={styles.sortBar}>
        {sortBtn('gross_alp', 'Gross ALP')}
        {sortBtn('net_alp', 'Net ALP')}
        {sortBtn('sales', 'Sales')}
        {sortBtn('close_ratio', 'Close %')}
        {sortBtn('avg_deal', 'Avg Deal')}
      </View>
      <TourAnchor id="team-roster">
        <SearchBar value={query} onChange={setQuery} placeholder="Search name, office, title" testID="team-search" />
      </TourAnchor>
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingTop: 4, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); }} tintColor={COLORS.primary} />}
      >
        {visible.length === 0 ? (
          <Text style={styles.emptyTxt}>{q ? 'No matches for your search.' : 'No team data yet.'}</Text>
        ) : visible.map((r) => (
          <TouchableOpacity
            key={r.agent_id}
            style={styles.row}
            testID={`team-row-${r.agent_id}`}
            onPress={() => setSelected(r)}
            activeOpacity={0.75}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={styles.name} numberOfLines={1}>{r.name}</Text>
                {r.is_rookie ? <View style={styles.rookie}><Text style={styles.rookieTxt}>R</Text></View> : null}
                <Ionicons name="chevron-forward" size={12} color={COLORS.textDim} style={{ marginLeft: 'auto' }} />
              </View>
              <Text style={styles.meta}>
                {r.office} · {roleTitle(r.io_role, r.role) || r.role.replace('level_', 'L')}
                {r.phone ? ` · ${formatPhone(r.phone)}` : ''}
              </Text>
              {r.alerts?.length ? (
                <View style={{ flexDirection: 'row', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                  {r.alerts.map((a) => (
                    <View key={a} style={[styles.alert, { borderColor: ALERT_LABELS[a]?.color || COLORS.textDim }]}>
                      <Text style={[styles.alertTxt, { color: ALERT_LABELS[a]?.color || COLORS.textDim }]}>{ALERT_LABELS[a]?.label || a}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.alp}>${Math.round(r.gross_alp).toLocaleString()}</Text>
              <Text style={styles.metric}>{r.sales} sales · {r.close_ratio}%</Text>
              {Math.abs(r.gross_alp - r.net_alp) > 0.01 ? (
                <Text style={styles.netAlp}>NET ${Math.round(r.net_alp).toLocaleString()}</Text>
              ) : null}
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <AgentContactSheet
        agent={selected}
        onClose={() => setSelected(null)}
        onEnterNumbers={canEnter && selected ? () => openQuickEntry(selected) : undefined}
      />
      <AgentContactSheet
        agent={uplineOpen ? upline : null}
        onClose={() => setUplineOpen(false)}
      />
      <QuickEntryForm
        target={quickEntryTarget}
        onClose={() => { setQuickEntryTarget(null); setMissingQueue([]); }}
        onSubmitted={advanceQueue}
        hasNext={missingQueue.length > 0}
        onNext={advanceQueue}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  weekPicker: { gap: 6, paddingVertical: 8 },
  weekChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  weekChipOn: { backgroundColor: COLORS.gold, borderColor: COLORS.gold },
  weekChipTxt: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },
  weekChipTxtOn: { color: '#000' },
  safe:          { flex: 1, backgroundColor: COLORS.bg },
  head:          { paddingHorizontal: 16, paddingVertical: 12 },
  kicker:        { color: COLORS.primary, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  title:         { color: '#fff', fontSize: 22, fontWeight: '900' },
  periodBar:     { paddingHorizontal: 12, paddingTop: 8 },
  sortBar:       { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, minHeight: 44 },
  sortBtn:       { flex: 1, alignItems: 'center', paddingHorizontal: 4, paddingVertical: 6, borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, backgroundColor: COLORS.surface },
  sortBtnActive: { borderColor: COLORS.primary, backgroundColor: 'rgba(49,152,66,0.12)' },
  sortTxt:       { color: COLORS.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  sortTxtActive: { color: COLORS.primary },
  empty:         { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  emptyTxt:      { color: COLORS.textDim, marginTop: 12, textAlign: 'center' },
  row:           { flexDirection: 'row', alignItems: 'flex-start', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 12, borderRadius: 6, marginBottom: 6 },
  name:          { color: '#fff', fontWeight: '800', fontSize: 14, flexShrink: 1 },
  meta:          { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  alp:           { color: COLORS.primary, fontWeight: '900', fontSize: 16, fontVariant: ['tabular-nums' as any] },
  metric:        { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  netAlp:        { color: COLORS.orange, fontSize: 10, fontWeight: '800', marginTop: 2, letterSpacing: 0.5 },
  alert:         { borderWidth: 1, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  alertTxt:      { fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  rookie:        { backgroundColor: COLORS.orange, paddingHorizontal: 4, borderRadius: 2 },
  rookieTxt:     { color: '#000', fontWeight: '900', fontSize: 9 },
  uplineCard:    {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginHorizontal: 16, marginBottom: 8,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.primary,
    padding: 12, borderRadius: 6,
  },
  uplineKicker:  { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1.8, marginBottom: 2 },
  uplineName:    { color: '#fff', fontWeight: '800', fontSize: 14 },
  missingCard:   {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    marginHorizontal: 16, marginBottom: 8,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.yellow,
    padding: 12, borderRadius: 6,
  },
  iconWrapMissing: { width: 28, height: 28, borderRadius: 14, backgroundColor: COLORS.surface2, alignItems: 'center', justifyContent: 'center' },
  missingKicker: { color: COLORS.yellow, fontSize: 10, fontWeight: '900', letterSpacing: 1.2 },
  missingNames:  { color: COLORS.textDim, fontSize: 12, marginTop: 2 },
  missingAction: { color: COLORS.yellow, fontSize: 10, fontWeight: '900', letterSpacing: 0.8 },
  nomBtn:        {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    borderWidth: 1, borderColor: '#E5E4E2', borderRadius: 5,
    paddingHorizontal: 10, paddingVertical: 7, backgroundColor: 'rgba(229,228,226,0.08)',
  },
  nomBtnTxt:     { color: '#E5E4E2', fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  badge:         { backgroundColor: COLORS.red, borderRadius: 8, minWidth: 16, height: 16, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  badgeTxt:      { color: '#fff', fontSize: 9, fontWeight: '900' },
});
