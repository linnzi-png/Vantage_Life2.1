// Missing Numbers — who has not submitted, per team, per night (owner,
// 2026-09-19, MJ's request 2.3). Reads GET /api/team/missing, which does the
// grouping (nearest SA/GA in the chain) and the scoping (the caller's own
// downline; level_4 sees every team), so this screen only lays it out.
//
// Tapping a person opens the same QuickEntryForm the Team tab uses, aimed at
// the night that was tapped, and ENTER ALL on a team walks that team's list
// for that night. Every entry still goes through can_enter_for server-side.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Stack } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, levelNum, roleTitle } from '../src/lib/auth';
import { QuickEntryForm, QuickEntryTarget } from '../src/components/QuickEntryForm';
import { LoadState } from '../src/components/LoadState';

interface Person { agent_id: string; name: string; role: string; io_role: string; office: string; }
interface TeamMissing { leader: Person | null; team_size: number; missing: Person[]; }
interface DayMissing { sales_day: string; total_missing: number; teams: TeamMissing[]; }
interface MissingResponse { today: string; days: DayMissing[]; scope: 'company' | 'downline'; }

function dayLabel(salesDay: string, index: number): string {
  if (index === 0) return 'TONIGHT';
  if (index === 1) return 'LAST NIGHT';
  const [y, m, d] = salesDay.split('-').map(Number);
  const date = new Date(y, (m || 1) - 1, d || 1);
  return `${date.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()} ${m}/${d}`;
}

