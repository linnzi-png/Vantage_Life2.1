// Nightly Pulse Entry — mobile-first stepper
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, KeyboardAvoidingView, InputAccessoryView, Keyboard, Platform, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { api, COLORS, useAuth, levelNum, roleTitle } from '../../src/lib/auth';
import { BufferedPulse, PulsePayload, getUpcomingSalesDay, isBufferEntryEligible, isLateNightBuffer } from '../../src/lib/cycle';
import GateBanner from '../../src/components/GateBanner';
import { AgentContactSheet, AgentContact } from '../../src/components/AgentContactSheet';

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
  { key: 'pos_sits', label: 'POS Sits', hint: 'Policy Owner Service sits.', type: 'int' },
  { key: 'pos_sales', label: 'POS Sales', hint: 'Policy Owner Service sales.', type: 'int' },
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

// Fields start empty (placeholder shows 0) so the keypad types straight in
// with no leading "0"; blank parses to 0 in buildPayload.
const empty: PulseForm = {
  sets: '', sits: '', sales: '', ots_sits: '', ots_sales: '',
  n1: '', refs_obtained: '', ref_sits: '', ref_sales: '',
  pos_sits: '', pos_sales: '', vet_sits: '', vet_sales: '',
  gross_alp: '',
};

// Anchors the keyboard-docked NEXT bar (iOS) to the pulse TextInput.
const PULSE_ACCESSORY_ID = 'pulse-next-accessory-bar';

const BUFFER_KEY = 'vl_pulse_buffer';

async function readBuffer(): Promise<BufferedPulse[]> {
  try {
    const raw = await AsyncStorage.getItem(BUFFER_KEY);
    return raw ? (JSON.parse(raw) as BufferedPulse[]) : [];
  } catch {
    return [];
  }
}

async function appendToBuffer(entry: BufferedPulse): Promise<void> {
  const buf = await readBuffer();
  buf.push(entry);
  await AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(buf));
}

async function flushEligibleEntries(): Promise<number> {
  const buf = await readBuffer();
  const now = new Date();
  const remaining: BufferedPulse[] = [];
  let submitted = 0;
  for (const entry of buf) {
    if (isBufferEntryEligible(entry.sales_day, now)) {
      try {
        await api('/api/pulse', { method: 'POST', body: JSON.stringify({ ...entry.payload, sales_day: entry.sales_day }) });
        submitted++;
      } catch {
        remaining.push(entry); // re-queue on failure, retry next open
      }
    } else {
      remaining.push(entry);
    }
  }
  await AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(remaining));
  return submitted;
}

function buildPayload(form: PulseForm): PulsePayload {
  return {
    sets: Math.floor(parseFloat(form.sets || '0') || 0),
    sits: Math.floor(parseFloat(form.sits || '0') || 0),
    sales: Math.floor(parseFloat(form.sales || '0') || 0),
    ots_sits: Math.floor(parseFloat(form.ots_sits || '0') || 0),
    ots_sales: Math.floor(parseFloat(form.ots_sales || '0') || 0),
    n1: Math.floor(parseFloat(form.n1 || '0') || 0),
    refs_obtained: Math.floor(parseFloat(form.refs_obtained || '0') || 0),
    ref_sits: Math.floor(parseFloat(form.ref_sits || '0') || 0),
    ref_sales: Math.floor(parseFloat(form.ref_sales || '0') || 0),
    pos_sits: Math.floor(parseFloat(form.pos_sits || '0') || 0),
    pos_sales: Math.floor(parseFloat(form.pos_sales || '0') || 0),
    vet_sits: Math.floor(parseFloat(form.vet_sits || '0') || 0),
    vet_sales: Math.floor(parseFloat(form.vet_sales || '0') || 0),
    gross_alp: parseFloat(form.gross_alp || '0') || 0,
  };
}

