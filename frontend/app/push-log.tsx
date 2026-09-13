// Push Delivery Log — Level 4 only. Every push Expo was asked to send, both
// delivered and rejected — Expo returns HTTP 200 even for a rejected
// message, so this is the only place a silent drop (stale token, missing
// push credentials, etc.) ever becomes visible.
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS } from '../src/lib/auth';

interface PushLogEntry {
  push_token: string; title: string; body: string; status: 'ok' | 'error';
  error_code?: string | null; error_message?: string | null; ts: string;
}

export default function PushLogScreen() {
  const [items, setItems] = useState<PushLogEntry[]>([]);
  useEffect(() => { (async () => { try { const r = await api<{ items: PushLogEntry[] }>('/api/admin/push-log'); setItems(r.items); } catch {} })(); }, []);

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'PUSH DELIVERY LOG', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 30 }}>
        <Text style={styles.kicker}>SEND HISTORY</Text>
        <Text style={styles.intro}>Every push VantageLife has asked Expo to send, delivered and rejected alike. A rejected push never reaches the recipient — Expo still answers "OK" for the request, so this is the only place that becomes visible.</Text>
        {items.length === 0 ? (
          <Text style={styles.empty}>No pushes recorded yet.</Text>
        ) : items.map((f, i) => {
          const failed = f.status === 'error';
          return (
            <View key={`${f.push_token}-${f.ts}-${i}`} style={[styles.row, failed ? styles.rowError : styles.rowOk]}>
              <View style={styles.rowHead}>
                <Ionicons name={failed ? 'alert-circle' : 'checkmark-circle'} size={16} color={failed ? COLORS.red : COLORS.primary} />
                <Text style={styles.code}>{failed ? (f.error_code || 'UNKNOWN ERROR') : 'DELIVERED'}</Text>
                <Text style={styles.ts}>{new Date(f.ts).toLocaleString()}</Text>
              </View>
              <Text style={styles.body} numberOfLines={2}>{f.title} — {f.body}</Text>
              {failed && f.error_message ? <Text style={styles.msg}>{f.error_message}</Text> : null}
              <Text style={styles.token} numberOfLines={1}>{f.push_token}</Text>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.orange, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  empty: { color: COLORS.textMuted, marginTop: 20, textAlign: 'center' },
  row: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 3, padding: 14, borderRadius: 6, marginTop: 8 },
  rowError: { borderLeftColor: COLORS.red },
  rowOk: { borderLeftColor: COLORS.primary },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  code: { color: '#fff', fontWeight: '900', fontSize: 12, letterSpacing: 1, flex: 1 },
  ts: { color: COLORS.textMuted, fontSize: 10 },
  body: { color: '#fff', fontWeight: '700', marginTop: 6 },
  msg: { color: COLORS.textDim, fontSize: 12, marginTop: 4, fontStyle: 'italic' },
  token: { color: COLORS.textMuted, fontSize: 10, marginTop: 6 },
});
