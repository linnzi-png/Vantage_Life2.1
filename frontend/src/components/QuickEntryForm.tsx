// Condensed one-screen Nightly Numbers entry — all 14 fields at once, no
// stepping. Built for uplines (level_2+) entering on behalf of a downline
// agent, where speed matters more than the guided one-field-at-a-time flow
// self-entry uses (that flow stays untouched in pulse.tsx).
import React, { useRef, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, Modal, KeyboardAvoidingView, Platform, Alert, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { PULSE_FIELDS, PulsePayload, recentSalesDays, currentSalesDay, makeClientEntryId } from '../lib/cycle';

// Matches MAX_UPLINE_BUFFER_DAYS on the backend: an upline may enter for a
// downline agent up to 7 sales days back.
const UPLINE_WINDOW_DAYS = 7;

function dayChipLabel(salesDay: string, index: number): string {
  if (index === 0) return 'Tonight';
  if (index === 1) return 'Yesterday';
  // salesDay is local YYYY-MM-DD; parse as local date, not UTC.
  const [y, m, d] = salesDay.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric' });
}

export interface QuickEntryTarget {
  agent_id: string;
  name: string;
}

interface Props {
  target: QuickEntryTarget | null;
  onClose: () => void;
  // Called after a successful submit. `hasNext` lets the caller decide whether
  // to show "Next" (advancing through a missing-tonight queue) or "Done".
  onSubmitted: (agentId: string) => void;
  hasNext?: boolean;
  onNext?: () => void;
}

type FormState = Record<keyof PulsePayload, string>;

const emptyForm: FormState = {
  sets: '', sits: '', sales: '', ots_sits: '', ots_sales: '',
  n1: '', refs_obtained: '', ref_sits: '', ref_sales: '',
  pos_sits: '', pos_sales: '', vet_sits: '', vet_sales: '',
  gross_alp: '',
};

function buildPayload(form: FormState): PulsePayload {
  const out: any = {};
  for (const f of PULSE_FIELDS) {
    const raw = parseFloat(form[f.key] || '0') || 0;
    out[f.key] = f.type === 'money' ? raw : Math.floor(raw);
  }
  return out as PulsePayload;
}

export function QuickEntryForm({ target, onClose, onSubmitted, hasNext, onNext }: Props) {
  const [form, setForm] = useState<FormState>(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [salesDay, setSalesDay] = useState<string>(currentSalesDay());
  // Persists across a failed submit so a retry reuses the same idempotency
  // key; reset only after the server confirms the write.
  const pendingEntryId = useRef<string | null>(null);

  if (!target) return null;

  const dayOptions = recentSalesDays(UPLINE_WINDOW_DAYS);

  const set = (key: keyof PulsePayload, val: string) => setForm((f) => ({ ...f, [key]: val }));

  const submit = async () => {
    setSubmitting(true);
    try {
      if (!pendingEntryId.current) pendingEntryId.current = makeClientEntryId();
      const payload = { ...buildPayload(form), target_agent_id: target.agent_id, sales_day: salesDay, client_entry_id: pendingEntryId.current };
      await api('/api/pulse', { method: 'POST', body: JSON.stringify(payload) });
      pendingEntryId.current = null;
      setForm(emptyForm);
      onSubmitted(target.agent_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit';
      Alert.alert('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <KeyboardAvoidingView style={styles.sheet} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.kicker}>ENTERING FOR</Text>
              <Text style={styles.name} numberOfLines={1}>{target.name}</Text>
            </View>
            <TouchableOpacity onPress={onClose} testID="quick-entry-close" hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Ionicons name="close" size={24} color={COLORS.textDim} />
            </TouchableOpacity>
          </View>

          <View style={styles.dayRowWrap}>
            <Text style={styles.dayKicker}>SALES DAY</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.dayRow}>
              {dayOptions.map((d, i) => (
                <TouchableOpacity
                  key={d}
                  style={[styles.dayChip, salesDay === d && styles.dayChipActive]}
                  onPress={() => setSalesDay(d)}
                  testID={`quick-entry-day-${d}`}
                >
                  <Text style={[styles.dayChipTxt, salesDay === d && styles.dayChipTxtActive]}>{dayChipLabel(d, i)}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>

          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {PULSE_FIELDS.map((f) => (
              <View key={f.key} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>{f.label}</Text>
                  <Text style={styles.hint}>{f.hint}</Text>
                </View>
                <View style={styles.inputWrap}>
                  {f.type === 'money' ? <Text style={styles.dollar}>$</Text> : null}
                  <TextInput
                    style={styles.input}
                    keyboardType="numeric"
                    placeholder="0"
                    placeholderTextColor={COLORS.textMuted}
                    value={form[f.key]}
                    onChangeText={(v) => set(f.key, v)}
                    testID={`quick-entry-${f.key}`}
                  />
                </View>
              </View>
            ))}
          </ScrollView>

          <View style={styles.footer}>
            <TouchableOpacity
              style={[styles.submitBtn, submitting && { opacity: 0.6 }]}
              onPress={submit}
              disabled={submitting}
              testID="quick-entry-submit"
            >
              {submitting ? <ActivityIndicator color="#000" /> : <Text style={styles.submitTxt}>SUBMIT FOR {target.name.split(' ')[0].toUpperCase()}</Text>}
            </TouchableOpacity>
            {hasNext ? (
              <TouchableOpacity style={styles.nextBtn} onPress={onNext} testID="quick-entry-skip-next">
                <Text style={styles.nextTxt}>Skip to next missing person</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: COLORS.bg, borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: '90%', borderWidth: 1, borderColor: COLORS.border },
  head: { flexDirection: 'row', alignItems: 'center', padding: 16, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  kicker: { color: COLORS.primary, fontSize: 10, fontWeight: '900', letterSpacing: 1.6 },
  name: { color: '#fff', fontSize: 18, fontWeight: '900', marginTop: 2 },
  dayRowWrap: { paddingTop: 12, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: COLORS.border, paddingBottom: 12 },
  dayKicker: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.6, marginBottom: 8 },
  dayRow: { gap: 8 },
  dayChip: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  dayChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dayChipTxt: { color: COLORS.textDim, fontSize: 12, fontWeight: '800' },
  dayChipTxtActive: { color: '#000' },
  scroll: { padding: 16, paddingBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  label: { color: '#fff', fontSize: 13, fontWeight: '700' },
  hint: { color: COLORS.textDim, fontSize: 10, marginTop: 1 },
  inputWrap: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, paddingHorizontal: 8, minWidth: 84 },
  dollar: { color: COLORS.textDim, fontSize: 14, fontWeight: '700', marginRight: 2 },
  input: { color: '#fff', fontSize: 15, fontWeight: '800', paddingVertical: 8, minWidth: 60, textAlign: 'right' },
  footer: { padding: 16, gap: 10, borderTopWidth: 1, borderTopColor: COLORS.border },
  submitBtn: { backgroundColor: COLORS.primary, borderRadius: 8, paddingVertical: 14, alignItems: 'center' },
  submitTxt: { color: '#000', fontWeight: '900', fontSize: 14, letterSpacing: 0.5 },
  nextBtn: { alignItems: 'center', paddingVertical: 4 },
  nextTxt: { color: COLORS.textDim, fontSize: 12, fontWeight: '700', textDecorationLine: 'underline' },
});
