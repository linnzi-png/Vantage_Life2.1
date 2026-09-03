// Nightly Pulse Entry — mobile-first stepper
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, KeyboardAvoidingView, InputAccessoryView, Keyboard, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { api, COLORS, useAuth, levelNum, roleTitle } from '../../src/lib/auth';
import { BufferedPulse, PulsePayload, PULSE_FIELDS, isBufferEntryEligible, isLateNightWindow, makeClientEntryId, recentSalesDays, SELF_WINDOW_DAYS } from '../../src/lib/cycle';
import GateBanner from '../../src/components/GateBanner';
import { AgentContactSheet, AgentContact } from '../../src/components/AgentContactSheet';
import { TourAnchor } from '../../src/components/TourAnchor';
import { confirmAsync, notify } from '../../src/lib/dialog';

const STEPS = PULSE_FIELDS;

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

// ---- Self-correction window (owner spec 2026-08-22) ----
// Full totals for one sales day, as returned by GET /api/pulse/me/day.
interface DayTotals {
  sets: number; sits: number; sales: number; ots_sits: number; ots_sales: number;
  n1: number; refs_obtained: number; ref_sits: number; ref_sales: number;
  pos_sits: number; pos_sales: number; vet_sits: number; vet_sales: number;
  gross_alp: number; net_alp: number;
}
interface DayEntry { entry_id: string; is_adjustment?: boolean; is_nif?: boolean; gross_alp: number; sales: number; sits: number; refs_obtained: number; submitted_at: string }
interface DayData { entries: DayEntry[]; totals: DayTotals; sales_day: string }

// Pre-fill the stepper with a day's current summed totals so the agent edits
// the TRUE values in place (the server computes deltas).
function totalsToForm(t: DayTotals): PulseForm {
  return {
    sets: String(t.sets), sits: String(t.sits), sales: String(t.sales),
    ots_sits: String(t.ots_sits), ots_sales: String(t.ots_sales), n1: String(t.n1),
    refs_obtained: String(t.refs_obtained), ref_sits: String(t.ref_sits), ref_sales: String(t.ref_sales),
    pos_sits: String(t.pos_sits), pos_sales: String(t.pos_sales),
    vet_sits: String(t.vet_sits), vet_sales: String(t.vet_sales),
    gross_alp: String(t.gross_alp),
  };
}

