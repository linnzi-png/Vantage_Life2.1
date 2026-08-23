// Pick a new upline for a downline member (GA/MGA/RGA; admins use the Admin
// Panel's set-upline tools instead). Candidates are supplied by the caller —
// already scoped to the viewer's downline at or above the member's tier — and
// the backend re-checks every rule, so this sheet is purely a picker.
import React, { useMemo, useState } from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput, Platform, ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, roleTitle } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

export interface MoveCandidate {
  agent_id: string;
  name: string;
  role: string;
  io_role?: string;
  office?: string;
}

interface Props {
  target: MoveCandidate | null;
  candidates: MoveCandidate[];
  onClose: () => void;
  onMoved: () => void;
}

export function MoveMemberSheet({ target, candidates, onClose, onMoved }: Props) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((c) => `${c.name} ${c.office || ''}`.toLowerCase().includes(q));
  }, [candidates, query]);

  if (!target) return null;

  const pick = async (c: MoveCandidate) => {
    const ok = await confirmAsync({
      title: 'Move Team Member',
      message: `Move ${target.name} under ${c.name}? Their own downline moves with them.`,
      confirmText: 'Move',
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api('/api/team/reassign', {
        method: 'POST',
        body: JSON.stringify({ agent_id: target.agent_id, new_upline_agent_id: c.agent_id }),
      });
      onClose();
      onMoved();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Move failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>MOVE {target.name.toUpperCase()}</Text>
          <Text style={styles.sub}>Pick their new upline from your team.</Text>
          <View style={styles.searchBox}>
            <Ionicons name="search" size={16} color={COLORS.textDim} />
            <TextInput
              style={styles.searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder="Search name or office"
              placeholderTextColor={COLORS.textMuted}
              autoCapitalize="none"
              testID="move-member-search"
            />
          </View>
          <ScrollView style={{ maxHeight: 320 }} keyboardShouldPersistTaps="handled">
            {shown.length === 0 ? (
              <Text style={styles.emptyTxt}>No eligible uplines match.</Text>
            ) : shown.map((c) => (
              <TouchableOpacity
                key={c.agent_id}
                style={styles.row}
                onPress={() => pick(c)}
                disabled={busy}
                testID={`move-member-pick-${c.agent_id}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>{c.name}</Text>
                  <Text style={styles.rowMeta}>
                    {roleTitle(c.io_role, c.role) || c.role}{c.office ? ` · ${c.office}` : ''}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
              </TouchableOpacity>
            ))}
          </ScrollView>
          <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
            <Text style={styles.closeTxt}>CANCEL</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    maxHeight: '88%', backgroundColor: '#1A1A1A',
    borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20,
    paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    borderTopWidth: 2, borderTopColor: COLORS.secondary,
  },
  handle: { width: 36, height: 4, backgroundColor: COLORS.border, borderRadius: 2, alignSelf: 'center', marginBottom: 16 },
  title: { color: '#fff', fontWeight: '900', fontSize: 16, letterSpacing: 0.5 },
  sub: { color: COLORS.textDim, fontSize: 12, marginTop: 4, marginBottom: 12 },
  searchBox: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 6, paddingHorizontal: 12, marginBottom: 8,
  },
  searchInput: { flex: 1, color: '#fff', paddingVertical: 10, fontSize: 14 },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 6, padding: 12, marginBottom: 6,
  },
  rowName: { color: '#fff', fontWeight: '800', fontSize: 14 },
  rowMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  emptyTxt: { color: COLORS.textDim, textAlign: 'center', paddingVertical: 20 },
  closeBtn: { marginTop: 8, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: COLORS.border, borderRadius: 8 },
  closeTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1.5 },
});
