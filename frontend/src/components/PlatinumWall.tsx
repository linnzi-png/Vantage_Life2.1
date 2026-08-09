import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export interface WallItem {
  agent_id: string; name: string; office: string; gross_alp: number; sales: number;
  // null = tenure never recorded, which is most of the roster.
  is_rookie?: boolean | null; role?: string; io_role?: string; phone?: string; email?: string;
}
export interface PlatinumRulePost { shoutout_id: string; agent_name: string; office: string; reason: string; posted_by?: string; }

const PLATINUM = '#E5E4E2';

export default function PlatinumWall(
  { vets, rookies, unranked = [], platinum = [], windowLabel, onPress }:
  {
    vets: WallItem[]; rookies: WallItem[];
    /** Top producers whose tenure was never recorded. Shown rather than hidden
     *  so nobody silently disappears from the wall — see the Unranked panel. */
    unranked?: WallItem[];
    platinum?: PlatinumRulePost[];
    windowLabel?: string;
    onPress?: (item: WallItem) => void;
  },
) {
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title}>PLATINUM WALL</Text>
        {windowLabel ? <Text style={styles.window}>{windowLabel}</Text> : null}
      </View>
      <View style={styles.row}>
        <Panel title="TOP 3 VETS" color={COLORS.gold} icon="ribbon" items={vets} testID="platinum-vets" onPress={onPress} />
        <View style={{ width: 8 }} />
        <Panel title="TOP 3 ROOKIES" color={COLORS.orange} icon="rocket" items={rookies} testID="platinum-rookies" onPress={onPress} />
      </View>
      {unranked.length ? (
        <View style={{ marginTop: 8 }}>
          <Panel
            title="TOP 3 — TENURE NOT SET"
            color={COLORS.textDim}
            icon="help-circle"
            items={unranked}
            testID="platinum-unranked"
            onPress={onPress}
          />
          <Text style={styles.hint}>
            Set Veteran or Rookie in Admin to rank these agents.
          </Text>
        </View>
      ) : null}
      {platinum.length ? (
        <View style={[styles.panel, { borderTopColor: PLATINUM, marginTop: 8 }]} testID="platinum-rule-strip">
          <View style={styles.panelHeader}>
            <Ionicons name="medal" size={14} color={PLATINUM} />
            <Text style={[styles.panelTitle, { color: PLATINUM }]}>PLATINUM RULE</Text>
          </View>
          {platinum.map((p) => (
            <View key={p.shoutout_id} style={styles.item}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{p.agent_name} <Text style={styles.meta}>· {p.office}</Text></Text>
                <Text style={[styles.meta, { fontStyle: 'italic' }]} numberOfLines={2}>"{p.reason}"</Text>
              </View>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Panel({ title, color, icon, items, testID, onPress }: any) {
  return (
    <View style={[styles.panel, { borderTopColor: color }]} testID={testID}>
      <View style={styles.panelHeader}>
        <Ionicons name={icon} size={14} color={color} />
        <Text style={[styles.panelTitle, { color }]}>{title}</Text>
      </View>
      {items?.length ? items.map((it: WallItem, i: number) => (
        <TouchableOpacity
          key={it.agent_id}
          style={styles.item}
          onPress={() => onPress?.(it)}
          activeOpacity={0.7}
          testID={`platinum-item-${it.agent_id}`}
        >
          <Text style={[styles.rank, { color }]}>{i + 1}</Text>
          <View style={{ flex: 1, marginLeft: 8 }}>
            <Text style={styles.name} numberOfLines={1}>{it.name}</Text>
            <Text style={styles.meta}>{it.office} · {it.sales} sales</Text>
          </View>
          <Text style={styles.alp}>${Math.round(it.gross_alp).toLocaleString()}</Text>
        </TouchableOpacity>
      )) : (
        <Text style={styles.empty}>No production in this period.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 16 },
  head: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 },
  title: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  window: { color: COLORS.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 1 },
  hint: { color: COLORS.textMuted, fontSize: 10, marginTop: 6, fontStyle: 'italic' },
  row: { flexDirection: 'row' },
  panel: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 6,
    borderTopWidth: 2,
    padding: 10,
  },
  panelHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 },
  panelTitle: { fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  item: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderTopWidth: 1, borderTopColor: COLORS.border },
  rank: { fontSize: 18, fontWeight: '900', width: 16, textAlign: 'center' },
  name: { color: COLORS.text, fontSize: 12, fontWeight: '700' },
  meta: { color: COLORS.textMuted, fontSize: 10 },
  alp: { color: COLORS.primary, fontSize: 13, fontWeight: '900', fontVariant: ['tabular-nums' as any] },
  empty: { color: COLORS.textMuted, fontSize: 11, paddingVertical: 8, textAlign: 'center' },
});
