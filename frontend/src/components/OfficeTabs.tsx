import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { COLORS } from '../lib/auth';

export interface OfficeRow { office: string; alp: number; sales: number; avg_deal: number; }

export default function OfficeTabs({ offices }: { offices: OfficeRow[] }) {
  const [active, setActive] = useState(offices[0]?.office || 'MCM');
  const cur = offices.find((o) => o.office === active) || offices[0];

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>OFFICE MARKET SHARE</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {offices.map((o) => {
          const sel = o.office === active;
          return (
            <TouchableOpacity
              key={o.office}
              testID={`office-tab-${o.office}`}
              onPress={() => setActive(o.office)}
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
  title: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginBottom: 8 },
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
