// Admin Panel — is_admin users only (bootstrap ADMIN_EMAILS or granted flag).
// In-app replacement for the terminal roster scripts: tier changes, onboarding,
// and permission grants. Every write goes through /api/admin/* which updates
// agent_profiles (source of truth) AND users, per the login re-derivation invariant.
import React, { useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, TextInput,
  Alert, ActivityIndicator, Switch,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, useAuth, roleTitle, COLORS, Role } from '../src/lib/auth';

interface Person {
  agent_id: string;
  name: string;
  email?: string;
  phone?: string;
  office?: string;
  role: Role;
  io_role?: string;
  upline_id?: string | null;
  has_login: boolean;
  is_admin: boolean;
  can_switch_role: boolean;
}

const TIERS: Role[] = ['level_1', 'level_2', 'level_3', 'level_4'];
const TIER_SHORT: Record<string, string> = { level_1: 'L1', level_2: 'L2', level_3: 'L3', level_4: 'L4' };
const IO_ROLES = ['Agent', 'SA', 'GA', 'MGA', 'RGA', 'Partner', 'Senior Partner', 'Builder', 'inTraining'];

export default function AdminScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // Add-person form state
  const [fName, setFName] = useState('');
  const [fEmail, setFEmail] = useState('');
  const [fPhone, setFPhone] = useState('');
  const [fOffice, setFOffice] = useState('MJ RGA');
  const [fRole, setFRole] = useState<Role>('level_1');
  const [fIoRole, setFIoRole] = useState<string>('Agent');
  const [fUplineQuery, setFUplineQuery] = useState('');
  const [fUpline, setFUpline] = useState<Person | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await api<{ people: Person[] }>('/api/admin/people');
      setPeople(r.people);
    } catch (e: unknown) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Failed to load roster');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user && !user.is_admin) { router.replace('/(tabs)'); return; }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) =>
      p.name.toLowerCase().includes(q) ||
      (p.email || '').toLowerCase().includes(q) ||
      (p.office || '').toLowerCase().includes(q));
  }, [people, filter]);

  const uplineMatches = useMemo(() => {
    const q = fUplineQuery.trim().toLowerCase();
    if (!q) return [];
    return people.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 5);
  }, [people, fUplineQuery]);

  const setRole = (p: Person, role: Role) => {
    if (p.role === role) return;
    Alert.alert(
      'Change Access Tier',
      `Set ${p.name} to ${TIER_SHORT[role]} (${roleTitle(undefined, role)})? This changes what data they can see.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Change',
          onPress: async () => {
            try {
              await api('/api/admin/set-role', { method: 'POST', body: JSON.stringify({ agent_id: p.agent_id, role }) });
              setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, role } : x)));
            } catch (e: unknown) {
              Alert.alert('Error', e instanceof Error ? e.message : 'Role change failed');
            }
          },
        },
      ],
    );
  };

  const setFlag = async (p: Person, flag: 'is_admin' | 'can_switch_role', value: boolean) => {
    if (!p.email) return;
    try {
      await api('/api/admin/set-flags', { method: 'POST', body: JSON.stringify({ email: p.email, [flag]: value }) });
      setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, [flag]: value } : x)));
    } catch (e: unknown) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Flag update failed');
    }
  };

  const addPerson = async () => {
    setSaving(true);
    try {
      await api('/api/admin/add-person', {
        method: 'POST',
        body: JSON.stringify({
          name: fName, email: fEmail, phone: fPhone, office: fOffice,
          role: fRole, io_role: fIoRole || null, upline_agent_id: fUpline?.agent_id || null,
        }),
      });
      setFName(''); setFEmail(''); setFPhone(''); setFUplineQuery(''); setFUpline(null);
      setShowAdd(false);
      await load();
    } catch (e: unknown) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Could not add person');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'ADMIN PANEL', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.kicker}>ROSTER MANAGEMENT</Text>
        <Text style={styles.intro}>
          Tier changes take effect immediately and update both the roster and any linked login.
        </Text>

        <TouchableOpacity style={styles.addBtn} onPress={() => setShowAdd((v) => !v)} testID="admin-toggle-add">
          <Ionicons name={showAdd ? 'chevron-up' : 'person-add'} size={16} color="#000" />
          <Text style={styles.addBtnTxt}>{showAdd ? 'Hide Form' : 'Add Person'}</Text>
        </TouchableOpacity>

        {showAdd ? (
          <View style={styles.card} testID="admin-add-form">
            <Text style={styles.lab}>NAME</Text>
            <TextInput style={styles.input} value={fName} onChangeText={setFName} placeholder="Full name" placeholderTextColor={COLORS.textMuted} testID="admin-add-name" />
            <Text style={styles.lab}>EMAIL</Text>
            <TextInput style={styles.input} value={fEmail} onChangeText={setFEmail} autoCapitalize="none" keyboardType="email-address" placeholder="name@example.com" placeholderTextColor={COLORS.textMuted} testID="admin-add-email" />
            <Text style={styles.lab}>PHONE (OPTIONAL)</Text>
            <TextInput style={styles.input} value={fPhone} onChangeText={setFPhone} keyboardType="phone-pad" placeholder="(313) 555-0100" placeholderTextColor={COLORS.textMuted} />
            <Text style={styles.lab}>OFFICE</Text>
            <TextInput style={styles.input} value={fOffice} onChangeText={setFOffice} placeholder="MJ RGA" placeholderTextColor={COLORS.textMuted} />

            <Text style={styles.lab}>ACCESS TIER</Text>
            <View style={styles.tierRow}>
              {TIERS.map((t) => (
                <TouchableOpacity key={t} style={[styles.tierBtn, fRole === t && styles.tierBtnOn]} onPress={() => setFRole(t)}>
                  <Text style={[styles.tierTxt, fRole === t && styles.tierTxtOn]}>{TIER_SHORT[t]}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.lab}>DISPLAY TITLE (IO ROLE)</Text>
            <View style={styles.chipWrap}>
              {IO_ROLES.map((r) => (
                <TouchableOpacity key={r} style={[styles.chip, fIoRole === r && styles.chipOn]} onPress={() => setFIoRole(r)}>
                  <Text style={[styles.chipTxt, fIoRole === r && styles.chipTxtOn]}>{roleTitle(r)}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.lab}>UPLINE (OPTIONAL)</Text>
            {fUpline ? (
              <View style={styles.uplinePick}>
                <Text style={styles.uplineName}>{fUpline.name} <Text style={styles.dim}>· {TIER_SHORT[fUpline.role]}</Text></Text>
                <TouchableOpacity onPress={() => { setFUpline(null); setFUplineQuery(''); }}>
                  <Ionicons name="close-circle" size={18} color={COLORS.textDim} />
                </TouchableOpacity>
              </View>
            ) : (
              <>
                <TextInput style={styles.input} value={fUplineQuery} onChangeText={setFUplineQuery} placeholder="Search upline by name" placeholderTextColor={COLORS.textMuted} />
                {uplineMatches.map((m) => (
                  <TouchableOpacity key={m.agent_id} style={styles.uplineRow} onPress={() => setFUpline(m)}>
                    <Text style={styles.uplineName}>{m.name} <Text style={styles.dim}>· {TIER_SHORT[m.role]} · {m.office}</Text></Text>
                  </TouchableOpacity>
                ))}
              </>
            )}

            <TouchableOpacity
              style={[styles.saveBtn, (saving || !fName.trim() || !fEmail.includes('@')) && { opacity: 0.5 }]}
              disabled={saving || !fName.trim() || !fEmail.includes('@')}
              onPress={addPerson}
              testID="admin-add-save"
            >
              {saving ? <ActivityIndicator color="#000" /> : <Text style={styles.saveTxt}>Add to Roster</Text>}
            </TouchableOpacity>
          </View>
        ) : null}

        <View style={styles.searchBox}>
          <Ionicons name="search" size={16} color={COLORS.textDim} />
          <TextInput
            style={styles.searchInput}
            value={filter}
            onChangeText={setFilter}
            placeholder="Search name, email, or office"
            placeholderTextColor={COLORS.textMuted}
            autoCapitalize="none"
            testID="admin-search"
          />
        </View>
        <Text style={styles.count}>{shown.length} of {people.length} people</Text>

        {loading ? (
          <ActivityIndicator color={COLORS.primary} style={{ marginTop: 30 }} />
        ) : shown.map((p) => {
          const open = expanded === p.agent_id;
          return (
            <View key={p.agent_id} style={styles.person} testID={`admin-person-${p.agent_id}`}>
              <TouchableOpacity style={styles.personHead} onPress={() => setExpanded(open ? null : p.agent_id)}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.personName}>{p.name}</Text>
                  <Text style={styles.personSub}>
                    {roleTitle(p.io_role, p.role)}{p.office ? ` · ${p.office}` : ''}
                  </Text>
                </View>
                <View style={[styles.tierBadge, !p.has_login && styles.tierBadgeDim]}>
                  <Text style={styles.tierBadgeTxt}>{TIER_SHORT[p.role] || '—'}</Text>
                </View>
                {p.is_admin ? <Ionicons name="shield-checkmark" size={14} color={COLORS.gold} /> : null}
                <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={16} color={COLORS.textDim} />
              </TouchableOpacity>

              {open ? (
                <View style={styles.personBody}>
                  <Text style={styles.detail}>{p.email || 'No email on file'}</Text>
                  <Text style={styles.detailDim}>{p.has_login ? 'Has signed in' : 'Never signed in'}</Text>

                  <Text style={styles.lab}>ACCESS TIER</Text>
                  <View style={styles.tierRow}>
                    {TIERS.map((t) => (
                      <TouchableOpacity key={t} style={[styles.tierBtn, p.role === t && styles.tierBtnOn]} onPress={() => setRole(p, t)} testID={`admin-tier-${p.agent_id}-${t}`}>
                        <Text style={[styles.tierTxt, p.role === t && styles.tierTxtOn]}>{TIER_SHORT[t]}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  <View style={styles.flagRow}>
                    <Text style={styles.flagLab}>Admin panel access</Text>
                    <Switch
                      value={p.is_admin}
                      disabled={!p.has_login}
                      onValueChange={(v) => setFlag(p, 'is_admin', v)}
                      trackColor={{ true: COLORS.primary, false: COLORS.surface2 }}
                    />
                  </View>
                  <View style={styles.flagRow}>
                    <Text style={styles.flagLab}>Role switcher (break-test)</Text>
                    <Switch
                      value={p.can_switch_role}
                      disabled={!p.has_login}
                      onValueChange={(v) => setFlag(p, 'can_switch_role', v)}
                      trackColor={{ true: COLORS.primary, false: COLORS.surface2 }}
                    />
                  </View>
                  {!p.has_login ? (
                    <Text style={styles.hint}>Flags need a login — have them sign in once first.</Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.gold, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  addBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.primary, padding: 12, borderRadius: 6, marginTop: 4 },
  addBtnTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 12, marginBottom: 4 },
  input: { backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, color: '#fff', paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  tierRow: { flexDirection: 'row', gap: 6 },
  tierBtn: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface2 },
  tierBtnOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  tierTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12 },
  tierTxtOn: { color: '#000' },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface2 },
  chipOn: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  chipTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  chipTxtOn: { color: '#fff' },
  uplinePick: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.primary, borderRadius: 6, padding: 10 },
  uplineRow: { padding: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  uplineName: { color: '#fff', fontWeight: '700', fontSize: 13 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  saveBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 16 },
  saveTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, paddingHorizontal: 12, marginTop: 16 },
  searchInput: { flex: 1, color: '#fff', paddingVertical: 10, fontSize: 14 },
  count: { color: COLORS.textMuted, fontSize: 10, marginTop: 6 },
  person: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, marginTop: 8, overflow: 'hidden' },
  personHead: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 12 },
  personName: { color: '#fff', fontWeight: '800', fontSize: 14 },
  personSub: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  tierBadge: { backgroundColor: COLORS.secondary, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  tierBadgeDim: { backgroundColor: COLORS.surface2 },
  tierBadgeTxt: { color: '#fff', fontWeight: '900', fontSize: 10 },
  personBody: { borderTopWidth: 1, borderTopColor: COLORS.border, padding: 12 },
  detail: { color: COLORS.text, fontSize: 12 },
  detailDim: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  flagRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 },
  flagLab: { color: '#fff', fontSize: 13, fontWeight: '600' },
  hint: { color: COLORS.textMuted, fontSize: 11, marginTop: 8, fontStyle: 'italic' },
});
