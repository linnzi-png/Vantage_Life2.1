// Full roster-sheet sync — Admin screen only.
//
// The office's app sheet (committed under backend/data/roster/) is the source
// of truth for tier, display title, tenure, and the upline structure. This
// tool previews every difference and applies it in one step. Access tiers are
// only ever RAISED to match a person's sheet position — would-be demotions
// (e.g. a deliberate level_4 the sheet shows lower) are listed for the admin
// to decide by hand, and Partner / Senior Partner titles are never touched.
import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

interface SyncChange {
  agent_id: string;
  name: string;
  current_role: string;
  role?: string;
  io_role?: string;
  is_rookie?: boolean;
  email?: string;
  phone?: string;
  upline_id?: string;
  upline_name?: string;
}

interface SyncPlan {
  changes: SyncChange[];
  to_create: string[];
  demotions_review: { agent_id: string; name: string; app_role: string; sheet_position: string }[];
  not_on_sheet: { agent_id: string; name: string; office: string }[];
  sheet_size: number;
  profiles_total: number;
}

function tierShort(role: string): string {
  return role.replace('level_', 'L');
}

function describeChange(c: SyncChange): string {
  const bits: string[] = [];
  if (c.role) bits.push(`${tierShort(c.current_role)} → ${tierShort(c.role)}`);
  if (c.io_role) bits.push(`title ${c.io_role}`);
  if (c.is_rookie !== undefined) bits.push(c.is_rookie ? 'Rookie' : 'Veteran');
  if (c.upline_name) bits.push(`under ${c.upline_name}`);
  if (c.email) bits.push('email filled');
  if (c.phone) bits.push('phone filled');
  return bits.join(' · ');
}

export function RosterSheetSync({ onSynced }: { onSynced: () => void }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [plan, setPlan] = useState<SyncPlan | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoaded(false);
    try {
      setPlan(await api<SyncPlan>('/api/admin/roster-sync'));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load the sync preview');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => { await load(); if (cancelled) return; })();
    return () => { cancelled = true; };
  }, [open, load]);

  const apply = async () => {
    if (!plan) return;
    const n = plan.changes.length + plan.to_create.length;
    if (n === 0) return;
    const ok = await confirmAsync({
      title: 'Sync App to Roster Sheet',
      message:
        `Apply ${plan.changes.length} profile update${plan.changes.length === 1 ? '' : 's'}` +
        (plan.to_create.length > 0 ? ` and create ${plan.to_create.length} missing profile${plan.to_create.length === 1 ? '' : 's'}` : '') +
        '? Tier changes take effect on the person’s next screen load.',
      confirmText: `Sync ${n}`,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<{ applied: SyncChange[]; created: string[] }>(
        '/api/admin/roster-sync/fix', { method: 'POST' });
      notify(
        'Roster synced',
        `${r.applied.length} profile${r.applied.length === 1 ? '' : 's'} updated, ` +
        `${r.created.length} created — the app now matches the sheet.`,
      );
      await load();
      onSynced();
    } catch (e: unknown) {
      notify('Sync failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="sheet-sync-open">
        <Ionicons name="sync-outline" size={16} color={COLORS.primary} />
        <Text style={styles.openTxt}>SYNC ROSTER SHEET</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Roster Sheet Sync</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="sheet-sync-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Makes the app match the office&apos;s roster sheet: access tier (raises
        only), display title, veteran/rookie tenure, and who reports to whom.
        Demotions are never applied automatically — they&apos;re listed below for
        you to decide.
      </Text>

      {!loaded || !plan ? (
        <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>
      ) : (
        <>
          {plan.changes.length === 0 && plan.to_create.length === 0 ? (
            <Text style={styles.clear}>The app already matches the sheet.</Text>
          ) : (
            <>
              <Text style={styles.count}>
                {plan.changes.length} UPDATE{plan.changes.length === 1 ? '' : 'S'}
                {plan.to_create.length > 0 ? ` · ${plan.to_create.length} TO CREATE` : ''}
              </Text>
              {plan.changes.map((c) => (
                <View key={c.agent_id} style={styles.row}>
                  <Text style={styles.name}>{c.name}</Text>
                  <Text style={styles.meta}>{describeChange(c)}</Text>
                </View>
              ))}
              {plan.to_create.map((name) => (
                <View key={name} style={styles.row}>
                  <Text style={styles.name}>{name}</Text>
                  <Text style={styles.meta}>on the sheet but not in the app — will be created</Text>
                </View>
              ))}
              <TouchableOpacity
                style={[styles.applyBtn, busy && { opacity: 0.5 }]}
                onPress={apply}
                disabled={busy}
                testID="sheet-sync-apply"
              >
                {busy ? <ActivityIndicator color="#000" /> : <Text style={styles.applyTxt}>Apply Sync</Text>}
              </TouchableOpacity>
            </>
          )}

          {plan.demotions_review.length > 0 ? (
            <>
              <Text style={styles.reviewLab}>NEEDS YOUR DECISION — NOT APPLIED</Text>
              {plan.demotions_review.map((d) => (
                <View key={d.agent_id} style={styles.row}>
                  <Text style={styles.name}>{d.name}</Text>
                  <Text style={styles.meta}>
                    app has {tierShort(d.app_role)}, sheet shows {d.sheet_position} — change the tier
                    manually below if the sheet is right.
                  </Text>
                </View>
              ))}
            </>
          ) : null}

          {plan.not_on_sheet.length > 0 ? (
            <Text style={styles.note}>
              {plan.not_on_sheet.length} people in the app aren&apos;t on the sheet at
              all (likely former agents) — they are left untouched.
            </Text>
          ) : null}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  openBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.primary, padding: 12, borderRadius: 6, marginTop: 10 },
  openTxt: { color: COLORS.primary, fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: '#fff', fontWeight: '900', fontSize: 15 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  loading: { paddingVertical: 20, alignItems: 'center' },
  clear: { color: COLORS.primary, fontSize: 12, marginTop: 10, fontWeight: '700' },
  count: { color: COLORS.primary, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12 },
  row: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, marginTop: 6, padding: 8 },
  name: { color: '#fff', fontWeight: '800', fontSize: 13 },
  meta: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  applyBtn: { backgroundColor: COLORS.primary, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 10 },
  applyTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  reviewLab: { color: COLORS.orange, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 14 },
  note: { color: COLORS.textDim, fontSize: 11, marginTop: 10, fontStyle: 'italic', lineHeight: 16 },
});
