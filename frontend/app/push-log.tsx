// Push Delivery Log — Level 4 only. Every push Expo was asked to send, both
// delivered and rejected — Expo returns HTTP 200 even for a rejected
// message, so this is the only place a silent drop (stale token, missing
// push credentials, etc.) ever becomes visible. Grouped by office/team, and
// by hierarchy level within a team, so it reads like a roster rather than a
// flat timestamp feed.
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS, levelNum, roleTitle, Role } from '../src/lib/auth';

interface PushLogEntry {
  push_token: string; title: string; body: string; status: 'ok' | 'error';
  error_code?: string | null; error_message?: string | null; ts: string;
  recipient_name?: string | null; recipient_office?: string | null;
  recipient_role?: Role | null; recipient_io_role?: string | null;
}

const UNASSIGNED_TEAM = 'Unassigned / Admin';

function recipientLabel(f: PushLogEntry): string {
  if (f.recipient_name) return f.recipient_name;
  return `Unknown device (${f.push_token.slice(0, 24)}…)`;
}

export default function PushLogScreen() {
  const [items, setItems] = useState<PushLogEntry[]>([]);
  useEffect(() => { (async () => { try { const r = await api<{ items: PushLogEntry[] }>('/api/admin/push-log'); setItems(r.items); } catch {} })(); }, []);

  // Group by office (team); within a team, highest hierarchy level first,
  // then most recent send first.
  const groups = useMemo(() => {
    const byTeam = new Map<string, PushLogEntry[]>();
    for (const f of items) {
      const team = f.recipient_office || UNASSIGNED_TEAM;
      if (!byTeam.has(team)) byTeam.set(team, []);
      byTeam.get(team)!.push(f);
    }
    for (const rows of byTeam.values()) {
      rows.sort((a, b) => levelNum(b.recipient_role) - levelNum(a.recipient_role) || +new Date(b.ts) - +new Date(a.ts));
    }
    return [...byTeam.entries()].sort(([a], [b]) => {
      if (a === UNASSIGNED_TEAM) return 1;
      if (b === UNASSIGNED_TEAM) return -1;
      return a.localeCompare(b);
    });
  }, [items]);

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'PUSH DELIVERY LOG', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 30 }}>
        <Text style={styles.kicker}>SEND HISTORY BY TEAM</Text>
        <Text style={styles.intro}>Every push VantageLife has asked Expo to send, grouped by the recipient's office and hierarchy level. A rejected push never reaches the recipient — Expo still answers "OK" for the request, so this is the only place that becomes visible.</Text>
        {groups.length === 0 ? (
          <Text style={styles.empty}>No pushes recorded yet.</Text>
        ) : groups.map(([team, rows]) => (
          <View key={team} style={styles.teamBlock}>
            <Text style={styles.teamHeader}>{team}</Text>
            {rows.map((f, i) => {
              const failed = f.status === 'error';
              const title = roleTitle(f.recipient_io_role, f.recipient_role);
              return (
                <View key={`${f.push_token}-${f.ts}-${i}`} style={[styles.row, failed ? styles.rowError : styles.rowOk]}>
                  <View style={styles.rowHead}>
                    <Ionicons name={failed ? 'alert-circle' : 'checkmark-circle'} size={16} color={failed ? COLORS.red : COLORS.primary} />
                    <Text style={styles.recipient} numberOfLines={1}>{recipientLabel(f)}</Text>
                    <Text style={styles.ts}>{new Date(f.ts).toLocaleString()}</Text>
                  </View>
                  {title ? <Text style={styles.title}>{title}</Text> : null}
                  <Text style={styles.status}>{failed ? (f.error_code || 'UNKNOWN ERROR') : 'DELIVERED'}</Text>
                  <Text style={styles.body} numberOfLines={2}>{f.title} — {f.body}</Text>
                  {failed && f.error_message ? <Text style={styles.msg}>{f.error_message}</Text> : null}
                </View>
              );
            })}
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
  teamBlock: { marginTop: 18 },
  teamHeader: { color: COLORS.textMuted, fontWeight: '900', fontSize: 11, letterSpacing: 1.5, marginBottom: 4, textTransform: 'uppercase' },
  row: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 3, padding: 14, borderRadius: 6, marginTop: 8 },
  rowError: { borderLeftColor: COLORS.red },
  rowOk: { borderLeftColor: COLORS.primary },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  recipient: { color: '#fff', fontWeight: '900', fontSize: 13, flex: 1 },
  ts: { color: COLORS.textMuted, fontSize: 10 },
  title: { color: COLORS.textDim, fontSize: 11, fontWeight: '700', marginTop: 2 },
  status: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1, marginTop: 6 },
  body: { color: '#fff', fontWeight: '700', marginTop: 4 },
  msg: { color: COLORS.textDim, fontSize: 12, marginTop: 4, fontStyle: 'italic' },
});
