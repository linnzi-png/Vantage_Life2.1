// Platinum Rule nomination sheet: pick any agent, say what they did, submit.
// The Platinum Rule: do more for others than they would do for themselves.
import React, { useEffect, useMemo, useState } from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput,
  FlatList, Platform, KeyboardAvoidingView, } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth } from '../lib/auth';
import { notify } from '../lib/dialog';

interface DirectoryAgent { agent_id: string; name: string; office: string; }

interface Props {
  visible: boolean;
  onClose: () => void;
  onSubmitted?: () => void;
  preselected?: DirectoryAgent | null;
}

export function NominateSheet({ visible, onClose, onSubmitted, preselected }: Props) {
  const { user } = useAuth();
  const [agents, setAgents] = useState<DirectoryAgent[]>([]);
  const [query, setQuery] = useState('');
  const [nominee, setNominee] = useState<DirectoryAgent | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setNominee(preselected ?? null);
    setQuery('');
    setReason('');
    api<{ agents: DirectoryAgent[] }>('/api/agents/directory')
      .then((r) => setAgents(r.agents.filter((a) => a.agent_id !== user?.agent_id)))
      .catch(() => setAgents([]));
  }, [visible, preselected, user?.agent_id]);

  const matches = useMemo(() => {
    if (!query.trim()) return agents.slice(0, 30);
    const q = query.trim().toLowerCase();
    return agents.filter((a) => a.name.toLowerCase().includes(q) || a.office.toLowerCase().includes(q)).slice(0, 30);
  }, [agents, query]);

  const submit = async () => {
    if (!nominee || reason.trim().length < 10 || busy) return;
    setBusy(true);
    try {
      await api('/api/nominations', {
        method: 'POST',
        body: JSON.stringify({ nominee_agent_id: nominee.agent_id, reason: reason.trim() }),
      });
      onClose();
      onSubmitted?.();
      notify('Nomination sent', `${nominee.name}'s upline will see your Platinum Rule nomination.`);
    } catch (e: any) {
      notify('Could not submit', String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = !!nominee && reason.trim().length >= 10 && !busy;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.kicker}>PLATINUM RULE NOMINATION</Text>
          <Text style={styles.subtitle}>Do more for others than they would do for themselves.</Text>

          {nominee ? (
            <View style={styles.nomineeRow} testID="nominate-selected">
              <View style={{ flex: 1 }}>
                <Text style={styles.nomineeName}>{nominee.name}</Text>
                <Text style={styles.nomineeMeta}>{nominee.office}</Text>
              </View>
              <TouchableOpacity onPress={() => setNominee(null)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <Ionicons name="close-circle" size={20} color={COLORS.textDim} />
              </TouchableOpacity>
            </View>
          ) : (
            <>
              <TextInput
                style={styles.input}
                placeholder="Search agents by name or office…"
                placeholderTextColor={COLORS.textMuted}
                value={query}
                onChangeText={setQuery}
                testID="nominate-search"
              />
              <FlatList
                style={styles.list}
                data={matches}
                keyExtractor={(a) => a.agent_id}
                keyboardShouldPersistTaps="handled"
                renderItem={({ item }) => (
                  <TouchableOpacity style={styles.listRow} onPress={() => setNominee(item)} testID={`nominate-pick-${item.agent_id}`}>
                    <Text style={styles.listName}>{item.name}</Text>
                    <Text style={styles.listMeta}>{item.office}</Text>
                  </TouchableOpacity>
                )}
                ListEmptyComponent={<Text style={styles.emptyTxt}>No matching agents.</Text>}
              />
            </>
          )}

          {nominee ? (
            <TextInput
              style={[styles.input, styles.reason]}
              placeholder="What did they do for someone else? (min 10 characters)"
              placeholderTextColor={COLORS.textMuted}
              value={reason}
              onChangeText={setReason}
              multiline
              maxLength={500}
              testID="nominate-reason"
            />
          ) : null}

          <TouchableOpacity
            style={[styles.submitBtn, !canSubmit && styles.submitDisabled]}
            onPress={submit}
            disabled={!canSubmit}
            testID="nominate-submit"
          >
            <Ionicons name="medal" size={16} color={canSubmit ? '#000' : COLORS.textMuted} />
            <Text style={[styles.submitTxt, !canSubmit && { color: COLORS.textMuted }]}>
              {busy ? 'SUBMITTING…' : 'SUBMIT NOMINATION'}
            </Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    backgroundColor: '#1A1A1A', borderTopLeftRadius: 16, borderTopRightRadius: 16,
    padding: 20, paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    borderTopWidth: 2, borderTopColor: '#E5E4E2', maxHeight: '85%',
  },
  handle: { width: 36, height: 4, backgroundColor: COLORS.border, borderRadius: 2, alignSelf: 'center', marginBottom: 16 },
  kicker: { color: '#E5E4E2', fontSize: 12, fontWeight: '900', letterSpacing: 2 },
  subtitle: { color: COLORS.textDim, fontSize: 12, marginTop: 4, marginBottom: 14, fontStyle: 'italic' },
  input: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 8,
    color: '#fff', padding: 12, fontSize: 14,
  },
  reason: { marginTop: 10, minHeight: 84, textAlignVertical: 'top' },
  list: { maxHeight: 240, marginTop: 8 },
  listRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingVertical: 10, paddingHorizontal: 4, borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  listName: { color: '#fff', fontWeight: '700', fontSize: 14 },
  listMeta: { color: COLORS.textDim, fontSize: 12 },
  emptyTxt: { color: COLORS.textMuted, textAlign: 'center', paddingVertical: 16, fontSize: 12 },
  nomineeRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface,
    borderWidth: 1, borderColor: '#E5E4E2', borderRadius: 8, padding: 12,
  },
  nomineeName: { color: '#fff', fontWeight: '800', fontSize: 15 },
  nomineeMeta: { color: COLORS.textDim, fontSize: 12, marginTop: 2 },
  submitBtn: {
    flexDirection: 'row', gap: 8, marginTop: 14, paddingVertical: 14,
    alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: '#E5E4E2',
  },
  submitDisabled: { backgroundColor: COLORS.surface2 },
  submitTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 1.5 },
});