function dayChipLabel(salesDay: string, index: number): string {
  if (index === 0) return 'Tonight';
  if (index === 1) return 'Yesterday';
  // salesDay is local YYYY-MM-DD; parse as local date, not UTC.
  const [y, m, d] = salesDay.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

const BUFFER_KEY = 'vl_pulse_buffer';

// Migration only: older builds queued late-night entries locally instead of
// posting them. New entries are never queued, but we still drain any leftover
// queued entries from those builds on mount. Safe to delete once no device
// holds a pre-fix buffer.
async function readBuffer(): Promise<BufferedPulse[]> {
  try {
    const raw = await AsyncStorage.getItem(BUFFER_KEY);
    return raw ? (JSON.parse(raw) as BufferedPulse[]) : [];
  } catch {
    return [];
  }
}

async function flushEligibleEntries(): Promise<number> {
  const buf = await readBuffer();
  const now = new Date();
  const remaining: BufferedPulse[] = [];
  let submitted = 0;
  for (const entry of buf) {
    if (isBufferEntryEligible(entry.sales_day, now)) {
      try {
        await api('/api/pulse', { method: 'POST', body: JSON.stringify({ ...entry.payload, sales_day: entry.sales_day, client_entry_id: entry.client_entry_id }) });
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
  const [nifSubmitting, setNifSubmitting] = useState(false);
  // True during the midnight–6 AM window; drives the "submit now" urgency
  // prompt only. Entries still post immediately.
  const [lateNight, setLateNight] = useState(false);

  // Day picker: today plus the last SELF_WINDOW_DAYS-1 sales days. Today
  // behaves exactly as before (new additive entry). A past day WITH entries
  // switches into correction mode (restate true totals → /api/pulse/correct);
  // a past day with NO entries is a plain backfill through /api/pulse.
  const dayOptions = useMemo(() => recentSalesDays(SELF_WINDOW_DAYS), []);
  const [salesDay, setSalesDay] = useState<string>(dayOptions[0]);
  const isToday = salesDay === dayOptions[0];
  const [dayData, setDayData] = useState<DayData | null>(null);
  const correctionMode = !isToday && (dayData?.entries?.length ?? 0) > 0;

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
    setLateNight(isLateNightWindow());
    flushEligibleEntries().then(async (count) => {
      await refresh();
      if (count > 0) {
        notify(
          'Pulse posted',
          `${count} pulse${count > 1 ? 's' : ''} from an earlier session posted to your sales day.`,
        );
      }
    });
  }, [refresh]);

  const cur = STEPS[step];
  const done = step >= STEPS.length;

  const scrollRef = useRef<ScrollView | null>(null);
  const stepCardY = useRef(0);
  const inputRef = useRef<TextInput | null>(null);

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

  // The TextInput never unmounts between steps (same JSX slot, just a new
  // `value`/key each render), so `autoFocus` only ever fires once on the
  // very first step. Tapping NEXT — an in-card button or the keyboard-docked
  // accessory bar — blurs the field, and without this it stayed blurred on
  // the next step, forcing a manual tap to reopen the keyboard for every one
  // of the 14 fields. Re-focus imperatively so the keyboard stays open and
  // entry stays continuous.
  useEffect(() => {
    if (!done) inputRef.current?.focus();
  }, [step, done]);

  const goNext = useCallback(() => {
    if (step === STEPS.length - 1) Keyboard.dismiss();
    setStep((s) => Math.min(s + 1, STEPS.length));
  }, [step]);

  // Persists across a failed submit so a retry reuses the same idempotency
  // key; reset only after the server confirms (or the entry is buffered).
  const pendingEntryId = useRef<string | null>(null);

  const onSelectDay = useCallback(async (d: string) => {
    setSalesDay(d);
    setStep(0);
    pendingEntryId.current = null;
    if (d === dayOptions[0]) {
      setDayData(null);
      setForm(empty);
      return;
    }
    try {
      const r = await api<DayData>(`/api/pulse/me/day?sales_day=${d}`);
      setDayData(r);
      // Correction mode pre-fills with current totals; a day with no entries
      // starts blank (backfill).
      setForm(r.entries.length > 0 ? totalsToForm(r.totals) : empty);
    } catch {
      setDayData(null);
      setForm(empty);
    }
  }, [dayOptions]);

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = buildPayload(form);
      // Always post immediately — including the midnight–6 AM window, where the
      // backend assigns the still-open (Midnight Miracle) sales day. No queuing.
      // The idempotency key survives a failed retry so a committed write can't
      // double-count.
      if (!pendingEntryId.current) pendingEntryId.current = makeClientEntryId();
      if (correctionMode) {
        // Restate the day's TRUE totals; the server computes per-field deltas
        // (including Gross ALP — the corrected number flows to the Platinum Wall).
        await api('/api/pulse/correct', { method: 'POST', body: JSON.stringify({ ...payload, sales_day: salesDay, client_entry_id: pendingEntryId.current }) });
        notify('Pulse corrected' /* TODO copy */, `Updated ${salesDay}: ${form.sales || '0'} sales · $${Math.round(parseFloat(form.gross_alp || '0')).toLocaleString()} ALP. This updates the Platinum Wall.` /* TODO copy */);
      } else {
        // Today: normal additive entry. Past day with no entries yet: a plain
        // backfill — same endpoint, explicit sales_day (3-day window enforced
        // server-side).
        await api('/api/pulse', { method: 'POST', body: JSON.stringify({ ...payload, ...(isToday ? {} : { sales_day: salesDay }), client_entry_id: pendingEntryId.current }) });
        notify('Pulse logged', `${form.sales || '0'} sales · $${Math.round(parseFloat(form.gross_alp || '0')).toLocaleString()} ALP`);
      }
      pendingEntryId.current = null;
      setForm(empty);
      setStep(0);
      await refresh();
      if (!isToday) await onSelectDay(salesDay); // re-pull the day's now-corrected totals
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit';
      notify('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  // Available on every step and on the review screen — logs today as NIF
  // (Not In Field): all 14 numbers zero, regardless of what's been typed so
  // far. Discards in-progress entries rather than saving them, since a NIF
  // day is a deliberate all-zero record, not a partial one.
  const onMarkNif = async () => {
    const ok = await confirmAsync({
      title: 'Mark today as NIF?',
      message: "This logs all 14 numbers as zero for today (Not In Field). Anything you've typed on this entry will be discarded.",
      confirmText: 'MARK NIF',
      destructive: true,
    });
    if (!ok) return;
    setNifSubmitting(true);
    try {
      const payload = buildPayload(empty);
      if (!pendingEntryId.current) pendingEntryId.current = makeClientEntryId();
      await api('/api/pulse', {
        method: 'POST',
        body: JSON.stringify({ ...payload, is_nif: true, client_entry_id: pendingEntryId.current }),
      });
      pendingEntryId.current = null;
      notify('Logged NIF', 'Today is recorded as Not In Field — all zeros.');
      setForm(empty);
      setStep(0);
      await refresh();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit';
      notify('Error', msg);
    } finally {
      setNifSubmitting(false);
    }
  };

  // Totals + entry list follow the selected day (today keeps its live data).
  const displayTotals = isToday ? today?.totals : dayData?.totals;
  const totalAlp = displayTotals?.gross_alp ?? 0;
  const isPlayersClub = totalAlp >= 10000;

  // Memoised so the value is stable across renders within the same mount
  const entries = useMemo(
    () => (isToday ? ((today?.entries ?? []) as DayEntry[]) : (dayData?.entries ?? [])),
    [isToday, today, dayData],
  );

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
      {/* Midnight–6 AM: simple urgency prompt (entries post immediately).
          Outside that window, defer to the backend-driven gate banner. */}
      {lateNight ? (
        <View style={styles.nightBanner} testID="late-night-banner">
          <Ionicons name="flash" size={16} color="#60A5FA" />
          <Text style={styles.nightBannerText}>Submit your numbers now</Text>
        </View>
      ) : today?.gate ? (
        <GateBanner gate={today.gate} />
      ) : null}

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.headRow}>
            <View>
              <Text style={styles.kicker}>NIGHTLY PULSE</Text>
              {/* TODO copy — placeholder heading for correction mode */}
              <Text style={styles.h1}>{correctionMode ? 'Correct a past day' : 'Log your sales day'}</Text>
            </View>
            <View style={styles.streakPill}>
              <Text style={styles.streakEmoji}>{streak >= 5 ? '🔥' : '⚡'}</Text>
              <Text style={styles.streakTxt}>{streak}d streak</Text>
            </View>
          </View>

          {/* Self-correction window: today + the last SELF_WINDOW_DAYS-1 days.
              Same chip pattern as QuickEntryForm's upline picker, scoped to 3. */}
          <TourAnchor id="pulse-days">
          <View style={styles.dayRowWrap}>
            <Text style={styles.dayKicker}>SALES DAY</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.dayRow}>
              {dayOptions.map((d, i) => (
                <TouchableOpacity
                  key={d}
                  style={[styles.dayChip, salesDay === d && styles.dayChipActive]}
                  onPress={() => onSelectDay(d)}
                  testID={`pulse-day-${d}`}
                >
                  <Text style={[styles.dayChipTxt, salesDay === d && styles.dayChipTxtActive]}>{dayChipLabel(d, i)}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
          </TourAnchor>

          {correctionMode ? (
            <View style={styles.correctionNote} testID="correction-banner">
              <Ionicons name="create-outline" size={14} color={COLORS.orange} />
              {/* TODO copy */}
              <Text style={styles.correctionNoteTxt}>Correction mode — fields show your current totals for this day. Edit any value and submit; the corrected numbers update the Platinum Wall.</Text>
            </View>
          ) : null}

          <View style={styles.todayCard}>
            <Text style={styles.todayLabel}>{isToday ? "TODAY'S RUNNING TOTAL" : `${salesDay} TOTAL`}</Text>
            <Text style={[styles.todayAlp, isPlayersClub && { color: COLORS.gold }]}>${Math.round(totalAlp).toLocaleString()}</Text>
            <Text style={styles.todayMeta}>{displayTotals?.sales ?? 0} sales · {displayTotals?.sits ?? 0} sits</Text>
            {isPlayersClub ? (
              <View style={styles.club}><Ionicons name="trophy" size={14} color={COLORS.gold} /><Text style={styles.clubTxt}>{"PLAYER'S CLUB · $10K HIT"}</Text></View>
            ) : null}
          </View>

          <TourAnchor id="pulse-stepper" onLayout={(e) => { stepCardY.current = e.nativeEvent.layout.y; }}>
          {!done ? (
            <View
              style={styles.stepCard}
              testID="pulse-step-card"
            >
              <View style={styles.progRow}>
                {STEPS.map((_, i) => (
                  <View key={i} style={[styles.progDot, i <= step && { backgroundColor: COLORS.primary }]} />
                ))}
              </View>
              <Text style={styles.stepNum}>STEP {step + 1} OF {STEPS.length}</Text>
              <Text style={styles.stepLabel}>{cur.label}</Text>
              <Text style={styles.stepHint}>{cur.hint}</Text>
              {correctionMode && cur.key === 'gross_alp' ? (
                /* TODO copy — Gross ALP corrections flow to the Platinum Wall (no lock, per owner) */
                <Text style={styles.wallNote}>This updates the Platinum Wall.</Text>
              ) : null}
              <TextInput
                ref={inputRef}
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
                {/* On iOS the keyboard-docked accessory bar already carries a NEXT/REVIEW
                    button right above the keypad — showing this one too meant tapping
                    NEXT twice (once on each) to advance. Android has no accessory view,
                    so it keeps this as its only NEXT affordance. */}
                {Platform.OS !== 'ios' ? (
                  <TouchableOpacity
                    style={[styles.btn, styles.btnPrimary]}
                    testID="pulse-next"
                    onPress={goNext}
                  >
                    <Text style={styles.btnPrimaryTxt}>{step === STEPS.length - 1 ? 'REVIEW' : 'NEXT'}</Text>
                    <Ionicons name="arrow-forward" size={14} color="#000" />
                  </TouchableOpacity>
                ) : null}
              </View>
              {isToday ? (
              <TouchableOpacity
                style={styles.nifBtn}
                onPress={onMarkNif}
                disabled={nifSubmitting}
                testID="pulse-nif"
              >
                <Ionicons name="close-circle-outline" size={13} color={COLORS.textDim} />
                <Text style={styles.nifTxt}>{nifSubmitting ? 'LOGGING NIF…' : 'NOT IN THE FIELD TODAY? MARK NIF'}</Text>
              </TouchableOpacity>
              ) : null}
            </View>
          ) : (
            <View style={styles.stepCard} testID="pulse-review-card">
              {/* TODO copy — correction-mode kicker */}
              <Text style={styles.kicker}>{correctionMode ? 'REVIEW CORRECTION' : 'REVIEW & SUBMIT'}</Text>
              {correctionMode ? (
                /* TODO copy */
                <Text style={styles.wallNote}>These replace the day's totals. Gross ALP updates the Platinum Wall.</Text>
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
                  <Text style={styles.btnPrimaryTxt}>{submitting ? 'SUBMITTING…' : correctionMode ? 'SUBMIT CORRECTION' /* TODO copy */ : 'SUBMIT PULSE'}</Text>
                  <Ionicons name="checkmark-circle" size={14} color="#000" />
                </TouchableOpacity>
              </View>
              {isToday ? (
              <TouchableOpacity
                style={styles.nifBtn}
                onPress={onMarkNif}
                disabled={nifSubmitting || submitting}
                testID="pulse-nif-review"
              >
                <Ionicons name="close-circle-outline" size={13} color={COLORS.textDim} />
                <Text style={styles.nifTxt}>{nifSubmitting ? 'LOGGING NIF…' : 'NOT IN THE FIELD TODAY? MARK NIF'}</Text>
              </TouchableOpacity>
              ) : null}
            </View>
          )}
          </TourAnchor>

          <Text style={[styles.kicker, { marginTop: 18 }]}>{isToday ? "TODAY'S ENTRIES" : 'ENTRIES FOR THIS DAY'}</Text>
          {entries.filter((e) => !e.is_adjustment).length === 0 ? (
            <Text style={styles.empty}>{isToday ? 'No pulses logged for today yet.' : 'No pulses logged for this day — submitting will log a new entry.' /* TODO copy */}</Text>
          ) : (
            entries.filter((e) => !e.is_adjustment).map((e) => (
              <View key={e.entry_id} style={styles.entry}>
                {e.is_nif ? (
                  <View style={styles.nifTag}><Text style={styles.nifTagTxt}>NIF</Text></View>
                ) : (
                  <Text style={styles.entryAlp}>${Math.round(e.gross_alp || 0).toLocaleString()}</Text>
                )}
                <Text style={styles.entryMeta}>
                  {e.is_nif ? 'Not in the field' : `${e.sales} sales · ${e.sits} sits · ${e.refs_obtained} refs`}
                </Text>
                <Text style={styles.entryTs}>{(new Date(e.submitted_at)).toLocaleTimeString()}</Text>
              </View>
            ))
          )}

          {upline && levelNum(user?.role) < 4 ? (
            <TourAnchor id="pulse-upline">
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
            </TourAnchor>
          ) : null}
        </ScrollView>

      <AgentContactSheet agent={contactOpen ? upline : null} onClose={() => setContactOpen(false)} />
      </KeyboardAvoidingView>

      {/* iOS numeric keypad has no return key, so dock NEXT directly above it —
          the step advances without ever scrolling or leaving the keypad. */}
      {Platform.OS === 'ios' && !done ? (
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
  wallNote: { color: COLORS.orange, fontSize: 11, fontWeight: '700', marginTop: 6 },
  // Day picker chips — same pattern as QuickEntryForm's upline picker.
  dayRowWrap: { marginTop: 4 },
  dayKicker: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.6, marginBottom: 8 },
  dayRow: { gap: 8 },
  dayChip: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  dayChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dayChipTxt: { color: COLORS.textDim, fontSize: 12, fontWeight: '800' },
  dayChipTxtActive: { color: '#000' },
  correctionNote: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 8,
    backgroundColor: 'rgba(255,140,0,0.08)', borderWidth: 1, borderColor: COLORS.orange,
    borderRadius: 6, padding: 10, marginTop: 10,
  },
  correctionNoteTxt: { color: COLORS.orange, fontSize: 11, fontWeight: '700', flex: 1, lineHeight: 15 },
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
  nifBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 12, paddingVertical: 8 },
  nifTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.4, textDecorationLine: 'underline' },
  nifTag: { alignSelf: 'flex-start', backgroundColor: 'rgba(255,255,255,0.08)', borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 2 },
  nifTagTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  reviewRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  reviewLabel: { color: COLORS.textDim, fontSize: 12 },
  reviewValue: { color: '#fff', fontWeight: '800', fontSize: 14 },
  empty: { color: COLORS.textMuted, fontSize: 12, marginTop: 8, textAlign: 'center' },
  entry: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 12, borderRadius: 6, marginTop: 6, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  entryAlp: { color: COLORS.primary, fontWeight: '900', fontSize: 14, fontVariant: ['tabular-nums' as never] },
  entryMeta: { color: COLORS.textDim, fontSize: 11, flex: 1, marginLeft: 8 },
  entryTs: { color: COLORS.textMuted, fontSize: 10 },
  // Midnight–6 AM urgency prompt
  nightBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    backgroundColor: '#0A1929', borderLeftWidth: 3, borderLeftColor: '#3B82F6',
  },
  nightBannerText: { color: '#93C5FD', fontWeight: '700', fontSize: 12, flex: 1, letterSpacing: 0.3 },
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
