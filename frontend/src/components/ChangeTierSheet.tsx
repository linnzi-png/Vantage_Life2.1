// Change Tier — the promotion an upline actually performs, from the agent card
// on the Team tab, instead of routing every one through an admin.
//
// Owner's decision tree (2026-09-14): an upline may set the tier of someone in
// their own downline, up or down, but only to a tier strictly below their own —
// an MGA can make someone a GA, never another MGA. is_admin and finance_admin
// get the same control agency-wide, capped the same way: level_4 and the
// Financial Admin role stay in the Admin Panel. /api/team/set-tier re-checks all
// of it; the options below are convenience, never the enforcement.
//
// The producer title travels with the tier. A promotion that leaves the old
// title behind is how someone ends up carrying GA access while the app still
// shows them as "Agent" until an admin notices, so each option here is a
// tier + title pair, exactly like AddTeamMemberSheet's.
import React, { useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, levelNum, roleTitle, Role } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

export interface TierTarget {
  agent_id: string;
  name: string;
  role?: string;
  io_role?: string;
}

interface Props {
  target: TierTarget | null;
  myRole?: Role | null;
  /** True for is_admin and finance_admin, who act agency-wide at the same cap. */
  agencyWide?: boolean;
  onClose: () => void;
  onChanged: () => void;
}

// Tier + title pairs, ordered lowest first. Wider than AddTeamMemberSheet's
// list on purpose: that sheet onboards new people (Agent and SA/GA only, since
// placing an MGA is an admin task), while a promotion has to be able to reach
// MGA for an RGA doing it.
const TIER_OPTIONS: { role: Role; io_role: string; label: string; blurb: string }[] = [
  { role: 'level_1', io_role: 'inTraining', label: 'TRAINEE',
    blurb: 'Enters their own numbers. In training.' },
  { role: 'level_1', io_role: 'Agent', label: 'AGENT',
    blurb: 'Enters their own numbers; reads their office.' },
  { role: 'level_sa', io_role: 'SA', label: 'SA',
    blurb: 'Runs a team: reads their downline, enters on their behalf, promotes to Agent.' },
  { role: 'level_2', io_role: 'GA', label: 'GA',
    blurb: 'Runs SAs and agents: everything an SA does, plus promoting to SA.' },
  { role: 'level_3', io_role: 'MGA', label: 'MGA',
    blurb: 'Reads every GA rollup beneath them.' },
];

export function ChangeTierSheet({ target, myRole, agencyWide, onClose, onChanged }: Props) {
  const [busy, setBusy] = useState(false);

  // An admin or finance_admin acts as though standing at level_4 — everything
  // below it, never level_4 itself.
  const ceiling = agencyWide ? 4 : levelNum(myRole);
  const options = useMemo(
    () => TIER_OPTIONS.filter((o) => levelNum(o.role) < ceiling),
    [ceiling],
  );

  if (!target) return null;

  const currentLevel = levelNum(target.role as Role | undefined);
  const currentLabel = roleTitle(target.io_role, target.role);
  const first = target.name.split(' ')[0];

  const apply = async (opt: typeof TIER_OPTIONS[number]) => {
    const raising = levelNum(opt.role) > currentLevel;
    const ok = await confirmAsync({
      title: raising ? 'Promote this teammate?' : 'Change their access tier?',
      message:
        `${target.name}\n\n${currentLabel} → ${opt.label}\n\n` +
        (raising
          ? "This widens what they can see: they will read their new downline's production, and can enter numbers on their behalf."
          : 'This narrows what they can see. Anything already recorded stays as it is.') +
        '\n\nIt takes effect immediately and is recorded in the audit log with your name.',
      confirmText: raising ? 'Promote' : 'Change',
      destructive: !raising,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api('/api/team/set-tier', {
        method: 'POST',
        body: JSON.stringify({ agent_id: target.agent_id, role: opt.role, io_role: opt.io_role }),
      });
      notify('Done', `${first} is now ${opt.label}.`);
      onChanged();
      onClose();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Tier change failed');
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
          <Text style={styles.title}>ACCESS TIER</Text>
          <Text style={styles.sub}>
            {target.name} · currently {currentLabel}
          </Text>

          {options.length === 0 ? (
            <Text style={styles.empty}>
              There is no tier below your own to assign. Ask an admin.
            </Text>
          ) : (
            <ScrollView style={{ maxHeight: 380 }}>
              {options.map((o) => {
                const isCurrent = o.role === target.role && o.io_role === (target.io_role || '');
                return (
                  <TouchableOpacity
                    key={`${o.role}-${o.io_role}`}
                    style={[styles.opt, isCurrent && styles.optCurrent]}
                    disabled={busy || isCurrent}
                    onPress={() => apply(o)}
                    testID={`tier-option-${o.io_role}`}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.optLabel}>
                        {o.label}{isCurrent ? ' · CURRENT' : ''}
                      </Text>
                      <Text style={styles.optBlurb}>{o.blurb}</Text>
                    </View>
                    {isCurrent ? (
                      <Ionicons name="checkmark" size={16} color={COLORS.gold} />
                    ) : (
                      <Ionicons
                        name={levelNum(o.role) > currentLevel ? 'arrow-up' : 'arrow-down'}
                        size={14}
                        color={COLORS.textDim}
                      />
                    )}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          )}

          <Text style={styles.note}>
            Setting RGA, or the Financial Admin role, stays in the Admin Panel.
          </Text>

          {busy ? (
            <View style={styles.busy}>
              <ActivityIndicator color={COLORS.primary} />
            </View>
          ) : null}

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
  sub: { color: COLORS.textDim, fontSize: 13, marginTop: 4, marginBottom: 12 },
  empty: { color: COLORS.textMuted, fontSize: 13, fontStyle: 'italic', paddingVertical: 12 },
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
