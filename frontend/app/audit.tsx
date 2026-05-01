// Audit Log — Level 4 only
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS } from '../src/lib/auth';

interface Audit {
  audit_id: string; ts: string; action: string;
  agent_name: string; changed_by_name?: string;
  original_value: number; new_value: number; delta: number;
  sales_day: string; reason: string;
}

export default function AuditScreen() {
  const [items, setItems] = useState<Audit[]>([]);
  useEffect(() => { (async () => { try { const r = await api<{ items: Audit[] }>('/api/manager/audit'); setItems(r.items); } catch {} })(); }, []);

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'AUDIT LOG', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 30 }}>
        <Text style={styles.kicker}>IMMUTABLE LEDGER</Text>
        <Text style={styles.intro}>Every Net ALP adjustment is recorded with a timestamp and a 10+ character reason.</Text>
        {items.length === 0 ? (
          <Text style={styles.empty}>No adjustments yet.</Text>
        ) : items.map((a) => (
          <View key={a.audit_id} style={styles.row} testID={`audit-${a.audit_id}`}>
            <View style={styles.rowHead}>
              <Ionicons name={a.delta < 0 ? 'remove-circle' : 'add-circle'} size={16} color={a.delta < 0 ? COLORS.red : COLORS.primary} />
              <Text style={styles.action}>{a.action.replace('_', ' ').toUpperCase()}</Text>
              <Text style={styles.ts}>{new Date(a.ts).toLocaleString()}</Text>
            </View>
            <Text style={styles.agent}>{a.agent_name} <Text style={styles.dim}>· {a.sales_day}</Text></Text>
            <View style={styles.values}>
              <View style={{ flex: 1 }}><Text style={styles.lab}>ORIGINAL</Text><Text style={styles.val}>${Math.round(a.original_value).toLocaleString()}</Text></View>
              <Ionicons name="arrow-forward" size={14} color={COLORS.textDim} />
              <View style={{ flex: 1, alignItems: 'flex-end' }}><Text style={styles.lab}>NEW</Text><Text style={styles.val}>${Math.round(a.new_value).toLocaleString()}</Text></View>
            </View>
            <Text style={styles.lab}>REASON</Text>
            <Text style={styles.reason}>"{a.reason}"</Text>
            <Text style={styles.by}>By {a.changed_by_name || a.action}</Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.orange, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  empty: { color: COLORS.textMuted, marginTop: 20, textAlign: 'center' },
  row: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 3, borderLeftColor: COLORS.orange, padding: 14, borderRadius: 6, marginTop: 8 },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  action: { color: '#fff', fontWeight: '900', fontSize: 12, letterSpacing: 1, flex: 1 },
  ts: { color: COLORS.textMuted, fontSize: 10 },
  agent: { color: '#fff', fontWeight: '700', marginTop: 6 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  values: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 6 },
  val: { color: '#fff', fontWeight: '900', fontSize: 14 },
  reason: { color: COLORS.text, fontStyle: 'italic', fontSize: 12, marginTop: 4 },
  by: { color: COLORS.textMuted, fontSize: 10, marginTop: 6 },
});
