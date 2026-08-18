// Roster office cleanup + rename — Admin screen only.
//
// One office recorded under two names (a WAR sheet header says "Mohamed
// Aljahmi RGA" where the roster says "MJ RGA") appears as two tabs everywhere
// offices are listed and splits that office's numbers between them.
// agent_profiles is the source of truth every office lookup resolves through,
// so this merges them there — which corrects historical weeks too, since
// nothing groups by the office stamped on an entry.
//
// The same action doubles as a plain rename: the destination doesn't have to
// be an office that already exists (the backend just does an update_many),
// so typing a brand-new name in the free-text field below renames the
// retired office to that name instead of folding it into an existing one.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

interface OfficeRow { office: string; agents: number; }

export function OfficeMerge() {
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const [toCustom, setToCustom] = useState('');
  const [busy, setBusy] = useState(false);

  // Typing a new name and picking an existing chip are mutually exclusive —
  // whichever the admin touched most recently wins.
  const effectiveTo = toCustom.trim() || to;

  const load = useCallback(async () => {
    try {
      const r = await api<{ offices: OfficeRow[] }>('/api/admin/offices');
      setOffices(r.offices);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load offices');
    } finally {
      setLoaded(true);
    }
  }, []);

  // The fetch is awaited rather than called bare, so no setState runs
  // synchronously in the effect body and triggers a cascading render.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => { await load(); if (cancelled) return; })();
    return () => { cancelled = true; };
  }, [open, load]);

  const merge = async () => {
    if (!from || !effectiveTo || from === effectiveTo) return;
    const src = offices.find((o) => o.office === from);
    const isRename = !offices.some((o) => o.office === effectiveTo);
    const ok = await confirmAsync({
      title: isRename ? 'Rename this office?' : 'Merge offices?',
      message: isRename
        ? `Rename "${from}" (${src?.agents ?? 0} agent(s)) to "${effectiveTo}". `
          + 'This updates the roster, so past weeks show the new name too.'
        : `Move ${src?.agents ?? 0} agent(s) from "${from}" into "${effectiveTo}". `
          + 'This updates the roster, so past weeks re-group under the new office too.',
      confirmText: isRename ? 'Rename' : 'Merge',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<{ agents_moved: number }>('/api/admin/merge-office', {
        method: 'POST',
        body: JSON.stringify({ from_office: from, to_office: effectiveTo }),
      });
      notify(isRename ? 'Renamed' : 'Merged', `${r.agents_moved} agent(s) moved into "${effectiveTo}".`);
      setFrom(null); setTo(null); setToCustom('');
      await load();
    } catch (e: unknown) {
      notify(isRename ? 'Rename failed' : 'Merge failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="office-merge-open">
        <Ionicons name="git-merge-outline" size={16} color={COLORS.secondary} />
        <Text style={styles.openTxt}>RENAME OR MERGE AN OFFICE</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Rename or Merge an Office</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="office-merge-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Pick the office to retire. Then either pick an existing office to fold it into,
        or type a brand-new name to simply rename it. Agents move to the new name and
        every screen — including past weeks — regroups under it.
      </Text>

      {!loaded ? (
        <View style={styles.loading}><ActivityIndicator color={COLORS.primary} /></View>
      ) : (
        <>
          <Text style={styles.lab}>RETIRE THIS OFFICE</Text>
          <View style={styles.chipWrap}>
            {offices.map((o) => (
              <TouchableOpacity
                key={`from-${o.office}`}
                onPress={() => setFrom(o.office === from ? null : o.office)}
                style={[styles.chip, o.office === from && styles.chipFrom]}
                testID={`office-from-${o.office}`}
              >
                <Text style={[styles.chipTxt, o.office === from && styles.chipTxtOn]}>
                  {o.office} · {o.agents}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.lab}>KEEP THIS OFFICE</Text>
          <View style={styles.chipWrap}>
            {offices.filter((o) => o.office !== from).map((o) => (
              <TouchableOpacity
                key={`to-${o.office}`}
                onPress={() => { setTo(o.office === to ? null : o.office); setToCustom(''); }}
                style={[styles.chip, o.office === to && styles.chipTo]}
                testID={`office-to-${o.office}`}
              >
                <Text style={[styles.chipTxt, o.office === to && styles.chipTxtOn]}>
                  {o.office} · {o.agents}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.lab}>OR TYPE A NEW NAME TO RENAME IT</Text>
          <TextInput
            style={styles.renameInput}
            value={toCustom}
            onChangeText={(v) => { setToCustom(v); if (v) setTo(null); }}
            placeholder="e.g. ALWATAN RGA"
            placeholderTextColor={COLORS.textMuted}
            autoCapitalize="characters"
            testID="office-to-custom"
          />

          <TouchableOpacity
            style={[styles.mergeBtn, (!from || !effectiveTo || busy) && styles.mergeBtnOff]}
            onPress={merge}
            disabled={!from || !effectiveTo || busy}
            testID="office-merge-run"
          >
            {busy ? <ActivityIndicator color="#000" /> : (
              <Text style={styles.mergeTxt}>
                {from && effectiveTo ? `${offices.some((o) => o.office === effectiveTo) ? 'MOVE' : 'RENAME'} "${from}" → "${effectiveTo}"` : 'PICK AN OFFICE AND A NEW NAME'}
              </Text>
            )}
          </TouchableOpacity>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  openBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.secondary, padding: 12, borderRadius: 6, marginTop: 10 },
  openTxt: { color: COLORS.secondary, fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: '#fff', fontWeight: '900', fontSize: 15 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  loading: { paddingVertical: 20, alignItems: 'center' },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 14, marginBottom: 6 },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface2 },
  chipFrom: { backgroundColor: COLORS.red, borderColor: COLORS.red },
  chipTo: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  chipTxtOn: { color: '#000' },
  renameInput: { backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10, color: '#fff', fontSize: 13, fontWeight: '700' },
  mergeBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 16 },
  mergeBtnOff: { opacity: 0.4 },
  mergeTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
});
