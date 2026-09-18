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
import { TypedConfirm } from './TypedConfirm';

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

interface HierarchyProposal {
  agent_id: string; name: string; office?: string;
  upline_agent_id?: string; upline_name: string;
}
interface HierarchyMerge {
  keep_agent_id: string; keep_name: string;
  remove_agent_id: string; remove_name?: string; office?: string;
}
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
  // The bulk fix is reviewed before it runs, never described in a dialog.
  // It re-points N people's uplines and permanently deletes N duplicate
  // profiles, and the names are already on the wire — approving a count
  // means approving a list you were never shown.
  const [reviewing, setReviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);

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

  const nLink = plan?.proposals.length ?? 0;
  const nMerge = plan?.merges.length ?? 0;

  const runAutoLink = async () => {
    setConfirming(false);
    setBusy(true);
    try {
      const r = await api<{ applied: HierarchyProposal[]; merged: HierarchyMerge[] }>(
        '/api/admin/hierarchy-audit/fix', { method: 'POST' });
      setReviewing(false);
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

  // Merges delete a profile outright, so they get the typed confirm the
  // duplicate-merge tool uses. A re-link only moves an upline_id and an admin
  // can reassign it by hand, so that alone stays an ordinary confirm.
  const applyPlan = async () => {
    if (nLink + nMerge === 0) return;
    if (nMerge > 0) { setConfirming(true); return; }
    const ok = await confirmAsync({
      title: 'Link these agents?',
      message:
        `${nLink} agent${nLink === 1 ? '' : 's'} will be linked to the upline the ` +
        'roster sheets record, exactly as listed. Anyone the sheets don’t cover ' +
        'stays listed for manual assignment.',
      confirmText: `Link ${nLink}`,
    });
    if (ok) await runAutoLink();
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
          {plan && nLink + nMerge > 0 ? (
            <>
              <TouchableOpacity
                style={[styles.autoBtn, busy && { opacity: 0.5 }]}
                onPress={() => setReviewing((v) => !v)}
                disabled={busy}
                testID="orphans-autolink"
              >
                <Text style={styles.autoTxt}>
                  {reviewing ? 'HIDE' : 'REVIEW'} {nLink + nMerge} FIX{nLink + nMerge === 1 ? '' : 'ES'}
                  {nMerge > 0 ? ` (LINK ${nLink} · MERGE ${nMerge})` : ' FROM ROSTER SHEET'}
                </Text>
              </TouchableOpacity>

              {reviewing ? (
                <View style={styles.review} testID="orphans-review">
                  {nMerge > 0 ? (
                    <>
                      <Text style={styles.reviewLab}>
                        MERGE · {nMerge} DUPLICATE PROFILE{nMerge === 1 ? '' : 'S'} DELETED
                      </Text>
                      {plan.merges.map((m) => (
                        <Text key={m.remove_agent_id} style={styles.reviewRow} testID={`orphan-plan-merge-${m.remove_agent_id}`}>
                          <Text style={styles.reviewGone}>{m.remove_name || m.remove_agent_id}</Text>
                          <Text style={styles.reviewDim}> folds into </Text>
                          <Text style={styles.reviewKeep}>{m.keep_name}</Text>
                          {m.office ? <Text style={styles.reviewDim}> · {m.office}</Text> : null}
                        </Text>
                      ))}
                    </>
                  ) : null}

                  {nLink > 0 ? (
                    <>
                      <Text style={[styles.reviewLab, nMerge > 0 && { marginTop: 10 }]}>
                        LINK · {nLink} UPLINE{nLink === 1 ? '' : 'S'} SET FROM THE SHEET
                      </Text>
                      {plan.proposals.map((pr) => (
                        <Text key={pr.agent_id} style={styles.reviewRow} testID={`orphan-plan-link-${pr.agent_id}`}>
                          <Text style={styles.reviewKeep}>{pr.name}</Text>
                          <Text style={styles.reviewDim}> reports to </Text>
                          <Text style={styles.reviewKeep}>{pr.upline_name}</Text>
                          {pr.office ? <Text style={styles.reviewDim}> · {pr.office}</Text> : null}
                        </Text>
                      ))}
                    </>
                  ) : null}

                  <TouchableOpacity
                    style={[styles.applyBtn, busy && { opacity: 0.5 }]}
                    onPress={applyPlan}
                    disabled={busy}
                    testID="orphans-apply"
                  >
                    {busy
                      ? <ActivityIndicator color="#000" />
                      : <Text style={styles.applyTxt}>APPLY ALL {nLink + nMerge}</Text>}
                  </TouchableOpacity>
                </View>
              ) : null}
            </>
          ) : null}
          {plan && plan.unresolved.length > 0 ? (
            <Text style={styles.unresolvedNote}>
              {(() => {
                const notOnSheet = plan.unresolved.filter((u) => u.reason === 'not_on_sheet').length;
                const uplineMissing = plan.unresolved.length - notOnSheet;
                const parts = [];
                if (notOnSheet > 0) parts.push(`${notOnSheet} aren't on any roster sheet the app has (former agents, or missing from the sheet)`);
                if (uplineMissing > 0) parts.push(`${uplineMissing} are on the sheet but the upline it names couldn't be found in the app`);
                return `${parts.join('; ')} — assign them below, or update the office's roster sheet in the app's data.`;
              })()}
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

      <TypedConfirm
        visible={confirming}
        title="MERGE AND LINK"
        message={
          `${nMerge} duplicate profile${nMerge === 1 ? ' is' : 's are'} deleted and folded ` +
          `into the profile named beside ${nMerge === 1 ? 'it' : 'each'}` +
          (nLink > 0 ? `, and ${nLink} agent${nLink === 1 ? '' : 's'} are linked to their sheet upline` : '') +
          '.\n\nThe merges cannot be undone. The list above is exactly what runs.'
        }
        word="MERGE"
        confirmText={`APPLY ${nLink + nMerge}`}
        busy={busy}
        onCancel={() => setConfirming(false)}
        onConfirm={runAutoLink}
      />
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
  review: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 10, marginTop: 8 },
  reviewLab: { color: COLORS.orange, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginBottom: 4 },
  reviewRow: { fontSize: 12, lineHeight: 18, marginTop: 2 },
  reviewKeep: { color: '#fff', fontWeight: '800' },
  reviewGone: { color: COLORS.orange, fontWeight: '800', textDecorationLine: 'line-through' },
  reviewDim: { color: COLORS.textDim, fontWeight: '500' },
  applyBtn: { backgroundColor: COLORS.primary, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 12 },
  applyTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 0.5 },
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
