// Hierarchy Map — company org chart, reachable from More for every linked
// agent (level_1+). Data comes from GET /api/hierarchy (a directory-only
// endpoint, no production/financial fields, open to anyone with a real agent
// profile). Editing (moving someone to a new upline) reuses the exact same
// /api/team/reassign flow and RBAC scope the Team tab already relies on —
// this screen adds no new write path, so a move here is instantly visible
// everywhere else in the app because it's the same underlying data.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Stack } from 'expo-router';
import { api, COLORS, useAuth, levelNum, Role } from '../src/lib/auth';
import { HierarchyTree, HierarchyAgent } from '../src/components/HierarchyTree';
import { AgentContactSheet } from '../src/components/AgentContactSheet';
import { MoveMemberSheet, MoveCandidate } from '../src/components/MoveMemberSheet';

interface TeamRow {
  agent_id: string; name: string; office: string; role: Role; io_role: string;
  archived: boolean;
}

export default function HierarchyScreen() {
  const { user, agent } = useAuth();
  const myLevel = levelNum(user?.role);
  const saTitle = (agent?.io_role || '').trim().toUpperCase() === 'SA';
  // Same "who may reassign" rule as the Team tab (owner's decision tree):
  // GA and above, never SA (SA is a level_2 title with no reassign rights).
  const canMoveAtAll = myLevel >= 2 && !(myLevel === 2 && saTitle);

  const [agents, setAgents] = useState<HierarchyAgent[]>([]);
  const [teamRows, setTeamRows] = useState<TeamRow[]>([]);
  const [office, setOffice] = useState<string | null>(null);
  const [selected, setSelected] = useState<HierarchyAgent | null>(null);
  const [moveTarget, setMoveTarget] = useState<TeamRow | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [h, t] = await Promise.all([
        api<{ agents: HierarchyAgent[] }>('/api/hierarchy'),
        canMoveAtAll ? api<{ team: TeamRow[] }>('/api/team') : Promise.resolve({ team: [] }),
      ]);
      setAgents(h.agents);
      setTeamRows(t.team);
    } catch {}
  }, [canMoveAtAll]);

  useEffect(() => {
    // Fetching an external API on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchAll();
  }, [fetchAll]);

  const offices = useMemo(() => {
    const counts = new Map<string, number>();
    for (const a of agents) counts.set(a.office || '(No Office)', (counts.get(a.office || '(No Office)') || 0) + 1);
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [agents]);

  // Default to the viewer's own office once the roster loads, falling back
  // to the first office alphabetically for admins with no agent link.
  useEffect(() => {
    if (office !== null || offices.length === 0) return;
    const mine = agent?.office && offices.some(([name]) => name === agent.office) ? agent.office : offices[0][0];
    // Deriving initial selection from freshly loaded data, not local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOffice(mine);
  }, [offices, office, agent?.office]);

  const officeAgents = useMemo(
    () => agents.filter((a) => (a.office || '(No Office)') === office),
    [agents, office],
  );

  const teamById = useMemo(() => new Map(teamRows.map((r) => [r.agent_id, r])), [teamRows]);

  const canMove = (a: HierarchyAgent): boolean => {
    if (!canMoveAtAll || a.agent_id === user?.agent_id) return false;
    const row = teamById.get(a.agent_id);
    if (!row || row.archived) return false;
    return levelNum(row.role) < myLevel;
  };

  const moveCandidates: MoveCandidate[] = moveTarget
    ? teamRows
        .filter((c) =>
          !c.archived && c.agent_id !== moveTarget.agent_id &&
          levelNum(c.role) >= levelNum(moveTarget.role) && levelNum(c.role) <= myLevel)
        .map((c) => ({ agent_id: c.agent_id, name: c.name, role: c.role, io_role: c.io_role, office: c.office }))
    : [];

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <Stack.Screen options={{ title: 'HIERARCHY MAP', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <View style={styles.head}>
        <Text style={styles.kicker}>WHO REPORTS TO WHOM</Text>
        <Text style={styles.title}>{office || 'HIERARCHY'}</Text>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.officeBar}
      >
        {offices.map(([name, count]) => (
          <TouchableOpacity
            key={name}
            onPress={() => setOffice(name)}
            style={[styles.officeChip, office === name && styles.officeChipOn]}
            testID={`hierarchy-office-${name}`}
          >
            <Text style={[styles.officeChipTxt, office === name && styles.officeChipTxtOn]}>
              {name.toUpperCase()} · {count}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <View style={styles.legend}>
        {([
          ['level_4', 'RGA', COLORS.gold],
          ['level_3', 'MGA', COLORS.primary],
          ['level_2', 'GA/SA', COLORS.secondary],
          ['level_1', 'Agent', COLORS.orange],
        ] as const).map(([, label, color]) => (
          <View key={label} style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: color }]} />
            <Text style={styles.legendTxt}>{label}</Text>
          </View>
        ))}
      </View>

      <View style={{ flex: 1 }}>
        {officeAgents.length === 0 && agents.length > 0 ? (
          <View style={styles.empty}><Text style={styles.emptyTxt}>Loading office…</Text></View>
        ) : (
          <HierarchyTree agents={officeAgents} onSelect={setSelected} />
        )}
      </View>

      <AgentContactSheet
        agent={selected}
        onClose={() => setSelected(null)}
        onMove={
          selected && canMove(selected)
            ? () => {
                const row = teamById.get(selected.agent_id);
                setSelected(null);
                if (row) setMoveTarget(row);
              }
            : undefined
        }
      />
      <MoveMemberSheet
        target={moveTarget}
        candidates={moveCandidates}
        onClose={() => setMoveTarget(null)}
        onMoved={fetchAll}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  head: { paddingHorizontal: 16, paddingTop: 12 },
  kicker: { color: COLORS.primary, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  title: { color: '#fff', fontSize: 20, fontWeight: '900', marginTop: 2 },
  officeBar: { gap: 8, paddingHorizontal: 16, paddingVertical: 10 },
  officeChip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  officeChipOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  officeChipTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  officeChipTxtOn: { color: '#000' },
  legend: { flexDirection: 'row', gap: 14, paddingHorizontal: 16, paddingBottom: 8, flexWrap: 'wrap' },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendTxt: { color: COLORS.textDim, fontSize: 10, fontWeight: '700' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyTxt: { color: COLORS.textDim },
});
