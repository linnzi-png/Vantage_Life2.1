// Licensed states picker (owner, 2026-09-24, from MJ's "dropdown" / "exact
// states"): a multi-select of the states a person is licensed to sell in.
// The same sheet serves both write paths — the agent's own profile on the
// More tab (POST /api/me/licensed-states) and a downline member's contact
// card on the Team tab (POST /api/team/set-licensed-states) — so the caller
// hands in the request and this sheet only collects the codes. The server
// validates, uppercases, deduplicates and sorts; the grid here is convenience,
// never the enforcement.
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, ActivityIndicator, Switch,
} from 'react-native';
import { COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';
import { LICENSED_STATE_CODES } from '../lib/licensedStates';

interface Props {
  /** Null keeps the sheet closed. */
  target: { name: string; licensed_states?: string[]; pending_states?: string[]; pending_reminder?: boolean } | null;
  /** Performs the write; the sheet shows any thrown error and stays open.
   *  `pending` are states applied for and not yet issued; `remind` is the
   *  weekly follow-up switch for them (Linnzi, 2026-09-29). */
  onSave: (codes: string[], pending: string[], remind: boolean) => Promise<void>;
  onClose: () => void;
}

export function LicensedStatesSheet({ target, onSave, onClose }: Props) {
  const [picked, setPicked] = useState<string[]>([]);
  const [pendingPicked, setPendingPicked] = useState<string[]>([]);
  const [mode, setMode] = useState<'active' | 'pending'>('active');
  const [remind, setRemind] = useState(true);
  const [busy, setBusy] = useState(false);

  // Start from what is on file each time the sheet opens for someone.
  useEffect(() => {
    // Seeding local edit state from the prop, not deriving it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPicked(target?.licensed_states ? [...target.licensed_states] : []);
    setPendingPicked(target?.pending_states ? [...target.pending_states] : []);
    setMode('active');
    setRemind(target?.pending_reminder !== false);
  }, [target]);

  if (!target) return null;

  // A state is never both licensed and pending: licensing a pending state moves
  // it, and a licensed state cannot be marked pending.
  const toggle = (code: string) => {
    if (mode === 'active') {
      setPicked((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]));
      setPendingPicked((cur) => cur.filter((c) => c !== code));
    } else if (!picked.includes(code)) {
      setPendingPicked((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]));
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      await onSave([...picked].sort(), [...pendingPicked].sort(), remind);
      onClose();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Licensed states could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const summary = picked.length ? [...picked].sort().join(', ') : 'No states selected';
  const pendingSummary = pendingPicked.length ? [...pendingPicked].sort().join(', ') : 'None';

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>LICENSED STATES</Text>
          <Text style={styles.sub}>{target.name} · tap every state they are licensed to sell in</Text>
          <Text style={styles.summary} testID="licensed-states-summary">{summary}</Text>
          <Text style={styles.pendingSummary} testID="licensed-states-pending-summary">Pending: {pendingSummary}</Text>

          <View style={styles.modeRow}>
            {(['active', 'pending'] as const).map((m) => (
              <TouchableOpacity
                key={m}
                style={[styles.modeBtn, mode === m && styles.modeBtnOn]}
                onPress={() => setMode(m)}
                accessibilityRole="button"
                accessibilityState={{ selected: mode === m }}
                testID={`licensed-mode-${m}`}
              >
                <Text style={[styles.modeTxt, mode === m && styles.modeTxtOn]}>{m === 'active' ? 'LICENSED' : 'PENDING'}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <ScrollView style={{ maxHeight: 360 }} contentContainerStyle={styles.grid}>
            {LICENSED_STATE_CODES.map((code) => {
              const on = picked.includes(code);
              const pend = pendingPicked.includes(code);
              const locked = mode === 'pending' && on;
              return (
                <TouchableOpacity
                  key={code}
                  style={[styles.chip, on && styles.chipOn, pend && styles.chipPending, locked && { opacity: 0.35 }]}
                  onPress={() => toggle(code)}
                  disabled={busy || locked}
                  testID={`licensed-state-${code}`}
                >
                  <Text style={[styles.chipTxt, on && styles.chipTxtOn, pend && styles.chipPendingTxt]}>{code}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>

          {mode === 'pending' ? (
            <View style={styles.remindRow}>
              <Text style={styles.remindTxt}>Remind me weekly to follow up</Text>
              <Switch
                value={remind}
                onValueChange={setRemind}
                trackColor={{ true: COLORS.primary }}
                accessibilityLabel="Remind me weekly to follow up on pending licenses"
                testID="licensed-states-remind"
              />
            </View>
          ) : null}

          <Text style={styles.note}>
            Licensed states are the ones they can write in. Pending states are applied for and not issued yet. This does not change the resident state on the roster.
          </Text>

          <View style={styles.actions}>
            <TouchableOpacity style={styles.cancel} onPress={onClose} disabled={busy}>
              <Text style={styles.cancelTxt}>CANCEL</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.save, busy && { opacity: 0.6 }]} onPress={save} disabled={busy} testID="licensed-states-save">
              {busy ? <ActivityIndicator color="#000" /> : <Text style={styles.saveTxt}>SAVE</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: {
    position: 'absolute', top: 0, right: 0, bottom: 0, left: 0,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  sheet: {
    backgroundColor: '#111', borderTopLeftRadius: 18, borderTopRightRadius: 18,
    padding: 18, paddingBottom: 28, borderTopWidth: 1, borderColor: COLORS.border,
  },
  handle: {
    width: 38, height: 4, borderRadius: 2, backgroundColor: COLORS.border,
    alignSelf: 'center', marginBottom: 12,
  },
  title: { color: COLORS.primary, fontWeight: '900', fontSize: 12, letterSpacing: 1.6 },
  sub: { color: COLORS.textDim, fontSize: 13, marginTop: 4 },
  summary: { color: '#fff', fontWeight: '800', fontSize: 13, marginTop: 8, marginBottom: 10 },
  pendingSummary: { color: COLORS.gold, fontWeight: '700', fontSize: 12, marginBottom: 10 },
  modeRow: { flexDirection: 'row', gap: 8, marginBottom: 10 },
  modeBtn: {
    flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface2,
  },
  modeBtnOn: { borderColor: COLORS.primary, backgroundColor: COLORS.surface },
  modeTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  modeTxtOn: { color: COLORS.primary },
  chipPending: { borderColor: COLORS.gold, borderStyle: 'dashed' },
  chipPendingTxt: { color: COLORS.gold },
  remindRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, minHeight: 44 },
  remindTxt: { color: '#fff', fontSize: 13, fontWeight: '700', flex: 1, paddingRight: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingBottom: 4 },
  chip: {
    width: 52, paddingVertical: 9, alignItems: 'center', borderRadius: 8,
    backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border,
  },
  chipOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 0.6 },
  chipTxtOn: { color: '#000' },
  note: { color: COLORS.textMuted, fontSize: 11, fontStyle: 'italic', marginTop: 10 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 14 },
  cancel: { flex: 1, alignItems: 'center', paddingVertical: 12 },
  cancelTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1 },
  save: {
    flex: 1, alignItems: 'center', paddingVertical: 12, borderRadius: 10,
    backgroundColor: COLORS.primary,
  },
  saveTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 1 },
});
