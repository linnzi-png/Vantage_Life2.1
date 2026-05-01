// Nightly Pulse Entry — mobile-first stepper
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, KeyboardAvoidingView, Platform, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth } from '../../src/lib/auth';
import GateBanner from '../../src/components/GateBanner';

const STEPS: { key: keyof PulseForm; label: string; hint: string; type?: 'int' | 'money' }[] = [
  { key: 'sets', label: 'Total Appointments (Sets)', hint: 'Total appointments booked.', type: 'int' },
  { key: 'sits', label: 'Total Sits', hint: 'Total appointments you actually ran (excludes N1).', type: 'int' },
  { key: 'sales', label: 'Total Sales', hint: 'Total closed deals today.', type: 'int' },
  { key: 'ots_sits', label: 'On Spot Sits', hint: 'Sits run on the spot (walk-ins / same-day).', type: 'int' },
  { key: 'ots_sales', label: 'On Spot Sales', hint: 'Sales closed on the spot.', type: 'int' },
  { key: 'n1', label: 'Uninsurables (N1)', hint: 'Tracked but excluded from Sits totals.', type: 'int' },
  { key: 'refs_obtained', label: 'Referrals Collected', hint: 'Referrals you collected today.', type: 'int' },
  { key: 'ref_sits', label: 'Referral Sits', hint: 'Sits run from referrals.', type: 'int' },
  { key: 'ref_sales', label: 'Referral Sales', hint: 'Sales closed from referrals.', type: 'int' },
  { key: 'pos_sits', label: 'POS Sits', hint: 'Point-of-Sale sits.', type: 'int' },
  { key: 'pos_sales', label: 'POS Sales', hint: 'Point-of-Sale sales.', type: 'int' },
  { key: 'vet_sits', label: 'Response Card / Veteran Sits', hint: 'Sits from response cards or Veteran leads.', type: 'int' },
  { key: 'vet_sales', label: 'Response Card / Veteran Sales', hint: 'Sales from response cards or Veteran leads.', type: 'int' },
  { key: 'gross_alp', label: 'Total ALP for the Day (Gross ALP)', hint: 'Annual Life Premium for the day.', type: 'money' },
];

interface PulseForm {
  sets: string; sits: string; sales: string; ots_sits: string; ots_sales: string;
  n1: string; refs_obtained: string; ref_sits: string; ref_sales: string;
  pos_sits: string; pos_sales: string; vet_sits: string; vet_sales: string;
  gross_alp: string;
}

const empty: PulseForm = {
  sets: '0', sits: '0', sales: '0', ots_sits: '0', ots_sales: '0',
  n1: '0', refs_obtained: '0', ref_sits: '0', ref_sales: '0',
  pos_sits: '0', pos_sales: '0', vet_sits: '0', vet_sales: '0',
  gross_alp: '0',
};

