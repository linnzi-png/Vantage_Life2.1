// Pick a new upline for a team member. Candidates are supplied by the caller —
// scoped to the viewer's downline at or above the member's tier, or the whole
// roster for an admin — and the backend re-checks every rule, so this sheet
// is purely a picker plus one choice: whether the member's own downline goes
// with them (owner, 2026-09-22). Office follows the upline: picking someone
// in another office moves the member — and, with the toggle on, their whole
// downline — into that office. Only an admin may cross an office line; the
// sheet says so on the row rather than letting the server refuse it.
import React, { useMemo, useState } from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput, Platform, ScrollView, Switch,
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
  /** Whether the viewer may move someone into another office (admin only). */
  canCrossOffice?: boolean;
  /** How many people report to the target, when the caller knows; only
   *  changes the wording of the confirmation. */
  downlineCount?: number;
  onClose: () => void;
  onMoved: () => void;
}

export function MoveMemberSheet({ target, candidates, canCrossOffice = false, downlineCount, onClose, onMoved }: Props) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [moveDownline, setMoveDownline] = useState(true);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((c) => `${c.name} ${c.office || ''}`.toLowerCase().includes(q));
  }, [candidates, query]);

  if (!target) return null;

  const officeOf = (c: MoveCandidate) => c.office || 'Unassigned';
  const crosses = (c: MoveCandidate) => officeOf(c) !== officeOf(target);

  const pick = async (c: MoveCandidate) => {
    const parts = [`Move ${target.name} under ${c.name}?`];
    if (crosses(c)) parts.push(`They move from ${officeOf(target)} to ${officeOf(c)} and count toward that office from now on.`);
    const who = downlineCount ? `their ${downlineCount} ${downlineCount === 1 ? 'report' : 'reports'}` : 'their own downline';
    parts.push(moveDownline
      ? `${who[0].toUpperCase()}${who.slice(1)} ${downlineCount === 1 ? 'goes' : 'go'} with them${crosses(c) ? ', office and all' : ''}.`
      : `${who[0].toUpperCase()}${who.slice(1)} ${downlineCount === 1 ? 'stays' : 'stay'} where they are, under ${target.name}'s current upline.`);
    const ok = await confirmAsync({
      title: crosses(c) ? 'Move to Another Office' : 'Move Team Member',
      message: parts.join(' '),
      confirmText: 'Move',
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api('/api/team/reassign', {
        method: 'POST',
        body: JSON.stringify({
          agent_id: target.agent_id, new_upline_agent_id: c.agent_id, move_downline: moveDownline,
        }),
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
          <Text style={styles.sub}>
            {canCrossOffice
              ? 'Pick their new upline. Their office follows the upline.'
              : 'Pick their new upline from your team.'}
          </Text>
          <View style={styles.toggleRow} testID="move-member-downline-toggle">
            <View style={{ flex: 1 }}>
              <Text style={styles.toggleLab}>Move their downline with them</Text>
              <Text style={styles.toggleSub}>
                {moveDownline
                  ? 'Everyone who reports to them comes along.'
                  : `Their reports stay behind, under ${target.name.split(' ')[0]}'s current upline.`}
              </Text>
            </View>
            <Switch
              value={moveDownline}
              onValueChange={setMoveDownline}
              disabled={busy}
              trackColor={{ true: COLORS.primary, false: COLORS.surface2 }}
            />
          </View>
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
            ) : shown.map((c) => {
              const otherOffice = crosses(c);
              const blocked = otherOffice && !canCrossOffice;
              return (
                <TouchableOpacity
                  key={c.agent_id}
                  style={[styles.row, blocked && styles.rowBlocked]}
                  onPress={() => pick(c)}
                  disabled={busy || blocked}
                  testID={`move-member-pick-${c.agent_id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>{c.name}</Text>
                    <Text style={styles.rowMeta}>
                      {roleTitle(c.io_role, c.role)}{c.office ? ` · ${c.office}` : ''}
                    </Text>
                    {otherOffice ? (
                      <Text style={[styles.rowOffice, blocked && styles.rowOfficeBlocked]}>
                        {blocked ? 'ANOTHER OFFICE · ADMIN ONLY' : `MOVES THEM TO ${officeOf(c).toUpperCase()}`}
                      </Text>
                    ) : null}
                  </View>
                  <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
                </TouchableOpacity>
              );
            })}
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
  rowBlocked: { opacity: 0.45 },
  rowName: { color: '#fff', fontWeight: '800', fontSize: 14 },
  rowMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  rowOffice: { color: COLORS.gold, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 4 },
  rowOfficeBlocked: { color: COLORS.textMuted },
  toggleRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.primary,
    borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 10,
  },
  toggleLab: { color: '#fff', fontWeight: '800', fontSize: 13 },
  toggleSub: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  emptyTxt: { color: COLORS.textDim, textAlign: 'center', paddingVertical: 20 },
  closeBtn: { marginTop: 8, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: COLORS.border, borderRadius: 8 },
  closeTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1.5 },
});
