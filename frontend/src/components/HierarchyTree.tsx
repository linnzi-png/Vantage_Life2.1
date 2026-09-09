// Renders one office's reporting structure as a top-down pyramid.
//
// Layout (owner's direction, 2026-09-09): the agency reads hierarchy as a
// pyramid, so the chart is drawn recursively -- each manager's card sits
// centred above a row of their reports, which are themselves subtrees. That
// keeps parents centred over children the way an org chart is drawn on a
// whiteboard, and it survives on a phone because the BOTTOM tier is collapsed:
// a manager's leaf-level agents never draw as cards. They roll up into one
// unmissable "N AGENTS / TAP TO SEE" button, and open as a full-width roster
// beneath the pyramid where each agent is tappable for call/text/email.
//
// Connectors are plain Views (a stem plus half-width bars per child), not an
// absolutely-positioned SVG canvas: the previous SVG version laid out fine
// natively but stranded the cards off-screen on the Expo web export, which is
// where most agents actually open the app.
import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, Role, levelNum, roleTitle, isFinanceAdmin } from '../lib/auth';

export interface HierarchyAgent {
  agent_id: string;
  name: string;
  office: string;
  role: Role;
  io_role?: string;
  phone?: string;
  email?: string;
  upline_id?: string | null;
  is_rookie?: boolean;
  non_producing?: boolean;
}

interface TreeNode {
  agent: HierarchyAgent;
  branches: TreeNode[];      // reports drawn as their own subtree
  leaves: HierarchyAgent[];  // agent-tier reports, collapsed behind the expander
}

const LINE = 'rgba(255,255,255,0.20)';
const STEM = 14;

function tierColor(role: Role): string {
  const lvl = levelNum(role);
  if (lvl >= 4) return COLORS.gold;
  if (lvl === 3) return COLORS.primary;
  if (lvl === 2) return COLORS.secondary;
  return COLORS.orange;
}

function buildForest(agents: HierarchyAgent[]): TreeNode[] {
  const byId = new Map(agents.map((a) => [a.agent_id, a]));
  const childIds = new Map<string, string[]>();
  const rootIds: string[] = [];
  for (const a of agents) {
    const uplineInOffice = a.upline_id && byId.has(a.upline_id);
    if (uplineInOffice) {
      const list = childIds.get(a.upline_id as string) || [];
      list.push(a.agent_id);
      childIds.set(a.upline_id as string, list);
    } else {
      rootIds.push(a.agent_id);
    }
  }
  const sortIds = (ids: string[]) =>
    [...ids].sort((x, y) => {
      const ax = byId.get(x)!, ay = byId.get(y)!;
      const lvlDiff = levelNum(ay.role) - levelNum(ax.role);
      return lvlDiff !== 0 ? lvlDiff : ax.name.localeCompare(ay.name);
    });

  const visiting = new Set<string>(); // cycle guard -- defends malformed upline chains
  function build(id: string, depth: number): TreeNode {
    const agent = byId.get(id)!;
    const node: TreeNode = { agent, branches: [], leaves: [] };
    if (visiting.has(id) || depth > 14) return node;
    visiting.add(id);
    for (const kid of sortIds(childIds.get(id) || [])) {
      const kidAgent = byId.get(kid)!;
      const hasOwnReports = (childIds.get(kid) || []).length > 0;
      // Collapse only the true bottom tier: an Agent with nobody under them.
      if (!hasOwnReports && levelNum(kidAgent.role) <= 1) {
        node.leaves.push(kidAgent);
      } else {
        node.branches.push(build(kid, depth + 1));
      }
    }
    visiting.delete(id);
    return node;
  }
  return sortIds(rootIds).map((id) => build(id, 0));
}

