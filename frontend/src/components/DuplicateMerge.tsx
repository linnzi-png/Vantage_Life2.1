// Duplicate-profile merge — Admin screen only.
//
// Each import path spelled names its own way ("QARADAGHI, SNOOR" vs
// "Snoor Qaradaghi"), so exact-name lookups minted a second profile for the
// same human. Their downline then splits across the twins: the person's login
// links (by email) to one profile and sees only that fragment of their team,
// while the fragment's own production hangs off the other twin and reads
// $0 / "No Pulse". This tool folds the twins back into one node.
import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

interface DupProfile {
  agent_id: string;
  name: string;
  email: string;
  office: string;
  role: string;
  io_role: string;
  upline_id: string | null;
  upline_name: string;
  downline_count: number;
  entries_count: number;
  logins_count: number;
  created_by_import: boolean;
}

interface DupGroup {
  reason: 'same_name' | 'same_email';
  suggested_keep_agent_id: string;
  profiles: DupProfile[];
}

interface MergeReport {
  children_repointed: number;
  entries_moved: number;
  entries_dropped_war_duplicates: number;
  logins_relinked: number;
}

export function DuplicateMerge({ onMerged }: { onMerged: () => void }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [groups, setGroups] = useState<DupGroup[]>([]);
  // Chosen keeper per group, keyed by group index.
  const [keepers, setKeepers] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoaded(false);
    try {
      const r = await api<{ groups: DupGroup[] }>('/api/admin/duplicates');
      setGroups(r.groups);
      const initial: Record<number, string> = {};
      r.groups.forEach((g, i) => { initial[i] = g.suggested_keep_agent_id; });
      setKeepers(initial);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load duplicate profiles');
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

  const merge = async (group: DupGroup, keepId: string) => {
    const keep = group.profiles.find((p) => p.agent_id === keepId);
    const others = group.profiles.filter((p) => p.agent_id !== keepId);
    if (!keep || others.length === 0) return;
    const ok = await confirmAsync({
      title: 'Merge Duplicate Profiles',
      message:
        `Fold ${others.map((o) => `"${o.name}"`).join(' and ')} into "${keep.name}"?\n\n` +
        'Their direct reports, production entries, and login move to the kept ' +
        'profile and the duplicate is deleted. This cannot be undone.',
      confirmText: 'Merge',
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      let children = 0; let entries = 0;
      for (const o of others) {
        const r = await api<MergeReport>('/api/admin/merge-agents', {
          method: 'POST',
          body: JSON.stringify({ keep_agent_id: keepId, remove_agent_id: o.agent_id }),
        });
        children += r.children_repointed;
        entries += r.entries_moved;
      }
      notify(
        'Profiles merged',
        `${keep.name} is one profile again — ${children} agent${children === 1 ? '' : 's'} ` +
        `re-linked, ${entries} production entr${entries === 1 ? 'y' : 'ies'} moved.`,
      );
      await load();
      onMerged();
    } catch (e: unknown) {
      notify('Merge failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="dups-open">
        <Ionicons name="copy-outline" size={16} color={COLORS.gold} />
        <Text style={styles.openTxt}>MERGE DUPLICATE PROFILES</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Duplicate Profiles</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="dups-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        The same person on the roster twice splits their team across the two
        profiles — their upline sees only part of the downline, and entries land
        on whichever twin each login is attached to. Pick the profile to keep
        (the one with the login is preselected) and merge.
      </Text>

      {!loaded ? (
        <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>
      ) : groups.length === 0 ? (
        <Text style={styles.clear}>No duplicate profiles found.</Text>
      ) : (
        groups.map((g, gi) => {
          const keepId = keepers[gi] ?? g.suggested_keep_agent_id;
          return (
            <View key={`${g.reason}-${g.profiles[0].agent_id}`} style={styles.group}>
              <Text style={styles.groupLab}>
                {g.reason === 'same_name' ? 'SAME NAME' : 'SAME EMAIL'}
              </Text>
              {g.profiles.map((p) => {
                const isKeep = p.agent_id === keepId;
                return (
                  <TouchableOpacity
                    key={p.agent_id}
                    style={[styles.row, isKeep && styles.rowKeep]}
                    onPress={() => setKeepers((prev) => ({ ...prev, [gi]: p.agent_id }))}
                    disabled={busy}
                    testID={`dup-${p.agent_id}`}
                  >
                    <Ionicons
                      name={isKeep ? 'radio-button-on' : 'radio-button-off'}
                      size={16}
                      color={isKeep ? COLORS.primary : COLORS.textDim}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name}>
                        {p.name} <Text style={styles.dim}>· {p.role.replace('level_', 'L')}</Text>
                      </Text>
                      <Text style={styles.meta}>
                        {p.email || 'no email'}
                        {p.logins_count > 0 ? ' · has login' : ''}
                        {p.created_by_import ? ' · from import' : ''}
                      </Text>
                      <Text style={styles.meta}>
                        {p.downline_count} direct report{p.downline_count === 1 ? '' : 's'} ·{' '}
                        {p.entries_count} entr{p.entries_count === 1 ? 'y' : 'ies'}
                        {p.upline_name ? ` · under ${p.upline_name}` : ' · no upline'}
                      </Text>
                    </View>
                    {isKeep ? <Text style={styles.keepTag}>KEEP</Text> : null}
                  </TouchableOpacity>
                );
              })}
              <TouchableOpacity
                style={[styles.mergeBtn, busy && { opacity: 0.5 }]}
                onPress={() => merge(g, keepId)}
                disabled={busy}
                testID={`dup-merge-${gi}`}
              >
                {busy
                  ? <ActivityIndicator color="#000" />
                  : <Text style={styles.mergeTxt}>Merge into kept profile</Text>}
              </TouchableOpacity>
            </View>
          );
        })
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  openBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.gold, padding: 12, borderRadius: 6, marginTop: 10 },
  openTxt: { color: COLORS.gold, fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: '#fff', fontWeight: '900', fontSize: 15 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  loading: { paddingVertical: 20, alignItems: 'center' },
  clear: { color: COLORS.primary, fontSize: 12, marginTop: 10, fontWeight: '700' },
  group: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, marginTop: 12, padding: 10 },
  groupLab: { color: COLORS.gold, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginBottom: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 8, borderRadius: 6, borderWidth: 1, borderColor: 'transparent' },
  rowKeep: { borderColor: COLORS.primary, backgroundColor: COLORS.surface2 },
  name: { color: '#fff', fontWeight: '800', fontSize: 13 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  meta: { color: COLORS.textMuted, fontSize: 11, marginTop: 1 },
  keepTag: { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  mergeBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 10, borderRadius: 6, marginTop: 8 },
  mergeTxt: { color: '#000', fontWeight: '900', fontSize: 12 },
});
