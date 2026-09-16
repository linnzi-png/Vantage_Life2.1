// Team View — Level 2+
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, levelNum, roleTitle, isFinanceAdmin, Role } from '../../src/lib/auth';
import { AgentContactSheet, AgentContact, formatPhone } from '../../src/components/AgentContactSheet';
import { ChangeTierSheet } from '../../src/components/ChangeTierSheet';
import { QuickEntryForm, QuickEntryTarget } from '../../src/components/QuickEntryForm';
import { AddTeamMemberSheet } from '../../src/components/AddTeamMemberSheet';
import { MoveMemberSheet } from '../../src/components/MoveMemberSheet';
import { PeriodSelector, usePersistedPeriod } from '../../src/components/PeriodSelector';
import { SearchBar } from '../../src/components/SearchBar';
import { TourAnchor } from '../../src/components/TourAnchor';
import { LoadState } from '../../src/components/LoadState';
import { confirmAsync, notify } from '../../src/lib/dialog';

interface TeamRow {
  agent_id: string; name: string; office: string; role: Role; io_role: string;
  phone: string; email: string; is_rookie: boolean | null;
  upline_id?: string | null;
  archived: boolean; // removed from the team; production shown for history only
  gross_alp: number; net_alp: number; sits: number; sales: number; close_ratio: number; avg_deal: number; alerts: string[];
  // Server-computed: is this person in MY downline, as opposed to elsewhere in
  // my office? The office is visible to everyone in it, but every write path
  // (enter numbers, move, remove, tier) is downline-scoped server-side, so this
  // is what decides which rows may offer those actions at all.
  in_my_downline?: boolean;
  // Leaderboard (owner, 2026-09-16), all server-computed so the board reads
  // the same for everyone: rank runs on Gross ALP inside leaderboard_group,
  // and rank is null for anyone who produced nothing in the window. A leader's
  // row also carries their team's rollup alongside their own numbers.
  leaderboard_group?: 'leader' | 'rookie' | 'veteran' | 'unset';
  rank?: number | null;
  rank_of?: number | null;
  team_gross_alp?: number;
  team_sales?: number;
  team_size?: number;
}

const ALERT_LABELS: Record<string, { label: string; color: string }> = {
  low_close_ratio:   { label: 'Low Close',  color: COLORS.red },
  low_avg_deal:      { label: 'Low Avg',    color: COLORS.orange },
  no_pulse:          { label: 'No Pulse',   color: COLORS.yellow },
  // Push notifications never reached this device -- they can't get the 9 PM
  // reminders or upline confirmation pings. A signal for the manager to
  // follow up directly, not something the app enforces on its own.
  notifications_off: { label: '🔕 No Push', color: COLORS.secondary },
};