function AgentCard({ agent, onPress }: { agent: HierarchyAgent; onPress: () => void }) {
  const color = tierColor(agent.role);
  return (
    <TouchableOpacity
      style={[styles.card, { borderColor: color }]}
      onPress={onPress}
      activeOpacity={0.75}
      testID={`hierarchy-card-${agent.agent_id}`}
    >
      <View style={[styles.avatar, { backgroundColor: color }]}>
        <Text style={styles.avatarTxt}>{agent.name.slice(0, 1)}</Text>
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.name} numberOfLines={1}>{agent.name}</Text>
        <Text style={[styles.title, { color }]} numberOfLines={1}>
          {roleTitle(agent.io_role, agent.role) || agent.role.replace('level_', 'L')}
        </Text>
      </View>
      {agent.is_rookie ? (
        <View style={styles.rookie}><Text style={styles.rookieTxt}>R</Text></View>
      ) : null}
    </TouchableOpacity>
  );
}

function Subtree({
  node, isFirst, isLast, isRoot, openId, onToggle, onSelect,
}: {
  node: TreeNode;
  isFirst: boolean;
  isLast: boolean;
  isRoot: boolean;
  openId: string | null;
  onToggle: (id: string) => void;
  onSelect: (agent: HierarchyAgent) => void;
}) {
  const open = openId === node.agent.agent_id;
  const kids = node.branches;
  return (
    <View style={styles.subtree}>
      {/* half-bars join this cell to its siblings; the outermost halves stay
          blank. A root has nothing above it, so it draws no inbound connector. */}
      {isRoot ? null : (
        <>
          <View style={styles.barRow}>
            <View style={[styles.barHalf, isFirst ? null : styles.barOn]} />
            <View style={[styles.barHalf, isLast ? null : styles.barOn]} />
          </View>
          <View style={styles.stem} />
        </>
      )}

      <AgentCard agent={node.agent} onPress={() => onSelect(node.agent)} />

      {node.leaves.length > 0 ? (
        <>
          <View style={styles.stem} />
          <TouchableOpacity
            style={[styles.expander, open && styles.expanderOn]}
            onPress={() => onToggle(node.agent.agent_id)}
            activeOpacity={0.8}
            testID={`hierarchy-expand-${node.agent.agent_id}`}
          >
            <View style={styles.expanderRow}>
              <Text style={[styles.expanderCount, open && styles.expanderInk]}>{node.leaves.length}</Text>
              <Text style={[styles.expanderLabel, open && styles.expanderInk]}>
                {node.leaves.length === 1 ? 'AGENT' : 'AGENTS'}
              </Text>
              <Ionicons
                name={open ? 'chevron-up' : 'chevron-down'}
                size={13}
                color={open ? '#000' : COLORS.primary}
              />
            </View>
            <Text style={[styles.expanderHint, open && styles.expanderHintOn]}>
              {open ? 'TAP TO CLOSE' : 'TAP TO SEE'}
            </Text>
          </TouchableOpacity>
        </>
      ) : null}

      {kids.length > 0 ? (
        <>
          <View style={styles.stem} />
          <View style={styles.kidRow}>
            {kids.map((k, i) => (
              <Subtree
                key={k.agent.agent_id}
                node={k}
                isFirst={i === 0}
                isLast={i === kids.length - 1}
                isRoot={false}
                openId={openId}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ))}
          </View>
        </>
      ) : null}
    </View>
  );
}

function collectOpen(nodes: TreeNode[], id: string): TreeNode | null {
  for (const n of nodes) {
    if (n.agent.agent_id === id) return n;
    const found = collectOpen(n.branches, id);
    if (found) return found;
  }
  return null;
}