export default function MissingScreen() {
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<MissingResponse | null>(null);
  const [dayIndex, setDayIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [target, setTarget] = useState<QuickEntryTarget | null>(null);
  const [queue, setQueue] = useState<Person[]>([]);
  // Which team section is open per day; all open by default so the count in
  // the chip and the names underneath never disagree.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const fetchAll = useCallback(async () => {
    try {
      const r = await api<MissingResponse>('/api/team/missing');
      setData(r);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Missing numbers could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetching + polling an external API, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchAll();
    const i = setInterval(fetchAll, 30000);
    return () => clearInterval(i);
  }, [fetchAll]);

  const day = data?.days[dayIndex] ?? null;

  const openOne = (p: Person) => {
    setQueue([]);
    setTarget({ agent_id: p.agent_id, name: p.name });
  };
  const enterAll = (team: TeamMissing) => {
    if (team.missing.length === 0) return;
    setQueue(team.missing.slice(1));
    setTarget({ agent_id: team.missing[0].agent_id, name: team.missing[0].name });
  };
  const advance = async () => {
    await fetchAll();
    setQueue((q) => {
      if (q.length === 0) { setTarget(null); return q; }
      const [next, ...rest] = q;
      setTarget({ agent_id: next.agent_id, name: next.name });
      return rest;
    });
  };

  if (authLoading) {
    return (
      <SafeAreaView style={styles.safe} edges={['bottom']}>
        <Stack.Screen options={{ title: 'MISSING NUMBERS', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
        <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>
      </SafeAreaView>
    );
  }

  if (levelNum(user?.role) < 2) {
    return (
      <SafeAreaView style={styles.safe} edges={['bottom']}>
        <Stack.Screen options={{ title: 'MISSING NUMBERS', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
        <View style={styles.center}>
          <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
          <Text style={styles.gateTxt}>Missing Numbers is for team leaders (SA, GA, MGA and RGA).</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <Stack.Screen options={{ title: 'MISSING NUMBERS', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <View style={styles.head}>
        <Text style={styles.kicker}>
          {data?.scope === 'company' ? 'EVERY TEAM · COMPANY-WIDE' : 'YOUR TEAMS'}
        </Text>
        <Text style={styles.title}>WHO HAS NOT SUBMITTED</Text>
      </View>

      {data ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.dayRow} style={{ flexGrow: 0 }}>
          {data.days.map((d, i) => {
            const on = i === dayIndex;
            return (
              <TouchableOpacity
                key={d.sales_day}
                onPress={() => setDayIndex(i)}
                style={[styles.dayChip, on && styles.dayChipOn, d.total_missing === 0 && !on && styles.dayChipClear]}
                testID={`missing-day-${d.sales_day}`}
              >
                <Text style={[styles.dayChipTxt, on && styles.dayChipTxtOn]}>{dayLabel(d.sales_day, i)}</Text>
                <View style={[styles.count, on && styles.countOn, d.total_missing === 0 && styles.countClear]}>
                  <Text style={[styles.countTxt, on && styles.countTxtOn]}>{d.total_missing}</Text>
                </View>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      ) : null}

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); }} tintColor={COLORS.primary} />}
      >
        <LoadState
          loading={loading}
          error={data ? null : error}
          onRetry={fetchAll}
          isEmpty={!!day && day.teams.length === 0}
          emptyText={day ? `Everyone on ${dayIndex === 0 ? 'your team' : 'the list'} submitted for ${dayLabel(day.sales_day, dayIndex).toLowerCase()}.` : 'Nothing to show.'}
          loadingText="Checking submissions…"
          testID="missing"
        >
          {day ? day.teams.map((team) => {
            const key = `${day.sales_day}:${team.leader?.agent_id ?? 'none'}`;
            const isCollapsed = !!collapsed[key];
            const leaderName = team.leader?.name ?? 'No upline on file';
            return (
              <View key={key} style={styles.team} testID={`missing-team-${team.leader?.agent_id ?? 'none'}`}>
                <TouchableOpacity
                  style={styles.teamHead}
                  onPress={() => setCollapsed((c) => ({ ...c, [key]: !isCollapsed }))}
                  activeOpacity={0.8}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.teamName} numberOfLines={1}>{leaderName.toUpperCase()}</Text>
                    <Text style={styles.teamMeta}>
                      {team.leader ? `${roleTitle(team.leader.io_role, team.leader.role)}${team.leader.office ? ` · ${team.leader.office}` : ''} · ` : ''}
                      {team.missing.length} of {team.team_size} missing
                    </Text>
                  </View>
                  <TouchableOpacity
                    style={styles.enterAll}
                    onPress={() => enterAll(team)}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    testID={`missing-enter-all-${team.leader?.agent_id ?? 'none'}`}
                  >
                    <Text style={styles.enterAllTxt}>ENTER ALL</Text>
                  </TouchableOpacity>
                  <Ionicons name={isCollapsed ? 'chevron-down' : 'chevron-up'} size={14} color={COLORS.textDim} />
                </TouchableOpacity>
                {isCollapsed ? null : team.missing.map((p) => (
                  <TouchableOpacity
                    key={p.agent_id}
                    style={styles.row}
                    onPress={() => openOne(p)}
                    activeOpacity={0.75}
                    testID={`missing-row-${p.agent_id}`}
                  >
                    <View style={styles.dot} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name} numberOfLines={1}>{p.name}</Text>
                      <Text style={styles.meta}>{roleTitle(p.io_role, p.role)}</Text>
                    </View>
                    <Text style={styles.action}>ENTER</Text>
                    <Ionicons name="chevron-forward" size={14} color={COLORS.textDim} />
                  </TouchableOpacity>
                ))}
              </View>
            );
          }) : null}
        </LoadState>
        <View style={{ height: 40 }} />
      </ScrollView>

      <QuickEntryForm
        target={target}
        initialSalesDay={day?.sales_day}
        onClose={() => { setTarget(null); setQueue([]); }}
        onSubmitted={advance}
        hasNext={queue.length > 0}
        onNext={advance}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  gateTxt: { color: COLORS.textDim, marginTop: 12, textAlign: 'center' },
  head: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  kicker: { color: COLORS.yellow, fontSize: 10, fontWeight: '900', letterSpacing: 2 },
  title: { color: '#fff', fontSize: 20, fontWeight: '900', marginTop: 2 },
  dayRow: { gap: 6, paddingHorizontal: 16, paddingVertical: 10 },
  dayChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  dayChipOn: { backgroundColor: COLORS.yellow, borderColor: COLORS.yellow },
  dayChipClear: { opacity: 0.6 },
  dayChipTxt: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 0.6 },
  dayChipTxtOn: { color: '#000' },
  count: { minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 5, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(234,179,8,0.18)' },
  countOn: { backgroundColor: 'rgba(0,0,0,0.18)' },
  countClear: { backgroundColor: 'rgba(49,152,66,0.18)' },
  countTxt: { color: COLORS.yellow, fontSize: 10, fontWeight: '900' },
  countTxtOn: { color: '#000' },
  scroll: { paddingHorizontal: 16, paddingTop: 4 },
  team: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.yellow, borderRadius: 6, marginBottom: 10, overflow: 'hidden',
  },
  teamHead: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12 },
  teamName: { color: '#fff', fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  teamMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  enterAll: { borderWidth: 1, borderColor: COLORS.yellow, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 5 },
  enterAllTxt: { color: COLORS.yellow, fontSize: 9, fontWeight: '900', letterSpacing: 0.8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 10, borderTopWidth: 1, borderTopColor: COLORS.border },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: COLORS.yellow },
  name: { color: '#fff', fontWeight: '800', fontSize: 14 },
  meta: { color: COLORS.textDim, fontSize: 11, marginTop: 1 },
  action: { color: COLORS.yellow, fontSize: 10, fontWeight: '900', letterSpacing: 0.8 },
});
