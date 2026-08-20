// Orphaned-agent repair — Admin screen only.
//
// visible_agent_ids() walks DOWN agent_profiles.upline_id, so an agent whose
// upline is null (or points at a deleted agent) can never be reached by a team
// rollup, and one broken link severs that agent's whole subtree. Every agent
// created by the WAR import starts this way. Nothing surfaced them before and
// no endpoint could fix them, so they were invisible with no way to notice.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, TextInput,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

interface Orphan {
  agent_id: string;
  name: string;
  office: string;
  role: string;
  upline_id: string | null;
  reason: 'no_upline' | 'dangling_upline';
  created_by_import: boolean;
}

export interface UplineChoice { agent_id: string; name: string; office?: string; role: string; }

interface HierarchyProposal { agent_id: string; name: string; upline_name: string; }
interface HierarchyMerge { keep_agent_id: string; keep_name: string; remove_agent_id: string; }
interface HierarchyPlan {
  proposals: HierarchyProposal[];
  merges: HierarchyMerge[];
  unresolved: { agent_id: string; reason: string }[];
}

export function OrphanRepair({ candidates, onRepaired }: {
  /** Roster the admin can pick an upline from — the same list the Add Person
   *  form searches, passed in so this component owns no roster state. */
  candidates: UplineChoice[];
  onRepaired: () => void;
}) {
  const [orphans, setOrphans] = useState<Orphan[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Orphan | null>(null);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<HierarchyPlan | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ orphans: Orphan[] }>('/api/admin/orphans');
      setOrphans(r.orphans);
      // The committed roster sheets know most uplines — ask what a bulk
      // re-link would cover so the one-at-a-time picker is the fallback,
      // not the plan.
      setPlan(await api<HierarchyPlan>('/api/admin/hierarchy-audit'));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load orphaned agents');
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

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return candidates.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 5);
  }, [candidates, query]);

  const autoLink = async () => {
    if (!plan) return;
    const nLink = plan.proposals.length;
    const nMerge = plan.merges.length;
    if (nLink + nMerge === 0) return;
    const parts = [];
    if (nMerge > 0) parts.push(`${nMerge} are duplicate profiles of someone already in the hierarchy and will be merged into them`);
    if (nLink > 0) parts.push(`${nLink} have an upline recorded on the roster sheets and will be linked to it`);
    const ok = await confirmAsync({
      title: 'Auto-Fix Unlinked Agents',
      message:
        `${parts.join('; ')}. Anyone the sheets don’t cover stays listed for ` +
        'manual assignment. Merges cannot be undone.',
      confirmText: `Fix ${nLink + nMerge}`,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<{ applied: HierarchyProposal[]; merged: HierarchyMerge[] }>(
        '/api/admin/hierarchy-audit/fix', { method: 'POST' });
      notify(
        'Agents repaired',
        `${r.applied.length} linked to their sheet upline, ${r.merged.length} duplicate ` +
        'profiles merged — all back in their upline’s team rollup.',
      );
      await load();
      onRepaired();
    } catch (e: unknown) {
      notify('Auto-fix failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const assign = async (upline: UplineChoice) => {
    if (!selected) return;
    setBusy(true);
    try {
      await api('/api/admin/set-upline', {
        method: 'POST',
        body: JSON.stringify({ agent_id: selected.agent_id, upline_agent_id: upline.agent_id }),
      });
      notify('Upline set', `${selected.name} now reports to ${upline.name}.`);
      setSelected(null); setQuery('');
      await load();
      onRepaired();
    } catch (e: unknown) {
      notify('Could not set upline', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="orphans-open">
        <Ionicons name="unlink-outline" size={16} color={COLORS.orange} />
        <Text style={styles.openTxt}>FIX UNLINKED AGENTS</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Unlinked Agents</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="orphans-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        These agents have no upline, so they don&apos;t appear in any GA or MGA team
        rollup — their production is invisible to everyone above them. Assign an
        upline to bring them back into the hierarchy.
      </Text>

      {!loaded ? (
        <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>
      ) : orphans.length === 0 ? (
        <Text style={styles.clear}>Every agent is linked. Nothing to fix.</Text>
      ) : (
        <>
          <Text style={styles.count}>{orphans.length} unlinked</Text>
          {plan && plan.proposals.length + plan.merges.length > 0 ? (
            <TouchableOpacity
              style={[styles.autoBtn, busy && { opacity: 0.5 }]}
              onPress={autoLink}
              disabled={busy}
              testID="orphans-autolink"
            >
              {busy
                ? <ActivityIndicator color="#000" />
                : (
                  <Text style={styles.autoTxt}>
                    AUTO-FIX {plan.proposals.length + plan.merges.length}
                    {plan.merges.length > 0 ? ` (LINK ${plan.proposals.length} · MERGE ${plan.merges.length})` : ' FROM ROSTER SHEET'}
                  </Text>
                )}
            </TouchableOpacity>
          ) : null}
          {plan && plan.unresolved.length > 0 ? (
            <Text style={styles.unresolvedNote}>
              {plan.unresolved.length} of these aren&apos;t on any roster sheet the app
              has, so their upline is unknown — assign them below, or get the
              office&apos;s full roster (the sheet with the SA/GA/MGA columns) added
              to the app&apos;s data to auto-link them.
            </Text>
          ) : null}
          {orphans.map((o) => {
            const sel = selected?.agent_id === o.agent_id;
            return (
              <View key={o.agent_id} style={[styles.row, sel && styles.rowOn]}>
                <TouchableOpacity
                  style={styles.rowHead}
                  onPress={() => { setSelected(sel ? null : o); setQuery(''); }}
                  testID={`orphan-${o.agent_id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{o.name}</Text>
                    <Text style={styles.meta}>
                      {o.office} · {o.reason === 'dangling_upline' ? 'upline no longer exists' : 'no upline'}
                      {o.created_by_import ? ' · from import' : ''}
                    </Text>
                  </View>
                  <Ionicons name={sel ? 'chevron-up' : 'chevron-down'} size={16} color={COLORS.textDim} />
                </TouchableOpacity>

                {sel ? (
                  <View style={styles.picker}>
                    <Text style={styles.lab}>ASSIGN UPLINE</Text>
                    <TextInput
                      style={styles.input}
                      value={query}
                      onChangeText={setQuery}
                      placeholder="Search by name"
                      placeholderTextColor={COLORS.textMuted}
                      testID="orphan-upline-search"
                    />
                    {matches.map((c) => (
                      <TouchableOpacity
                        key={c.agent_id}
                        style={styles.match}
                        onPress={() => assign(c)}
                        disabled={busy}
                        testID={`orphan-upline-${c.agent_id}`}
                      >
                        <Text style={styles.matchName}>{c.name}</Text>
                        <Text style={styles.matchMeta}>{c.office || ''}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                ) : null}
              </View>
            );
          })}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  openBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.orange, padding: 12, borderRadius: 6, marginTop: 10 },
  openTxt: { color: COLORS.orange, fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: '#fff', fontWeight: '900', fontSize: 15 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  loading: { paddingVertical: 20, alignItems: 'center' },
  clear: { color: COLORS.primary, fontSize: 12, marginTop: 10, fontWeight: '700' },
  count: { color: COLORS.orange, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12 },
  autoBtn: { backgroundColor: COLORS.primary, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 8 },
  autoTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 0.5 },
  unresolvedNote: { color: COLORS.textDim, fontSize: 11, marginTop: 8, lineHeight: 16, fontStyle: 'italic' },
  row: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, marginTop: 8, overflow: 'hidden' },
  rowOn: { borderColor: COLORS.orange },
  rowHead: { flexDirection: 'row', alignItems: 'center', padding: 10, gap: 8 },
  name: { color: '#fff', fontWeight: '800', fontSize: 13 },
  meta: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  picker: { borderTopWidth: 1, borderTopColor: COLORS.border, padding: 10 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginBottom: 6 },
  input: { backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, color: '#fff', paddingHorizontal: 12, paddingVertical: 9, fontSize: 14 },
  match: { padding: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  matchName: { color: '#fff', fontWeight: '700', fontSize: 13 },
  matchMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 1 },
});