export default function PulseScreen() {
  const { user } = useAuth();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<PulseForm>(empty);
  const [today, setToday] = useState<any>(null);
  const [streak, setStreak] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const refresh = async () => {
    try {
      const t = await api<{ entries: any[]; totals: any; gate: any; sales_day: string }>('/api/pulse/me/today');
      setToday(t);
      const s = await api<{ streak: number }>('/api/pulse/me/streak');
      setStreak(s.streak);
    } catch (e) { /* not linked */ }
  };

  useEffect(() => { refresh(); }, []);

  const cur = STEPS[step];
  const done = step >= STEPS.length;

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      const payload: any = {};
      STEPS.forEach((s) => {
        const v = parseFloat(form[s.key] || '0') || 0;
        payload[s.key] = s.type === 'money' ? v : Math.floor(v);
      });
      await api('/api/pulse', { method: 'POST', body: JSON.stringify(payload) });
      Alert.alert('Pulse logged', `${form.sales} sales · $${Math.round(parseFloat(form.gross_alp || '0')).toLocaleString()} ALP`);
      setForm(empty); setStep(0);
      await refresh();
    } catch (e: any) {
      Alert.alert('Error', e.message || 'Failed to submit');
    } finally { setSubmitting(false); }
  };

  const totalAlp = today?.totals?.gross_alp || 0;
  const isPlayersClub = totalAlp >= 10000;

  if (!user?.agent_id) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={36} color={COLORS.orange} />
          <Text style={styles.notLinked}>This account isn't linked to an agent profile yet.</Text>
          <Text style={styles.notLinkedSub}>Try the Demo Login screen and pick "AGENT" to test the Pulse flow.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {today?.gate ? <GateBanner gate={today.gate} /> : null}
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.headRow}>
            <View>
              <Text style={styles.kicker}>NIGHTLY PULSE</Text>
              <Text style={styles.h1}>Log your sales day</Text>
            </View>
            <View style={styles.streakPill}>
              <Text style={styles.streakEmoji}>{streak >= 5 ? '🔥' : '⚡'}</Text>
              <Text style={styles.streakTxt}>{streak}d streak</Text>
            </View>
          </View>

          <View style={styles.todayCard}>
            <Text style={styles.todayLabel}>TODAY'S RUNNING TOTAL</Text>
            <Text style={[styles.todayAlp, isPlayersClub && { color: COLORS.gold }]}>${Math.round(totalAlp).toLocaleString()}</Text>
            <Text style={styles.todayMeta}>{today?.totals?.sales || 0} sales · {today?.totals?.sits || 0} sits</Text>
            {isPlayersClub ? (
              <View style={styles.club}><Ionicons name="trophy" size={14} color={COLORS.gold} /><Text style={styles.clubTxt}>PLAYER'S CLUB · $10K HIT</Text></View>
            ) : null}
          </View>

          {!done ? (
            <View style={styles.stepCard} testID="pulse-step-card">
              <View style={styles.progRow}>
                {STEPS.map((_, i) => (
                  <View key={i} style={[styles.progDot, i <= step && { backgroundColor: COLORS.primary }]} />
                ))}
              </View>
              <Text style={styles.stepNum}>STEP {step + 1} OF {STEPS.length}</Text>
              <Text style={styles.stepLabel}>{cur.label}</Text>
              <Text style={styles.stepHint}>{cur.hint}</Text>
              <TextInput
                testID={`pulse-input-${cur.key}`}
                style={styles.input}
                value={form[cur.key]}
                onChangeText={(v) => setForm((p) => ({ ...p, [cur.key]: v.replace(/[^0-9.]/g, '') }))}
                keyboardType="numeric"
                placeholder="0"
                placeholderTextColor={COLORS.textMuted}
                selectTextOnFocus
                autoFocus
              />
              <View style={styles.btnRow}>
                {step > 0 ? (
                  <TouchableOpacity style={[styles.btn, styles.btnGhost]} onPress={() => setStep(step - 1)} testID="pulse-back">
                    <Text style={styles.btnGhostTxt}>BACK</Text>
                  </TouchableOpacity>
                ) : <View style={{ flex: 1 }} />}
                <TouchableOpacity
                  style={[styles.btn, styles.btnPrimary]}
                  testID="pulse-next"
                  onPress={() => setStep(step + 1)}
                >
                  <Text style={styles.btnPrimaryTxt}>{step === STEPS.length - 1 ? 'REVIEW' : 'NEXT'}</Text>
                  <Ionicons name="arrow-forward" size={14} color="#000" />
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <View style={styles.stepCard} testID="pulse-review-card">
              <Text style={styles.kicker}>REVIEW & SUBMIT</Text>
              {STEPS.map((s) => (
                <View key={s.key} style={styles.reviewRow}>
                  <Text style={styles.reviewLabel}>{s.label}</Text>
                  <Text style={styles.reviewValue}>
                    {s.type === 'money' ? `$${Math.round(parseFloat(form[s.key] || '0')).toLocaleString()}` : (form[s.key] || '0')}
                  </Text>
                </View>
              ))}
              <View style={styles.btnRow}>
                <TouchableOpacity style={[styles.btn, styles.btnGhost]} onPress={() => setStep(STEPS.length - 1)} testID="pulse-edit">
                  <Text style={styles.btnGhostTxt}>EDIT</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.btn, styles.btnPrimary]}
                  testID="pulse-submit"
                  disabled={submitting}
                  onPress={onSubmit}
                >
                  <Text style={styles.btnPrimaryTxt}>{submitting ? 'SUBMITTING…' : 'SUBMIT PULSE'}</Text>
                  <Ionicons name="checkmark-circle" size={14} color="#000" />
                </TouchableOpacity>
              </View>
            </View>
          )}

          <Text style={[styles.kicker, { marginTop: 18 }]}>TODAY'S ENTRIES</Text>
          {(today?.entries || []).filter((e: any) => !e.is_adjustment).length === 0 ? (
            <Text style={styles.empty}>No pulses logged for today yet.</Text>
          ) : (
            (today?.entries || []).filter((e: any) => !e.is_adjustment).map((e: any) => (
              <View key={e.entry_id} style={styles.entry}>
                <Text style={styles.entryAlp}>${Math.round(e.gross_alp || 0).toLocaleString()}</Text>
                <Text style={styles.entryMeta}>{e.sales} sales · {e.sits} sits · {e.refs_obtained} refs</Text>
                <Text style={styles.entryTs}>{(new Date(e.submitted_at)).toLocaleTimeString()}</Text>
              </View>
            ))
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: 16, paddingBottom: 60 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  notLinked: { color: '#fff', fontWeight: '800', fontSize: 16, marginTop: 12, textAlign: 'center' },
  notLinkedSub: { color: COLORS.textDim, marginTop: 6, textAlign: 'center' },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  h1: { color: '#fff', fontSize: 22, fontWeight: '900', marginTop: 2 },
  streakPill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4 },
  streakEmoji: { fontSize: 14 },
  streakTxt: { color: COLORS.text, fontWeight: '800', fontSize: 11 },
  todayCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopColor: COLORS.primary, borderTopWidth: 2, padding: 14, borderRadius: 6, marginVertical: 12 },
  todayLabel: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.6 },
  todayAlp: { color: '#fff', fontSize: 36, fontWeight: '900', marginTop: 4, letterSpacing: -1 },
  todayMeta: { color: COLORS.textDim, fontSize: 12, marginTop: 4 },
  club: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8, alignSelf: 'flex-start', backgroundColor: 'rgba(255,215,0,0.1)', paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: COLORS.gold, borderRadius: 4 },
  clubTxt: { color: COLORS.gold, fontWeight: '900', fontSize: 10, letterSpacing: 1 },
  stepCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 16, borderRadius: 6, marginTop: 8 },
  progRow: { flexDirection: 'row', gap: 4, marginBottom: 12 },
  progDot: { flex: 1, height: 3, backgroundColor: COLORS.border, borderRadius: 1 },
  stepNum: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.5 },
  stepLabel: { color: '#fff', fontSize: 22, fontWeight: '900', marginTop: 4 },
  stepHint: { color: COLORS.textDim, fontSize: 12, marginTop: 4 },
  input: {
    backgroundColor: '#000', color: '#fff', fontSize: 36, fontWeight: '900',
    borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: 14, paddingVertical: 14,
    marginTop: 14, borderRadius: 4,
  },
  btnRow: { flexDirection: 'row', gap: 8, marginTop: 14 },
  btn: { flex: 1, paddingVertical: 13, borderRadius: 4, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6 },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryTxt: { color: '#000', fontWeight: '900', letterSpacing: 1 },
  btnGhost: { borderWidth: 1, borderColor: COLORS.border, backgroundColor: 'transparent' },
  btnGhostTxt: { color: COLORS.textDim, fontWeight: '900', letterSpacing: 1 },
  reviewRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  reviewLabel: { color: COLORS.textDim, fontSize: 12 },
  reviewValue: { color: '#fff', fontWeight: '800', fontSize: 14 },
  empty: { color: COLORS.textMuted, fontSize: 12, marginTop: 8, textAlign: 'center' },
  entry: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 12, borderRadius: 6, marginTop: 6, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  entryAlp: { color: COLORS.primary, fontWeight: '900', fontSize: 14, fontVariant: ['tabular-nums' as any] },
  entryMeta: { color: COLORS.textDim, fontSize: 11, flex: 1, marginLeft: 8 },
  entryTs: { color: COLORS.textMuted, fontSize: 10 },
});