export default function PulseScreen() {
  const { user } = useAuth();
  const [upline, setUpline] = useState<AgentContact | null>(null);
  const [contactOpen, setContactOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<PulseForm>(empty);
  const [today, setToday] = useState<{ entries: unknown[]; totals: { gross_alp: number; sales: number; sits: number }; gate: { state: string; message: string; color: string } | null; sales_day: string } | null>(null);
  const [streak, setStreak] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [inBuffer, setInBuffer] = useState(false);
  const [queued, setQueued] = useState(false);
  const [queuedDay, setQueuedDay] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [t, s, u] = await Promise.all([
        api<{ entries: unknown[]; totals: { gross_alp: number; sales: number; sits: number }; gate: { state: string; message: string; color: string } | null; sales_day: string }>('/api/pulse/me/today'),
        api<{ streak: number }>('/api/pulse/me/streak').catch(() => ({ streak: 0 })),
        api<{ upline: AgentContact | null }>('/api/my-upline').catch(() => ({ upline: null })),
      ]);
      setToday(t);
      setStreak(s.streak);
      setUpline(u.upline);
    } catch { /* not linked */ }
  }, []);

  useEffect(() => {
    setInBuffer(isLateNightBuffer());
    flushEligibleEntries().then(async (count) => {
      await refresh();
      if (count > 0) {
        Alert.alert(
          'Buffered pulse posted',
          `${count} queued pulse${count > 1 ? 's' : ''} posted to today's sales day.`,
        );
      }
    });
  }, [refresh]);

  const cur = STEPS[step];
  const done = step >= STEPS.length;

  const scrollRef = useRef<ScrollView | null>(null);
  const stepCardY = useRef(0);

  // Pin the step card to a uniform position whenever the step changes or the
  // keyboard opens, so the label + input are never hidden behind the keypad.
  const scrollToStepCard = useCallback(() => {
    scrollRef.current?.scrollTo({ y: Math.max(stepCardY.current - 8, 0), animated: true });
  }, []);
  useEffect(() => {
    if (!done) scrollToStepCard();
  }, [step, done, scrollToStepCard]);
  useEffect(() => {
    const sub = Keyboard.addListener('keyboardDidShow', scrollToStepCard);
    return () => sub.remove();
  }, [scrollToStepCard]);

  const goNext = useCallback(() => {
    if (step === STEPS.length - 1) Keyboard.dismiss();
    setStep((s) => Math.min(s + 1, STEPS.length));
  }, [step]);

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = buildPayload(form);

      if (inBuffer) {
        const salesDay = getUpcomingSalesDay();
        await appendToBuffer({ payload, sales_day: salesDay, queued_at: new Date().toISOString() });
        setQueuedDay(salesDay);
        setQueued(true);
        setForm(empty);
        setStep(0);
      } else {
        await api('/api/pulse', { method: 'POST', body: JSON.stringify(payload) });
        Alert.alert('Pulse logged', `${form.sales || '0'} sales · $${Math.round(parseFloat(form.gross_alp || '0')).toLocaleString()} ALP`);
        setForm(empty);
        setStep(0);
        await refresh();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit';
      Alert.alert('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  const totalAlp = today?.totals?.gross_alp ?? 0;
  const isPlayersClub = totalAlp >= 10000;

  // Memoised so the value is stable across renders within the same mount
  const entries = useMemo(() => (today?.entries ?? []) as Array<{ entry_id: string; is_adjustment: boolean; gross_alp: number; sales: number; sits: number; refs_obtained: number; submitted_at: string }>, [today]);

  if (!user?.agent_id) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={36} color={COLORS.orange} />
          <Text style={styles.notLinked}>{"This account isn't linked to an agent profile yet."}</Text>
          <Text style={styles.notLinkedSub}>{'Try the Demo Login screen and pick "AGENT" to test the Pulse flow.'}</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Show buffer banner during the dead zone; suppress the API gate banner */}
      {inBuffer ? (
        <View style={styles.bufferBanner} testID="buffer-banner">
          <Ionicons name="time-outline" size={16} color="#60A5FA" />
          <Text style={styles.bufferBannerText}>
            Late night buffer active · Your submission will post to today's sales day at 6:00 AM
          </Text>
        </View>
      ) : today?.gate ? (
        <GateBanner gate={today.gate} />
      ) : null}

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
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
            <Text style={styles.todayLabel}>{"TODAY'S RUNNING TOTAL"}</Text>
            <Text style={[styles.todayAlp, isPlayersClub && { color: COLORS.gold }]}>${Math.round(totalAlp).toLocaleString()}</Text>
            <Text style={styles.todayMeta}>{today?.totals?.sales ?? 0} sales · {today?.totals?.sits ?? 0} sits</Text>
            {isPlayersClub ? (
              <View style={styles.club}><Ionicons name="trophy" size={14} color={COLORS.gold} /><Text style={styles.clubTxt}>{"PLAYER'S CLUB · $10K HIT"}</Text></View>
            ) : null}
          </View>

          {/* Post-queue confirmation card — shown after buffering an entry */}
          {queued ? (
            <View style={styles.queuedCard} testID="queued-confirmation">
              <Ionicons name="checkmark-circle" size={28} color="#60A5FA" />
              <Text style={styles.queuedTitle}>Numbers safe — queued for 6:00 AM</Text>
              <Text style={styles.queuedSub}>
                Your Pulse for the {queuedDay} sales day has been received. It will be posted automatically the moment the sales day opens at 6:00 AM. No action needed.
              </Text>
              <TouchableOpacity style={styles.queuedBtn} onPress={() => setQueued(false)}>
                <Text style={styles.queuedBtnTxt}>LOG ANOTHER PULSE</Text>
              </TouchableOpacity>
            </View>
          ) : !done ? (
            <View
              style={styles.stepCard}
              testID="pulse-step-card"
              onLayout={(e) => { stepCardY.current = e.nativeEvent.layout.y; }}
            >
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
                blurOnSubmit={false}
                returnKeyType="next"
                onSubmitEditing={goNext}
                inputAccessoryViewID={Platform.OS === 'ios' ? PULSE_ACCESSORY_ID : undefined}
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
                  onPress={goNext}
                >
                  <Text style={styles.btnPrimaryTxt}>{step === STEPS.length - 1 ? 'REVIEW' : 'NEXT'}</Text>
                  <Ionicons name="arrow-forward" size={14} color="#000" />
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <View style={styles.stepCard} testID="pulse-review-card">
              <Text style={styles.kicker}>REVIEW & SUBMIT</Text>
              {inBuffer ? (
                <View style={styles.bufferReviewNote}>
                  <Ionicons name="time-outline" size={13} color="#60A5FA" />
                  <Text style={styles.bufferReviewNoteText}>
                    Will post to {getUpcomingSalesDay()} sales day at 6:00 AM
                  </Text>
                </View>
              ) : null}
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
                  <Text style={styles.btnPrimaryTxt}>
                    {submitting
                      ? (inBuffer ? 'QUEUING…' : 'SUBMITTING…')
                      : (inBuffer ? 'QUEUE FOR 6 AM' : 'SUBMIT PULSE')}
                  </Text>
                  <Ionicons name={inBuffer ? 'time-outline' : 'checkmark-circle'} size={14} color="#000" />
                </TouchableOpacity>
              </View>
            </View>
          )}

          <Text style={[styles.kicker, { marginTop: 18 }]}>TODAY'S ENTRIES</Text>
          {entries.filter((e) => !e.is_adjustment).length === 0 ? (
            <Text style={styles.empty}>No pulses logged for today yet.</Text>
          ) : (
            entries.filter((e) => !e.is_adjustment).map((e) => (
              <View key={e.entry_id} style={styles.entry}>
                <Text style={styles.entryAlp}>${Math.round(e.gross_alp || 0).toLocaleString()}</Text>
                <Text style={styles.entryMeta}>{e.sales} sales · {e.sits} sits · {e.refs_obtained} refs</Text>
                <Text style={styles.entryTs}>{(new Date(e.submitted_at)).toLocaleTimeString()}</Text>
              </View>
            ))
          )}

          {upline && levelNum(user?.role) < 4 ? (
            <TouchableOpacity
              style={styles.uplineCard}
              onPress={() => setContactOpen(true)}
              activeOpacity={0.75}
              testID="upline-contact-card"
            >
              <View style={styles.uplineLeft}>
                <Text style={styles.uplineKicker}>YOUR {roleTitle(upline.io_role, upline.role).toUpperCase()}</Text>
                <Text style={styles.uplineName}>{upline.name}</Text>
                {upline.office ? <Text style={styles.uplineOffice}>{upline.office}</Text> : null}
              </View>
              <View style={styles.uplineActions}>
                {upline.phone ? (
                  <View style={styles.uplineIcon}>
                    <Ionicons name="call" size={16} color={COLORS.primary} />
                  </View>
                ) : null}
                {upline.phone ? (
                  <View style={styles.uplineIcon}>
                    <Ionicons name="chatbubble" size={16} color={COLORS.secondary} />
                  </View>
                ) : null}
                <Ionicons name="chevron-forward" size={14} color={COLORS.textDim} />
              </View>
            </TouchableOpacity>
          ) : null}
        </ScrollView>

      <AgentContactSheet agent={contactOpen ? upline : null} onClose={() => setContactOpen(false)} />
      </KeyboardAvoidingView>

      {/* iOS numeric keypad has no return key, so dock NEXT directly above it —
          the step advances without ever scrolling or leaving the keypad. */}
      {Platform.OS === 'ios' && !done && !queued ? (
        <InputAccessoryView nativeID={PULSE_ACCESSORY_ID}>
          <View style={styles.accessoryBar}>
            <Text style={styles.accessoryStep} numberOfLines={1}>STEP {step + 1} OF {STEPS.length}</Text>
            <TouchableOpacity style={styles.accessoryBtn} onPress={goNext} testID="pulse-next-docked">
              <Text style={styles.btnPrimaryTxt}>{step === STEPS.length - 1 ? 'REVIEW' : 'NEXT'}</Text>
              <Ionicons name="arrow-forward" size={14} color="#000" />
            </TouchableOpacity>
          </View>
        </InputAccessoryView>
      ) : null}
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
  accessoryBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    backgroundColor: COLORS.surface, borderTopWidth: 1, borderTopColor: COLORS.border,
    paddingHorizontal: 16, paddingVertical: 8,
  },
  accessoryStep: { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 1.2, flexShrink: 1 },
  accessoryBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: COLORS.primary, paddingHorizontal: 22, paddingVertical: 10, borderRadius: 4,
  },
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
  entryAlp: { color: COLORS.primary, fontWeight: '900', fontSize: 14, fontVariant: ['tabular-nums' as never] },
  entryMeta: { color: COLORS.textDim, fontSize: 11, flex: 1, marginLeft: 8 },
  entryTs: { color: COLORS.textMuted, fontSize: 10 },
  // Late night buffer styles
  bufferBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    backgroundColor: '#0A1929', borderLeftWidth: 3, borderLeftColor: '#3B82F6',
  },
  bufferBannerText: { color: '#93C5FD', fontWeight: '700', fontSize: 12, flex: 1, letterSpacing: 0.3 },
  bufferReviewNote: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: '#0A1929', borderRadius: 4, paddingHorizontal: 10, paddingVertical: 7,
    marginBottom: 10, borderWidth: 1, borderColor: '#1E3A5F',
  },
  bufferReviewNoteText: { color: '#93C5FD', fontSize: 11, fontWeight: '700' },
  queuedCard: {
    backgroundColor: '#0A1929', borderWidth: 1, borderColor: '#1E3A5F',
    borderRadius: 6, padding: 20, marginTop: 8, alignItems: 'center', gap: 10,
  },
  queuedTitle: { color: '#fff', fontWeight: '900', fontSize: 16, textAlign: 'center' },
  queuedSub: { color: '#93C5FD', fontSize: 13, textAlign: 'center', lineHeight: 20 },
  queuedBtn: {
    marginTop: 6, borderWidth: 1, borderColor: '#3B82F6',
    paddingHorizontal: 18, paddingVertical: 10, borderRadius: 4,
  },
  queuedBtnTxt: { color: '#60A5FA', fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  uplineCard: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.primary,
    padding: 14, borderRadius: 6, marginTop: 18,
  },
  uplineLeft: { flex: 1 },
  uplineKicker: { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1.8, marginBottom: 3 },
  uplineName: { color: '#fff', fontWeight: '800', fontSize: 15 },
  uplineOffice: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  uplineActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  uplineIcon: {
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: COLORS.surface2,
    alignItems: 'center', justifyContent: 'center',
  },
});