export function HierarchyTree({
  agents,
  onSelect,
}: {
  agents: HierarchyAgent[];
  onSelect: (agent: HierarchyAgent) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  // Non-producing members (app developer, office support) are part of the
  // team but not part of the reporting ladder, so they are lifted out of the
  // tree entirely and shown in their own band beneath it — present, clearly
  // set apart, and never drawn as a stray root of the pyramid.
  const { producing, staff } = useMemo(() => {
    const producing: HierarchyAgent[] = [];
    const staff: HierarchyAgent[] = [];
    // A Financial Admin is non-producing by definition (see FINANCE_ADMIN_ROLE
    // in backend/server.py) and carries no upline, so they belong in the band
    // too rather than floating as a root of the pyramid.
    for (const a of agents) {
      const outside = !!a.non_producing || isFinanceAdmin(a.role);
      (outside ? staff : producing).push(a);
    }
    staff.sort((x, y) => x.name.localeCompare(y.name));
    return { producing, staff };
  }, [agents]);
  const forest = useMemo(() => buildForest(producing), [producing]);
  const openNode = useMemo(
    () => (openId ? collectOpen(forest, openId) : null),
    [forest, openId],
  );

  if (agents.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTxt}>No one on file for this office yet.</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.page} showsVerticalScrollIndicator={false}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.canvas}
      >
        <View style={styles.kidRow}>
          {forest.map((n, i) => (
            <Subtree
              key={n.agent.agent_id}
              node={n}
              isFirst={i === 0}
              isLast={i === forest.length - 1}
              isRoot
              openId={openId}
              onToggle={(id) => setOpenId((cur) => (cur === id ? null : id))}
              onSelect={onSelect}
            />
          ))}
        </View>
      </ScrollView>

      {openNode ? (
        <View style={styles.roster}>
          <View style={styles.rosterHead}>
            <View style={styles.rosterAccent} />
            <View style={{ flex: 1 }}>
              <Text style={styles.rosterTitle} numberOfLines={1}>
                {openNode.agent.name.toUpperCase()} · {openNode.leaves.length}{' '}
                {openNode.leaves.length === 1 ? 'AGENT' : 'AGENTS'}
              </Text>
              <Text style={styles.rosterSub}>Tap anyone to call, text or email</Text>
            </View>
          </View>
          <View style={styles.rosterGrid}>
            {openNode.leaves.map((a) => (
              <TouchableOpacity
                key={a.agent_id}
                style={styles.rosterCard}
                onPress={() => onSelect(a)}
                activeOpacity={0.75}
                testID={`hierarchy-agent-${a.agent_id}`}
              >
                <View style={[styles.rosterAvatar, { backgroundColor: COLORS.orange }]}>
                  <Text style={styles.avatarTxt}>{a.name.slice(0, 1)}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.rosterName} numberOfLines={1}>{a.name}</Text>
                  <Text style={styles.rosterRole} numberOfLines={1}>
                    {roleTitle(a.io_role, a.role) || 'Agent'}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={COLORS.textMuted} />
              </TouchableOpacity>
            ))}
          </View>
        </View>
      ) : null}

      {staff.length > 0 ? (
        <View style={styles.staff}>
          <View style={styles.staffHead}>
            <Text style={styles.staffTitle}>TEAM SUPPORT</Text>
            <View style={styles.staffRule} />
          </View>
          <Text style={styles.staffSub}>Part of the team, outside the production hierarchy</Text>
          <View style={styles.staffRow}>
            {staff.map((a) => (
              <TouchableOpacity
                key={a.agent_id}
                style={styles.staffCard}
                onPress={() => onSelect(a)}
                activeOpacity={0.75}
                testID={`hierarchy-staff-${a.agent_id}`}
              >
                <View style={styles.staffAvatar}>
                  <Text style={styles.staffAvatarTxt}>{a.name.slice(0, 1)}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.staffName} numberOfLines={1}>{a.name}</Text>
                  <Text style={styles.staffRole} numberOfLines={1}>
                    {roleTitle(a.io_role, a.role) || 'Team Support'}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={COLORS.textMuted} />
              </TouchableOpacity>
            ))}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const CARD_W = 150;

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  canvas: { paddingHorizontal: 16, paddingTop: 4, minWidth: '100%', justifyContent: 'center' },
  empty: { padding: 40, alignItems: 'center' },
  emptyTxt: { color: COLORS.textDim, fontSize: 13 },

  subtree: { alignItems: 'center', paddingHorizontal: 6 },
  kidRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'center' },
  barRow: { flexDirection: 'row', height: 2, alignSelf: 'stretch' },
  barHalf: { flex: 1, height: 2 },
  barOn: { backgroundColor: LINE },
  stem: { width: 2, height: STEM, backgroundColor: LINE },

  card: {
    width: CARD_W,
    backgroundColor: COLORS.surface,
    borderWidth: 1.5,
    borderRadius: 8,
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  avatar: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  avatarTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  name: { color: '#fff', fontWeight: '800', fontSize: 12 },
  title: { fontSize: 10, fontWeight: '700', marginTop: 1 },
  rookie: {
    position: 'absolute', top: 4, right: 4,
    backgroundColor: COLORS.orange, borderRadius: 2, paddingHorizontal: 3,
  },
  rookieTxt: { color: '#000', fontWeight: '900', fontSize: 8 },

  // The one control that has to be unmissable.
  expander: {
    width: CARD_W,
    minHeight: 46,
    borderRadius: 8,
    borderWidth: 1.5,
    borderColor: COLORS.primary,
    backgroundColor: 'rgba(49,152,66,0.14)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 5,
  },
  expanderOn: { backgroundColor: COLORS.primary },
  expanderRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  expanderCount: { color: COLORS.primary, fontSize: 13, fontWeight: '900' },
  expanderLabel: { color: COLORS.primary, fontSize: 11, fontWeight: '900', letterSpacing: 0.4 },
  expanderInk: { color: '#000' },
  expanderHint: { color: COLORS.textMuted, fontSize: 8, fontWeight: '800', letterSpacing: 0.6, marginTop: 1 },
  expanderHintOn: { color: 'rgba(0,0,0,0.55)' },

  roster: {
    marginTop: 22,
    marginHorizontal: 16,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    paddingTop: 16,
  },
  rosterHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12 },
  rosterAccent: { width: 3, height: 22, borderRadius: 2, backgroundColor: COLORS.primary },
  rosterTitle: { color: COLORS.primary, fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  rosterSub: { color: COLORS.textMuted, fontSize: 10, fontWeight: '700', marginTop: 1 },
  rosterGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  rosterCard: {
    flexGrow: 1,
    flexBasis: '46%',
    minHeight: 58,
    backgroundColor: COLORS.surface,
    borderWidth: 1.5,
    borderColor: COLORS.orange,
    borderRadius: 8,
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rosterAvatar: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  rosterName: { color: '#fff', fontWeight: '800', fontSize: 11 },
  rosterRole: { color: COLORS.orange, fontSize: 9, fontWeight: '700', marginTop: 1 },

  // Deliberately drawn in neutral grey, not a tier colour: these people sit
  // outside the RGA/MGA/GA/Agent ladder the legend describes.
  staff: { marginTop: 26, marginHorizontal: 16 },
  staffHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  staffTitle: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.6 },
  staffRule: { flex: 1, height: 1, backgroundColor: COLORS.border },
  staffSub: { color: COLORS.textMuted, fontSize: 10, fontWeight: '700', marginTop: 4, marginBottom: 10 },
  staffRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  staffCard: {
    flexGrow: 1,
    flexBasis: '46%',
    minHeight: 58,
    backgroundColor: COLORS.surface,
    borderWidth: 1.5,
    borderColor: COLORS.textMuted,
    borderStyle: 'dashed',
    borderRadius: 8,
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  staffAvatar: {
    width: 26, height: 26, borderRadius: 13, backgroundColor: COLORS.textDim,
    alignItems: 'center', justifyContent: 'center',
  },
  staffAvatarTxt: { color: '#000', fontWeight: '900', fontSize: 12 },
  staffName: { color: '#fff', fontWeight: '800', fontSize: 11 },
  staffRole: { color: COLORS.textDim, fontSize: 9, fontWeight: '700', marginTop: 1 },
});