export default function TeamScreen() {
  const { user, agent, loading: authLoading } = useAuth();
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [moveTarget, setMoveTarget] = useState<TeamRow | null>(null);
  // A team IS an office (owner, 2026-09-16) — MJ's team, Rust's, Alwatan's,
  // Gojcaj's — and seeing the whole one is the point: it is a motivation and
  // healthy-competition tactic, not an oversight. So the board opens on the
  // team, and the narrower filter is "the people who report to me", which is
  // what an upline wants when entering numbers rather than when competing.
  const [scope, setScope] = useState<'team' | 'mine'>('team');
  const [tierTarget, setTierTarget] = useState<TeamRow | null>(null);
  const [upline, setUpline] = useState<AgentContact | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sortKey, setSortKey] = useState<keyof TeamRow>('gross_alp');
  const [selected, setSelected] = useState<TeamRow | null>(null);
  const [uplineOpen, setUplineOpen] = useState(false);
  const [readyNoms, setReadyNoms] = useState(0);
  const [period, changePeriod] = usePersistedPeriod('vl_team_period', 'weekly');
  const [quickEntryTarget, setQuickEntryTarget] = useState<QuickEntryTarget | null>(null);
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [missingQueue, setMissingQueue] = useState<TeamRow[]>([]); // remaining "no_pulse" agents queued for auto-advance
  // null = live rolling window (period). A week_start pins the view to that
  // past reporting week instead, so a manager can review it as it stood.
  const [weekStart, setWeekStart] = useState<string | null>(null);
  const [weekOptions, setWeekOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Which reporting window the rows currently on screen were fetched for.
  // Without it, switching Daily/Weekly/Monthly or pinning a past week kept
  // the previous window's rows on screen while the controls described the
  // new one — and if the new request failed, the masking below hid the
  // failure and those stale figures read as the selected window.
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const scopeKey = weekStart ? `week:${weekStart}` : `period:${period}`;
  const rowsMatchScope = loadedScope === scopeKey;

  const fetchAll = async () => {
    const scope = weekStart ? `week:${weekStart}` : `period:${period}`;
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
      setLoadedScope(scope);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Your team could not be loaded.');
    } finally {
      setLoading(false);
    }
  };
  // Re-fetch whenever the period changes; keep the 30s live refresh going.
  useEffect(() => {
    // Fetching + polling an external API, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
  // Only my own downline: this card opens proxy entry, which is downline-only.
  const missingTonight = rows.filter((r) => r.alerts?.includes('no_pulse') && r.in_my_downline !== false);

  // Owner's decision tree: remove or reassign anyone in your downline strictly
  // below your tier (level 2+). SA is not a special case (per owner,
  // 2026-09-15) — the tier decides, never the title. Backend re-checks all.
  const myLevel = levelNum(user?.role);
  const mine = (r: TeamRow) => r.in_my_downline !== false;
  const canRemoveRow = (r: TeamRow) =>
    myLevel >= 2 && mine(r) && !r.archived && r.agent_id !== user?.agent_id &&
    levelNum(r.role) < myLevel;
  const canMoveRow = canRemoveRow;
  // Proxy entry is downline-only server-side (can_enter_for), so an office
  // peer's card must not offer it.
  const canEnterForRow = (r: TeamRow) => canEnter && mine(r) && !r.archived;
  // Tier changes (owner, 2026-09-14): the same "in your downline, strictly
  // below you" rule as remove — canRemoveRow now carries the downline test, so
  // an office peer's card offers nothing an upline could not actually do.
  // is_admin and finance_admin act agency-wide at the same cap, which is why
  // they bypass it. Only ever a hint: /api/team/set-tier re-checks every part.
  const agencyWide = !!user?.is_admin || isFinanceAdmin(user?.role);
  const canChangeTierRow = (r: TeamRow) =>
    !r.archived && r.agent_id !== user?.agent_id && r.role !== 'level_4' &&
    (agencyWide || canRemoveRow(r));

  const removeMember = async (row: TeamRow) => {
    setSelected(null);
    try {
      const preview = await api<{ plan: { children_count: number; destination_upline: { name: string } | null } }>(
        '/api/team/remove-person',
        { method: 'POST', body: JSON.stringify({ agent_id: row.agent_id, dry_run: true }) });
      const n = preview.plan.children_count;
      const cascade = n > 0
        ? ` Their ${n} direct report${n === 1 ? '' : 's'} (and everyone under them) will move under ${preview.plan.destination_upline?.name || 'their former upline'}.`
        : '';
      const ok = await confirmAsync({
        title: 'Remove From Team',
        message: `Remove ${row.name} from your team? Their sales history stays in the records and an admin can restore them.${cascade}`,
        confirmText: 'Remove',
      });
      if (!ok) return;
      await api('/api/team/remove-person', {
        method: 'POST', body: JSON.stringify({ agent_id: row.agent_id }) });
      await fetchAll();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Remove failed');
    }
  };

  const moveCandidates = moveTarget
    ? rows.filter((c) =>
        !c.archived && c.agent_id !== moveTarget.agent_id &&
        levelNum(c.role) >= levelNum(moveTarget.role) && levelNum(c.role) <= myLevel)
    : [];

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
  const hasDownline = rows.some((r) => r.in_my_downline === true && r.agent_id !== user?.agent_id);
  const scoped = scope === 'mine' && hasDownline
    ? sorted.filter((r) => r.in_my_downline !== false || r.agent_id === user?.agent_id)
    : sorted;
  const visible = q
    ? scoped.filter((r) => `${r.name} ${r.office} ${roleTitle(r.io_role, r.role)}`.toLowerCase().includes(q))
    : scoped;

  // `user` is null while AuthProvider restores the session, and
  // levelNum(undefined) is 0 — so without this every GA and above was shown
  // the lock screen for a beat on every cold start. With the level_1 Team tab
  // it matters more, not less: that beat would now hit every tier.
  // One row, rendered under whichever board the server put this person on.
  const renderRow = (r: TeamRow) => (
          <TouchableOpacity
            key={r.agent_id}
            style={styles.row}
            testID={`team-row-${r.agent_id}`}
            onPress={() => setSelected(r)}
            activeOpacity={0.75}
          >
            <View style={styles.rankWrap}>
              <Text style={[styles.rankTxt, r.rank === 1 && styles.rankTxtTop]}>
                {r.rank ? `${r.rank}` : '—'}
              </Text>
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={styles.name} numberOfLines={1}>{r.name}</Text>
                {r.is_rookie ? <View style={styles.rookie}><Text style={styles.rookieTxt}>R</Text></View> : null}
                {r.archived ? <View style={styles.removed}><Text style={styles.removedTxt}>REMOVED</Text></View> : null}
                {r.in_my_downline === false && r.agent_id !== user?.agent_id ? (
                  <View style={styles.officeBadge}><Text style={styles.officeBadgeTxt}>OFFICE</Text></View>
                ) : null}
                <Ionicons name="chevron-forward" size={12} color={COLORS.textDim} style={{ marginLeft: 'auto' }} />
              </View>
              <Text style={styles.meta}>
                {r.office} · {roleTitle(r.io_role, r.role)}
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
              {/* A leader is ranked on what they sold themselves, which is
                  usually nothing — the rollup is what they are actually
                  accountable for, so both sit on the row. */}
              {r.leaderboard_group === 'leader' && r.team_size ? (
                <Text style={styles.teamRollup}>
                  TEAM ${Math.round(r.team_gross_alp || 0).toLocaleString()} · {r.team_sales || 0} sales · {r.team_size}
                </Text>
              ) : null}
            </View>
          </TouchableOpacity>
  );

  // The four boards, in the order they read best: the leaders first, then the
  // people they run. TENURE NOT SET only appears when someone is in it, which
  // is the nudge to go set it.
  const BOARDS: { key: NonNullable<TeamRow['leaderboard_group']>; label: string }[] = [
    { key: 'leader', label: 'LEADERS' },
    { key: 'rookie', label: 'ROOKIES' },
    { key: 'veteran', label: 'VETERANS' },
    { key: 'unset', label: 'TENURE NOT SET' },
  ];

  if (authLoading) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.empty}>
          <ActivityIndicator color={COLORS.primary} accessibilityLabel="Checking your access" />
        </View>
      </SafeAreaView>
    );
  }

  // < 1 rather than < 2: level_1 reads their own office here (office_agent_ids).
  // levelNum is 0 for finance_admin and pending, so both still get the lock.
  if (levelNum(user?.role) < 1) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.empty}>
          <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
          <Text style={styles.emptyTxt}>Team View is for Agent, GA, MGA, and RGA roles.</Text>
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
        {canEnter ? (
          <TouchableOpacity
            style={[styles.nomBtn, { marginRight: 8, borderColor: COLORS.primary, backgroundColor: 'rgba(49,152,66,0.10)' }]}
            onPress={() => setAddMemberOpen(true)}
            testID="open-add-member"
          >
            <Ionicons name="person-add" size={14} color={COLORS.primary} />
            <Text style={[styles.nomBtnTxt, { color: COLORS.primary }]}>ADD</Text>
          </TouchableOpacity>
        ) : null}
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
        {hasDownline ? (
          <View style={styles.scopeRow}>
            <TouchableOpacity
              onPress={() => setScope('team')}
              style={[styles.weekChip, scope === 'team' && styles.weekChipOn]}
              testID="team-scope-team"
            >
              <Text style={[styles.weekChipTxt, scope === 'team' && styles.weekChipTxtOn]}>MY TEAM</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setScope('mine')}
              style={[styles.weekChip, scope === 'mine' && styles.weekChipOn]}
              testID="team-scope-mine"
            >
              <Text style={[styles.weekChipTxt, scope === 'mine' && styles.weekChipTxtOn]}>REPORTS TO ME</Text>
            </TouchableOpacity>
          </View>
        ) : null}
        {weekOptions.length > 0 ? (
          <TourAnchor id="team-weeks">
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
          </TourAnchor>
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
        <LoadState
          // Rows from the previous window are not an answer for this one, so
          // a scope change shows the spinner rather than stale figures under
          // the new label.
          loading={loading || !rowsMatchScope}
          // Masked only for a failure that leaves correct rows on screen — a
          // flaky 30s poll must not replace a good roster with an error card.
          // A failed period or week change has no such rows, so it surfaces.
          error={rowsMatchScope && rows.length > 0 ? null : error}
          onRetry={fetchAll}
          isEmpty={visible.length === 0}
          emptyText={q ? 'No matches for your search.' : 'No team data yet.'}
          loadingText="Loading your team…"
          testID="team"
        >
          {BOARDS.map(({ key, label }) => {
            const group = visible.filter((r) => (r.leaderboard_group || 'unset') === key);
            if (group.length === 0) return null;
            const ranked = group.filter((r) => r.rank).length;
            return (
              <View key={key} style={styles.board}>
                <View style={styles.boardHead}>
                  <Text style={styles.boardLabel}>{label}</Text>
                  <Text style={styles.boardCount}>
                    {ranked > 0 ? `${ranked} RANKED · ` : ''}{group.length}
                  </Text>
                </View>
                {group.map(renderRow)}
              </View>
            );
          })}
        </LoadState>
      </ScrollView>

      <AgentContactSheet
        agent={selected}
        onClose={() => setSelected(null)}
        onEnterNumbers={selected && canEnterForRow(selected) ? () => openQuickEntry(selected) : undefined}
        onMove={selected && canMoveRow(selected) ? () => { const t = selected; setSelected(null); setMoveTarget(t); } : undefined}
        onRemove={selected && canRemoveRow(selected) ? () => removeMember(selected) : undefined}
        onChangeTier={selected && canChangeTierRow(selected)
          ? () => { const t = selected; setSelected(null); setTierTarget(t); }
          : undefined}
      />
      <ChangeTierSheet
        target={tierTarget}
        myRole={user?.role}
        agencyWide={agencyWide}
        onClose={() => setTierTarget(null)}
        onChanged={fetchAll}
      />
      <MoveMemberSheet
        target={moveTarget}
        candidates={moveCandidates}
        onClose={() => setMoveTarget(null)}
        onMoved={fetchAll}
      />
      <AgentContactSheet
        agent={uplineOpen ? upline : null}
        onClose={() => setUplineOpen(false)}
      />
      <AddTeamMemberSheet
        visible={addMemberOpen}
        onClose={() => setAddMemberOpen(false)}
        myRole={user?.role}
        onAdded={fetchAll}
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
  scopeRow: { flexDirection: 'row', gap: 6, marginTop: 8 },
  board: { marginBottom: 18 },
  boardHead: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 6, paddingHorizontal: 2,
  },
  boardLabel: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 1.6 },
  boardCount: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  rankWrap: { width: 26, alignItems: 'center', justifyContent: 'center' },
  rankTxt: { color: COLORS.textDim, fontSize: 13, fontWeight: '900' },
  rankTxtTop: { color: COLORS.gold, fontSize: 16 },
  teamRollup: { color: COLORS.textMuted, fontSize: 10, fontWeight: '800', marginTop: 2 },
  officeBadge: {
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4,
    borderWidth: 1, borderColor: COLORS.border,
  },
  officeBadgeTxt: { color: COLORS.textMuted, fontSize: 8, fontWeight: '900', letterSpacing: 0.8 },
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
  removed:       { borderWidth: 1, borderColor: COLORS.red, paddingHorizontal: 4, borderRadius: 2 },
  removedTxt:    { color: COLORS.red, fontWeight: '900', fontSize: 8, letterSpacing: 0.5 },
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
