// Reusable summary card with delta indicator
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export default function StatCard({
  label, value, sub, deltaPct, accent, testID,
}: {
  label: string;
  value: string;
  sub?: string;
  deltaPct?: number;
  accent?: string;
  testID?: string;
}) {
  const pos = (deltaPct ?? 0) >= 0;
  return (
    <View style={[styles.card, accent ? { borderTopColor: accent, borderTopWidth: 2 } : null]} testID={testID}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      {sub ? <Text style={styles.sub}>{sub}</Text> : null}
      {typeof deltaPct === 'number' ? (
        <View style={styles.deltaRow}>
          <Ionicons
            name={pos ? 'arrow-up' : 'arrow-down'}
            size={12}
            color={pos ? COLORS.primary : COLORS.red}
          />
          <Text style={[styles.delta, { color: pos ? COLORS.primary : COLORS.red }]}>
            {pos ? '+' : ''}{deltaPct.toFixed(1)}% vs yest.
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 6,
    padding: 12,
    minHeight: 92,
    justifyContent: 'space-between',
  },
  label: { color: COLORS.textDim, fontSize: 10, fontWeight: '700', letterSpacing: 1.4, textTransform: 'uppercase' },
  value: { color: COLORS.text, fontSize: 22, fontWeight: '900', marginTop: 6, letterSpacing: -0.5 },
  sub: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  deltaRow: { flexDirection: 'row', alignItems: 'center', marginTop: 6, gap: 4 },
  delta: { fontSize: 11, fontWeight: '700' },
});
