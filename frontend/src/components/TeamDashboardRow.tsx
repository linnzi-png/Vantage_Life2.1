// The Team tab's dashboard row (owner: MJ 2026-09-25; Linnzi 2026-09-26 and
// 2026-09-29). Sits above the list: the viewer's own scope by SA team, on
// Daily / Weekly / Monthly, each person's licensed states, and a state chip
// that narrows it to people licensed in that exact code. The server decides
// what the viewer may see (team_scope_agent_ids); this only draws it.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { formatLicensedStates } from '../lib/licensedStates';
import {
  DashboardResponse, DashTeam, dashboardPath, noOneLicensedText,
} from '../lib/teamDashboard';
import { formatMoney } from '../lib/teamViews';
import { LoadState } from './LoadState';
import PeriodSegmented from './PeriodSegmented';
import { Period } from './PeriodSelector';

export function TeamDashboardRow({ refreshKey = 0 }: { refreshKey?: number }) {
  const [period, setPeriod] = useState<Period>('monthly');
  const [state, setState] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const path = dashboardPath(state);
  const latest = useRef(path);
  latest.current = path;

  const load = useCallback(async () => {
    const asked = path;
    try {
      const r = await api<DashboardResponse>(asked);
      // An answer for a state the viewer has already left must not replace
      // the one on screen.
      if (latest.current !== asked) return;
      setData(r);
      setLoadedFor(asked);
      setError(null);
    } catch (e: unknown) {
      if (latest.current !== asked) return;
      setError(e instanceof Error ? e.message : 'The team dashboard could not be loaded.');
    }
  }, [path]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const total = data?.total[period];
  const loading = !data && !error || (loadedFor !== path && !error);

  const renderTeam = (t: DashTeam) => {
    const id = t.leader?.agent_id || 'none';
    const open = expanded === id;
    const tot = t.totals[period];
    return (
      <View key={id} style={styles.team} testID={`dash-team-${id}`}>
        <TouchableOpacity
          style={styles.teamHead}
          onPress={() => setExpanded(open ? null : id)}
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          testID={`dash-team-toggle-${id}`}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.teamName} numberOfLines={1}>{t.leader?.name || 'No team leader'}</Text>
            <Text style={styles.teamSub}>{t.head_count} {t.head_count === 1 ? 'person' : 'people'} · {tot.sales} sales</Text>
          </View>
          <Text style={styles.teamAlp}>{formatMoney(tot.gross_alp)}</Text>
          <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={14} color={COLORS.textDim} />
        </TouchableOpacity>
        {open ? t.members.map((m) => (
          <View key={m.agent_id} style={styles.member} testID={`dash-member-${m.agent_id}`}>
            <View style={{ flex: 1 }}>
              <Text style={styles.memberName} numberOfLines={1}>{m.name}</Text>
              <Text style={styles.memberStates} numberOfLines={2}>{formatLicensedStates(m.licensed_states)}</Text>
            </View>
            <Text style={styles.memberAlp}>{formatMoney(m[period].gross_alp)}</Text>
          </View>
        )) : null}
      </View>
    );
  };

  return (
    <View style={styles.wrap} testID="team-dashboard-row">
      <View style={styles.head}>
        <Text style={styles.kicker}>YOUR TEAMS</Text>
        <TouchableOpacity
          style={[styles.chip, state && styles.chipOn]}
          onPress={() => setMenuOpen(true)}
          accessibilityRole="button"
          accessibilityLabel={`Licensed state: ${state || 'all'}. Change`}
          testID="team-dash-state"
        >
          <Text style={[styles.chipTxt, state && styles.chipTxtOn]}>{state ? `Licensed in ${state}` : 'All states'}</Text>
          <Ionicons name="chevron-down" size={11} color={state ? '#000' : COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <PeriodSegmented value={period} onChange={setPeriod} testID="team-dash-period" />
      <LoadState
        loading={loading}
        error={error}
        onRetry={load}
        isEmpty={!!data && data.teams.length === 0}
        emptyText={state ? noOneLicensedText(state) : 'No teams to show yet.'}
        testID="team-dash-load"
      >
        {total ? (
          <View style={styles.total} testID="team-dash-total">
            <Text style={styles.totalAlp}>{formatMoney(total.gross_alp)}</Text>
            <Text style={styles.totalSub}>{total.sales} sales · {Math.round(total.close_ratio)}% close ratio</Text>
          </View>
        ) : null}
        {data?.teams.map(renderTeam)}
      </LoadState>
      <Modal visible={menuOpen} transparent animationType="fade" onRequestClose={() => setMenuOpen(false)}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={() => setMenuOpen(false)}>
          <View style={styles.menu} testID="team-dash-state-menu">
            <ScrollView>
            <TouchableOpacity
              style={styles.menuItem}
              onPress={() => { setState(null); setMenuOpen(false); }}
              testID="team-dash-state-all"
            >
              <Text style={[styles.menuTxt, !state && { color: COLORS.gold }]}>All states</Text>
            </TouchableOpacity>
            {(data?.available_states || []).map((c) => (
              <TouchableOpacity
                key={c}
                style={styles.menuItem}
                onPress={() => { setState(c); setMenuOpen(false); }}
                testID={`team-dash-state-${c}`}
              >
                <Text style={[styles.menuTxt, state === c && { color: COLORS.gold }]}>{c}</Text>
              </TouchableOpacity>
            ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginHorizontal: 16, marginTop: 8, marginBottom: 8, padding: 12, backgroundColor: COLORS.surface, borderRadius: 10, borderWidth: 1, borderColor: COLORS.border, gap: 10 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  kicker: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 1.2 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, minHeight: 32, borderRadius: 6, borderWidth: 1, borderColor: COLORS.border },
  chipOn: { backgroundColor: COLORS.gold, borderColor: COLORS.gold },
  chipTxt: { color: COLORS.textDim, fontSize: 12, fontWeight: '800' },
  chipTxtOn: { color: '#000' },
  total: { alignItems: 'center', paddingVertical: 4 },
  totalAlp: { color: COLORS.text, fontSize: 26, fontWeight: '900' },
  totalSub: { color: COLORS.textDim, fontSize: 12, marginTop: 2 },
  team: { borderTopWidth: 1, borderTopColor: COLORS.border },
  teamHead: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10, minHeight: 44 },
  teamName: { color: COLORS.text, fontSize: 14, fontWeight: '800' },
  teamSub: { color: COLORS.textDim, fontSize: 11, marginTop: 1 },
  teamAlp: { color: COLORS.gold, fontSize: 14, fontWeight: '900' },
  member: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 6, paddingLeft: 12 },
  memberName: { color: COLORS.text, fontSize: 13, fontWeight: '700' },
  memberStates: { color: COLORS.textDim, fontSize: 11, marginTop: 1 },
  memberAlp: { color: COLORS.text, fontSize: 13, fontWeight: '800' },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center' },
  menu: { backgroundColor: COLORS.surface, borderRadius: 10, padding: 8, minWidth: 180, maxHeight: 420, borderWidth: 1, borderColor: COLORS.border },
  menuItem: { paddingVertical: 12, paddingHorizontal: 14, minHeight: 44, justifyContent: 'center' },
  menuTxt: { color: COLORS.text, fontSize: 14, fontWeight: '700' },
});
