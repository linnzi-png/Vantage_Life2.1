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
  View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, ActivityIndicator,
} from 'react-native';
import { COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';
import { LICENSED_STATE_CODES } from '../lib/licensedStates';

interface Props {
  /** Null keeps the sheet closed. */
  target: { name: string; licensed_states?: string[] } | null;
  /** Performs the write; the sheet shows any thrown error and stays open. */
  onSave: (codes: string[]) => Promise<void>;
  onClose: () => void;
}

export function LicensedStatesSheet({ target, onSave, onClose }: Props) {
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  // Start from what is on file each time the sheet opens for someone.
  useEffect(() => {
    // Seeding local edit state from the prop, not deriving it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPicked(target?.licensed_states ? [...target.licensed_states] : []);
  }, [target]);

  if (!target) return null;

  const toggle = (code: string) =>
    setPicked((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]));

  const save = async () => {
    setBusy(true);
    try {
      await onSave([...picked].sort());
      onClose();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Licensed states could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const summary = picked.length ? [...picked].sort().join(', ') : 'No states selected';

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>LICENSED STATES</Text>
          <Text style={styles.sub}>{target.name} · tap every state they are licensed to sell in</Text>
          <Text style={styles.summary} testID="licensed-states-summary">{summary}</Text>

          <ScrollView style={{ maxHeight: 360 }} contentContainerStyle={styles.grid}>
            {LICENSED_STATE_CODES.map((code) => {
              const on = picked.includes(code);
              return (
                <TouchableOpacity
                  key={code}
                  style={[styles.chip, on && styles.chipOn]}
                  onPress={() => toggle(code)}
                  disabled={busy}
                  testID={`licensed-state-${code}`}
                >
                  <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>{code}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>

          <Text style={styles.note}>
            This is the list of states they can write in. It does not change the resident state on the roster.
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
