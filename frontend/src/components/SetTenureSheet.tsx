// Rookie / Veteran from the Team tab (owner, 2026-09-24): the SET TENURE
// badge on a row opens this, the same two-way choice the Admin Panel uses,
// posted to /api/team/set-tenure — a leader for their own downline, level_4,
// the admin grant and finance_admin agency-wide. The server re-checks all of
// it; the badge is only offered where the write would succeed.
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';

export interface TenureTarget {
  agent_id: string;
  name: string;
  is_rookie?: boolean | null;
}

interface Props {
  target: TenureTarget | null;
  onClose: () => void;
  onChanged: () => void;
}

export function SetTenureSheet({ target, onClose, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  if (!target) return null;
  const first = target.name.split(' ')[0];

  const apply = async (isRookie: boolean) => {
    setBusy(true);
    try {
      await api('/api/team/set-tenure', {
        method: 'POST',
        body: JSON.stringify({ agent_id: target.agent_id, is_rookie: isRookie }),
      });
      notify('Done', `${first} is marked ${isRookie ? 'Rookie' : 'Veteran'}.`);
      onChanged();
      onClose();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Tenure could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  // A render helper, not a nested component: a component defined inside
  // render would remount on every state change.
  const option = (rookie: boolean, label: string, blurb: string, testID: string) => {
    const current = target.is_rookie === rookie;
    return (
      <TouchableOpacity style={[styles.opt, current && styles.optCurrent]} disabled={busy || current} onPress={() => apply(rookie)} testID={testID}>
        <View style={{ flex: 1 }}>
          <Text style={styles.optLabel}>{label}{current ? ' · CURRENT' : ''}</Text>
          <Text style={styles.optBlurb}>{blurb}</Text>
        </View>
        <Ionicons name={current ? 'checkmark' : 'chevron-forward'} size={16} color={current ? COLORS.gold : COLORS.textDim} />
      </TouchableOpacity>
    );
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>TENURE</Text>
          <Text style={styles.sub}>{target.name} · {target.is_rookie == null ? 'not set' : target.is_rookie ? 'Rookie' : 'Veteran'}</Text>
          {option(true, 'ROOKIE', 'Coded within the last 12 months. Ranks on the Top 3 Rookies wall.', 'tenure-option-rookie')}
          {option(false, 'VETERAN', 'Past the one-year code anniversary. Ranks on the Top 3 Vets wall.', 'tenure-option-veteran')}
          <Text style={styles.note}>Recorded in the audit log with your name. It takes effect immediately.</Text>
          {busy ? <View style={styles.busy}><ActivityIndicator color={COLORS.primary} /></View> : null}
          <TouchableOpacity style={styles.cancel} onPress={onClose} disabled={busy}>
            <Text style={styles.cancelTxt}>CANCEL</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    backgroundColor: '#111', borderTopLeftRadius: 18, borderTopRightRadius: 18,
    padding: 18, paddingBottom: 28, borderTopWidth: 1, borderColor: COLORS.border,
  },
  handle: { width: 38, height: 4, borderRadius: 2, backgroundColor: COLORS.border, alignSelf: 'center', marginBottom: 12 },
  title: { color: COLORS.primary, fontWeight: '900', fontSize: 12, letterSpacing: 1.6 },
  sub: { color: COLORS.textDim, fontSize: 13, marginTop: 4, marginBottom: 12 },
  opt: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    backgroundColor: COLORS.surface2, borderRadius: 10, borderWidth: 1,
    borderColor: COLORS.border, padding: 12, marginBottom: 8,
  },
  optCurrent: { opacity: 0.55 },
  optLabel: { color: '#fff', fontWeight: '900', fontSize: 13, letterSpacing: 0.6 },
  optBlurb: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  note: { color: COLORS.textMuted, fontSize: 11, fontStyle: 'italic', marginTop: 4 },
  busy: { paddingVertical: 10, alignItems: 'center' },
  cancel: { marginTop: 14, alignItems: 'center', paddingVertical: 10 },
  cancelTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1 },
});
