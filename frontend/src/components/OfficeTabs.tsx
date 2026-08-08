import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { COLORS } from '../lib/auth';

export interface OfficeRow { office: string; alp: number; sales: number; avg_deal: number; }

export default function OfficeTabs({ offices, windowLabel }: {
  offices: OfficeRow[];
  /** What window these numbers cover, e.g. "WEEKLY" or "2026-06-10". Without it
   *  the section reads as stale, since the summary above it is always labelled. */
  windowLabel?: string;
}) {
  // Which office the user explicitly picked. Deliberately NOT seeded from
  // offices[0]: a useState initializer runs once on mount, when offices is still
  // empty, so the selection used to freeze on a placeholder that matched nothing
  // — no tab highlighted, while the body silently rendered offices[0]'s numbers.
  const [picked, setPicked] = useState<string | null>(null);

  // Derive the active office instead of storing it, so it self-corrects when the
  // list loads or when a period change drops the picked office from the roster.
  const cur = offices.find((o) => o.office === picked) ?? offices[0];
  const active = cur?.office;

  if (offices.length === 0) return null;

  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title}>OFFICE MARKET SHARE</Text>
        {windowLabel ? <Text style={styles.window}>{windowLabel}</Text> : null}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {offices.map((o) => {
          const sel = o.office === active;
          return (
            <TouchableOpacity
              key={o.office}
              testID={`office-tab-${o.office}`}
              onPress={() => setPicked(o.office)}
              style={[styles.tab, sel && styles.tabActive]}
            >
              <Text style={[styles.tabText, sel && styles.tabTextActive]}>{o.office.toUpperCase()}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
      {cur ? (
        <View style={styles.body}>
          <View style={styles.metricRow}>
            <Metric label="Office ALP" value={`$${Math.round(cur.alp).toLocaleString()}`} />
            <Metric label="Total Sales" value={`${cur.sales}`} />
            <Metric label="Avg Deal" value={`$${Math.round(cur.avg_deal).toLocaleString()}`} />
          </View>
        </View>
      ) : null}
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 16 },
  head: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 },
  title: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  window: { color: COLORS.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 1 },
  tabs: { gap: 6, paddingBottom: 8 },
  tab: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 4,
    backgroundColor: COLORS.surface,
  },
  tabActive: { borderColor: COLORS.primary, backgroundColor: 'rgba(49,152,66,0.12)' },
  tabText: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 1.2 },
  tabTextActive: { color: COLORS.primary },
  body: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderTopColor: COLORS.primary,
    borderTopWidth: 2,
    borderRadius: 6,
    padding: 12,
  },
  metricRow: { flexDirection: 'row', gap: 8 },
  metric: { flex: 1 },
  metricLabel: { color: COLORS.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 1.2 },
  metricValue: { color: COLORS.text, fontSize: 16, fontWeight: '900', marginTop: 4, letterSpacing: -0.3 },
});
