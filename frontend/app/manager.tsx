// Manager Command Panel — Net ALP Eraser (Level 4 only)
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, KeyboardAvoidingView, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, useRouter } from 'expo-router';
import { api, COLORS, useAuth, levelNum } from '../src/lib/auth';
import { TourAnchor } from '../src/components/TourAnchor';
import { notify } from '../src/lib/dialog';

interface AgentRow { agent_id: string; name: string; office: string; gross_alp: number; net_alp: number; sales: number; }

export default function ManagerScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [list, setList] = useState<AgentRow[]>([]);
  const [selected, setSelected] = useState<AgentRow | null>(null);
  const [newAlp, setNewAlp] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [salesDay, setSalesDay] = useState<string>('');

  useEffect(() => {
    (async () => {
      try {
        // Eraser adjusts a specific sales_day, so it always works off the
        // daily window regardless of the Team screen's period default.
        const r = await api<{ team: AgentRow[]; sales_day: string }>('/api/team?period=daily');
        setList(r.team.filter((x) => x.sales > 0).slice(0, 100));
        setSalesDay(r.sales_day);
      } catch (e: any) { notify('Error', e.message); }
    })();
  }, []);

  if (levelNum(user?.role) < 4) {
    return (
      <View style={styles.lock}><Ionicons name="lock-closed" size={32} color={COLORS.textDim} /><Text style={styles.lockTxt}>RGA-only command panel.</Text></View>
    );
  }

  const onSubmit = async () => {
    if (!selected) return notify('Pick an agent first.');
    const v = parseFloat(newAlp);
    if (isNaN(v)) return notify('Enter a valid Net ALP value.');
    if (reason.trim().length < 10) return notify('Reason must be at least 10 characters.');
    setBusy(true);
    try {
      const r = await api<{ ok: boolean; delta: number; audit: any }>('/api/manager/erase', {
        method: 'POST',
        body: JSON.stringify({ agent_id: selected.agent_id, sales_day: salesDay, new_alp: v, reason }),
      });
      notify('Adjusted', `Net ALP delta: ${r.delta >= 0 ? '+' : ''}$${Math.round(r.delta).toLocaleString()}\nGross unchanged on Platinum Wall.`);
      setSelected(null); setNewAlp(''); setReason('');
      // refresh list
      const fresh = await api<{ team: AgentRow[] }>('/api/team?period=daily');
      setList(fresh.team.filter((x) => x.sales > 0).slice(0, 100));
    } catch (e: any) { notify('Error', e.message || 'Failed'); }
    finally { setBusy(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: COLORS.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Stack.Screen options={{ title: 'COMMAND PANEL', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <TourAnchor id="manager-intro">
          <Text style={styles.kicker}>NET ALP ERASER · LEVEL 4</Text>
          <Text style={styles.intro}>Adjustments update Net ALP for internal reporting; Gross ALP on the Platinum Wall stays unchanged.</Text>
        </TourAnchor>

        {selected ? (
          <View style={styles.formCard} testID="erase-form">
            <View style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.formAgent}>{selected.name}</Text>
                <Text style={styles.formMeta}>{selected.office} · {salesDay}</Text>
                <Text style={styles.formMeta}>Current Net ALP: <Text style={styles.dollar}>${Math.round(selected.net_alp).toLocaleString()}</Text></Text>
                <Text style={styles.formMeta}>Gross ALP (locked): <Text style={styles.dollarLocked}>${Math.round(selected.gross_alp).toLocaleString()}</Text></Text>
              </View>
              <TouchableOpacity onPress={() => setSelected(null)} testID="erase-cancel"><Ionicons name="close" size={22} color={COLORS.textDim} /></TouchableOpacity>
            </View>
            <Text style={styles.label}>NEW NET ALP</Text>
            <TextInput
              testID="erase-alp-input"
              style={styles.input}
              value={newAlp}
              onChangeText={(v) => setNewAlp(v.replace(/[^0-9.]/g, ''))}
              placeholder="e.g. 4500"
              keyboardType="numeric"
              placeholderTextColor={COLORS.textMuted}
            />
            <Text style={styles.label}>REASON FOR ADJUSTMENT (≥10 chars)</Text>
            <TextInput
              testID="erase-reason-input"
              style={[styles.input, { height: 88, textAlignVertical: 'top' }]}
              value={reason}
              onChangeText={setReason}
              placeholder="Charge-back, NSF, replaced policy…"
              placeholderTextColor={COLORS.textMuted}
              multiline
            />
            <Text style={[styles.charCount, reason.trim().length < 10 && { color: COLORS.red }]}>
              {reason.trim().length}/10 minimum
            </Text>
            <TouchableOpacity
              testID="erase-submit"
              style={[styles.submit, (busy || reason.trim().length < 10 || !newAlp) && { opacity: 0.5 }]}
              disabled={busy || reason.trim().length < 10 || !newAlp}
              onPress={onSubmit}
            >
              <Ionicons name="warning" size={14} color="#000" />
              <Text style={styles.submitTxt}>{busy ? 'APPLYING…' : 'APPLY ADJUSTMENT'}</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <Text style={styles.kicker2}>SELECT AN AGENT</Text>
        )}

        <TouchableOpacity onPress={() => router.push('/audit')} style={styles.auditLink} testID="goto-audit">
          <Ionicons name="list" size={14} color={COLORS.primary} />
          <Text style={styles.auditTxt}>View Audit Log</Text>
        </TouchableOpacity>

        {list.map((a) => (
          <TouchableOpacity
            key={a.agent_id}
            onPress={() => setSelected(a)}
            style={[styles.agentRow, selected?.agent_id === a.agent_id && { borderColor: COLORS.primary }]}
            testID={`erase-pick-${a.agent_id}`}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.agentName}>{a.name}</Text>
              <Text style={styles.agentMeta}>{a.office} · {a.sales} sales</Text>
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.gross}>${Math.round(a.gross_alp).toLocaleString()}</Text>
              {Math.abs(a.gross_alp - a.net_alp) > 0.01 ? (
                <Text style={styles.netAlp}>NET ${Math.round(a.net_alp).toLocaleString()}</Text>
              ) : null}
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  lock: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg, padding: 30 },
  lockTxt: { color: COLORS.textDim, marginTop: 12 },
  kicker: { color: COLORS.orange, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  kicker2: { color: COLORS.textDim, fontWeight: '900', fontSize: 11, letterSpacing: 2, marginTop: 12 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, marginBottom: 14 },
  formCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.orange, borderRadius: 6, padding: 14, marginBottom: 16 },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  formAgent: { color: '#fff', fontWeight: '900', fontSize: 16 },
  formMeta: { color: COLORS.textDim, fontSize: 12, marginTop: 2 },
  dollar: { color: COLORS.primary, fontWeight: '800' },
  dollarLocked: { color: COLORS.gold, fontWeight: '800' },
  label: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.4, marginTop: 12 },
  input: { backgroundColor: '#000', color: '#fff', fontWeight: '700', borderWidth: 1, borderColor: COLORS.border, padding: 10, borderRadius: 4, marginTop: 4 },
  charCount: { color: COLORS.textMuted, fontSize: 10, marginTop: 4 },
  submit: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: COLORS.orange, paddingVertical: 13, borderRadius: 4, marginTop: 14 },
  submitTxt: { color: '#000', fontWeight: '900', letterSpacing: 1 },
  agentRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 12, borderRadius: 6, marginTop: 6 },
  agentName: { color: '#fff', fontWeight: '700' },
  agentMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  gross: { color: COLORS.primary, fontWeight: '900', fontVariant: ['tabular-nums' as any] },
  netAlp: { color: COLORS.orange, fontSize: 10, fontWeight: '800', marginTop: 2 },
  auditLink: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8, marginBottom: 8 },
  auditTxt: { color: COLORS.primary, fontWeight: '800', fontSize: 12 },
});
