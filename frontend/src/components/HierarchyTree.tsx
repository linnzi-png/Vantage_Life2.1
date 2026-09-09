// Renders one office's reporting structure as a card-and-connector org chart.
// Hand-rolled on react-native-svg (already used by Charts.tsx) rather than a
// tree/graph library — none is installed, and the layout this needs (a
// classic top-down org chart) is simple enough not to warrant one.
//
// Layout: every agent becomes a leaf or branch node; leaves are assigned
// increasing horizontal "slots" left to right, and each branch node centers
// itself over its children's slots (simple Reingold–Tilford-style centering,
// good enough at this scale). The whole tree is one absolutely-positioned
// canvas inside a single ScrollView (horizontal + vertical), with an SVG
// layer drawing elbow connectors underneath the cards — this keeps the lines
// perfectly aligned with the cards at any scroll position, which independently
// scrolling per-depth rows could not guarantee.
import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { COLORS, Role, levelNum, roleTitle } from '../lib/auth';

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
}

interface TreeNode {
  agent: HierarchyAgent;
  children: TreeNode[];
  depth: number;
  slot: number; // horizontal position in "slot" units, fractional for branch nodes
}

const CARD_W = 130;
const CARD_H = 74;
const COL_GAP = 18;
const COL_W = CARD_W + COL_GAP;
const ROW_H = 128;
const PAD = 28;

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
    // Anyone whose upline isn't in this office's own roster (or has none)
    // becomes a root of their own — keeps messy/legacy data from crashing
    // the layout instead of just looking a little unusual.
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

  let nextSlot = 0;
  const visiting = new Set<string>(); // cycle guard -- should never trigger, defends bad data
  function build(id: string, depth: number): TreeNode {
    const agent = byId.get(id)!;
    const node: TreeNode = { agent, children: [], depth, slot: 0 };
    if (visiting.has(id) || depth > 14) {
      node.slot = nextSlot++;
      return node;
    }
    visiting.add(id);
    const kids = sortIds(childIds.get(id) || []);
    node.children = kids.map((k) => build(k, depth + 1));
    visiting.delete(id);
    if (node.children.length === 0) {
      node.slot = nextSlot++;
    } else {
      const slots = node.children.map((c) => c.slot);
      node.slot = (Math.min(...slots) + Math.max(...slots)) / 2;
    }
    return node;
  }

  return sortIds(rootIds).map((id) => build(id, 0));
}

function flatten(nodes: TreeNode[], out: TreeNode[] = []): TreeNode[] {
  for (const n of nodes) {
    out.push(n);
    flatten(n.children, out);
  }
  return out;
}

export function HierarchyTree({
  agents,
  onSelect,
}: {
  agents: HierarchyAgent[];
  onSelect: (agent: HierarchyAgent) => void;
}) {
  const { forest, all, maxDepth, maxSlot } = useMemo(() => {
    const forest = buildForest(agents);
    const all = flatten(forest);
    const maxDepth = all.reduce((m, n) => Math.max(m, n.depth), 0);
    const maxSlot = all.reduce((m, n) => Math.max(m, n.slot), 0);
    return { forest, all, maxDepth, maxSlot };
  }, [agents]);

  if (agents.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTxt}>No one on file for this office yet.</Text>
      </View>
    );
  }

  const canvasW = PAD * 2 + (maxSlot + 1) * COL_W;
  const canvasH = PAD * 2 + (maxDepth + 1) * ROW_H;
  const cx = (n: TreeNode) => PAD + n.slot * COL_W + COL_W / 2;
  const cy = (n: TreeNode) => PAD + n.depth * ROW_H;

  const edges: string[] = [];
  for (const n of all) {
    for (const c of n.children) {
      const px = cx(n), py = cy(n) + CARD_H;
      const chx = cx(c), chy = cy(c);
      const midY = py + (ROW_H - CARD_H) / 2;
      edges.push(`M${px},${py} L${px},${midY} L${chx},${midY} L${chx},${chy}`);
    }
  }

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={{ padding: 4 }}>
      <ScrollView showsVerticalScrollIndicator contentContainerStyle={{ padding: 4 }}>
        <View style={{ width: canvasW, height: canvasH }}>
          <Svg width={canvasW} height={canvasH} style={StyleSheet.absoluteFill}>
            {edges.map((d, i) => (
              <Path key={i} d={d} stroke={COLORS.border} strokeWidth={2} fill="none" />
            ))}
          </Svg>
          {all.map((n) => {
            const color = tierColor(n.agent.role);
            const x = cx(n) - CARD_W / 2;
            const y = cy(n);
            return (
              <TouchableOpacity
                key={n.agent.agent_id}
                style={[styles.card, { left: x, top: y, borderColor: color }]}
                onPress={() => onSelect(n.agent)}
                activeOpacity={0.75}
                testID={`hierarchy-card-${n.agent.agent_id}`}
              >
                <View style={[styles.avatar, { backgroundColor: color }]}>
                  <Text style={styles.avatarTxt}>{n.agent.name.slice(0, 1)}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.name} numberOfLines={1}>{n.agent.name}</Text>
                  <Text style={[styles.title, { color }]} numberOfLines={1}>
                    {roleTitle(n.agent.io_role, n.agent.role) || n.agent.role.replace('level_', 'L')}
                  </Text>
                </View>
                {n.agent.is_rookie ? (
                  <View style={styles.rookie}><Text style={styles.rookieTxt}>R</Text></View>
                ) : null}
              </TouchableOpacity>
            );
          })}
        </View>
      </ScrollView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  empty: { padding: 40, alignItems: 'center' },
  emptyTxt: { color: COLORS.textDim, fontSize: 13 },
  card: {
    position: 'absolute',
    width: CARD_W,
    height: CARD_H,
    backgroundColor: COLORS.surface,
    borderWidth: 1.5,
    borderRadius: 8,
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  avatar: {
    width: 28, height: 28, borderRadius: 14,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  name: { color: '#fff', fontWeight: '800', fontSize: 12 },
  title: { fontSize: 10, fontWeight: '700', marginTop: 1 },
  rookie: {
    position: 'absolute', top: 4, right: 4,
    backgroundColor: COLORS.orange, borderRadius: 2, paddingHorizontal: 3,
  },
  rookieTxt: { color: '#000', fontWeight: '900', fontSize: 8 },
});
