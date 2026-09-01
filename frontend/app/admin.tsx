// Admin Panel — is_admin users, plus finance_admin (level_1..level_3 roster
// scope + WAR import only; hierarchy-repair tools and flags stay is_admin-only).
// In-app replacement for the terminal roster scripts: tier changes, onboarding,
// and permission grants. Every write goes through /api/admin/* which updates
// agent_profiles (source of truth) AND users, per the login re-derivation invariant.
import React, { useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, TextInput,
  ActivityIndicator, Switch,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, useAuth, roleTitle, isFinanceAdmin, levelNum, COLORS, Role } from '../src/lib/auth';
import { WarReportImport } from '../src/components/WarReportImport';
import { OfficeMerge } from '../src/components/OfficeMerge';
import { OrphanRepair } from '../src/components/OrphanRepair';
import { DuplicateMerge } from '../src/components/DuplicateMerge';
import { RosterSheetSync } from '../src/components/RosterSheetSync';
import { RosterEmailAudit } from '../src/components/RosterEmailAudit';
import { confirmAsync, notify } from '../src/lib/dialog';

interface Person {
  agent_id: string;
  name: string;
  email?: string;
  phone?: string;
  office?: string;
  role: Role;
  io_role?: string;
  upline_id?: string | null;
  is_rookie?: boolean; // absent = tenure never recorded (Unknown)
  has_login: boolean;
  is_admin: boolean;
  can_switch_role: boolean;
  first_login_at?: string | null; // null until they sign in for the first time
  last_seen_at?: string | null;   // refreshed by activity, not just login
  self_registered?: boolean;      // came in through the public /join web form
  needs_review?: boolean;         // self-registered and not yet verified by an admin
  requested_title?: string;       // e.g. "RGA" — title claimed above the join-form tier cap
}

interface LoginSummary {
  roster: number;
  signed_in: number;
}

interface ArchivedPerson extends Person {
  archived_at?: string | null;
  archived_by_name?: string | null;
}

interface RemovePlan {
  children_count: number;
  destination_upline: { name: string } | null;
}

type LoginFilter = 'all' | 'in' | 'out';

// e.g. "Aug 20" this year, "Aug 20, 2025" otherwise; '—' when never signed in.
const fmtWhen = (iso?: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString(undefined, opts);
};

const TIERS: Role[] = ['level_1', 'level_2', 'level_3', 'level_4'];
// A finance_admin actor's own range: level_1..level_3 only. RGA (level_4) and
// finance_admin itself are untouchable — mirrors the 403s on /api/admin/set-role
// and /api/admin/add-person (server is the real enforcement; this is convenience).
const TIERS_FOR_FINANCE_ADMIN: Role[] = ['level_1', 'level_2', 'level_3'];
// Granting the Financial Admin role is RGA-only (true level_4, independent of
// is_admin) — see role_level(user.role) < 4 checks on /api/admin/set-role and
// /api/admin/add-person.
const TIERS_FOR_RGA: Role[] = ['level_1', 'level_2', 'level_3', 'level_4', 'finance_admin'];
const TIER_SHORT: Record<string, string> = { level_1: 'L1', level_2: 'L2', level_3: 'L3', level_4: 'L4', finance_admin: 'FA' };
const IO_ROLES = ['Agent', 'SA', 'GA', 'MGA', 'RGA', 'Partner', 'Senior Partner', 'Builder', 'inTraining'];

export default function AdminScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isFA = isFinanceAdmin(user?.role);
  // True RGA tier — not just is_admin. Only an RGA may create, remove, or
  // reassign the Financial Admin role itself (see backend/server.py).
  const isRGA = levelNum(user?.role) >= 4;
  const tiersForViewer: Role[] = isFA ? TIERS_FOR_FINANCE_ADMIN : isRGA ? TIERS_FOR_RGA : TIERS;
  const [people, setPeople] = useState<Person[]>([]);
  const [archivedPeople, setArchivedPeople] = useState<ArchivedPerson[]>([]);
  const [summary, setSummary] = useState<LoginSummary | null>(null);
  // Removal of a root (no upline) needs a destination pick; restore always
  // needs an upline pick (unless RGA). Both hold the pending person + search.
  const [destFor, setDestFor] = useState<Person | null>(null);
  const [destQuery, setDestQuery] = useState('');
  const [restoreFor, setRestoreFor] = useState<ArchivedPerson | null>(null);
  const [restoreQuery, setRestoreQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [loginFilter, setLoginFilter] = useState<LoginFilter>('all');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // Add-person form state
  const [fName, setFName] = useState('');
  const [fEmail, setFEmail] = useState('');
  const [fPhone, setFPhone] = useState('');
  const [fOffice, setFOffice] = useState('MJ RGA');
  const [fRole, setFRole] = useState<Role>('level_1');
  // Tenure starts unchosen on purpose: submit stays disabled until the admin
  // explicitly picks Veteran or Rookie — never preselected, never defaulted.
  const [fRookie, setFRookie] = useState<boolean | null>(null);
  const [fIoRole, setFIoRole] = useState<string>('Agent');
  const [fUplineQuery, setFUplineQuery] = useState('');
  const [fUpline, setFUpline] = useState<Person | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await api<{ people: Person[]; archived: ArchivedPerson[]; summary: LoginSummary }>('/api/admin/people');
      setPeople(r.people);
      setArchivedPeople(r.archived || []);
      setSummary(r.summary);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Failed to load roster');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user && !user.is_admin && !isFA) { router.replace('/(tabs)'); return; }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin, isFA]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return people.filter((p) => {
      if (loginFilter === 'in' && !p.has_login) return false;
      if (loginFilter === 'out' && p.has_login) return false;
      if (!q) return true;
      return p.name.toLowerCase().includes(q) ||
        (p.email || '').toLowerCase().includes(q) ||
        (p.office || '').toLowerCase().includes(q);
    });
  }, [people, filter, loginFilter]);

  const uplineMatches = useMemo(() => {
    const q = fUplineQuery.trim().toLowerCase();
    if (!q) return [];
    return people.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 5);
  }, [people, fUplineQuery]);

  const setRole = async (p: Person, role: Role) => {
    if (p.role === role) return;
    const ok = await confirmAsync({
      title: 'Change Access Tier',
      message: `Set ${p.name} to ${TIER_SHORT[role]} (${roleTitle(undefined, role)})? This changes what data they can see.`,
      confirmText: 'Change',
    });
    if (!ok) return;
    try {
      await api('/api/admin/set-role', { method: 'POST', body: JSON.stringify({ agent_id: p.agent_id, role }) });
      setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, role } : x)));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Role change failed');
    }
  };

  const setFlag = async (p: Person, flag: 'is_admin' | 'can_switch_role', value: boolean) => {
    if (!p.email) return;
    try {
      await api('/api/admin/set-flags', { method: 'POST', body: JSON.stringify({ email: p.email, [flag]: value }) });
      setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, [flag]: value } : x)));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Flag update failed');
    }
  };

  const addPerson = async () => {
    setSaving(true);
    try {
      const isFinanceAdminRole = fRole === 'finance_admin';
      await api('/api/admin/add-person', {
        method: 'POST',
        body: JSON.stringify({
          name: fName, email: fEmail, phone: fPhone, office: fOffice,
          role: fRole,
          // Financial Admin has no producer-track title and no upline —
          // io_role would otherwise outrank the role in roleTitle().
          io_role: isFinanceAdminRole ? null : (fIoRole || null),
          upline_agent_id: isFinanceAdminRole ? null : (fUpline?.agent_id || null),
          is_rookie: isFinanceAdminRole ? null : fRookie,
        }),
      });
      setFName(''); setFEmail(''); setFPhone(''); setFUplineQuery(''); setFUpline(null); setFRookie(null); setFRole('level_1');
      setShowAdd(false);
      await load();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not add person');
    } finally {
      setSaving(false);
    }
  };

  const removePerson = async (p: Person, destinationId?: string) => {
    setDestFor(null); setDestQuery('');
    const args = { agent_id: p.agent_id, destination_upline_agent_id: destinationId || null };
    try {
      const preview = await api<{ plan: RemovePlan }>('/api/team/remove-person', {
        method: 'POST', body: JSON.stringify({ ...args, dry_run: true }) });
      const n = preview.plan.children_count;
      const cascade = n > 0
        ? ` Their ${n} direct report${n === 1 ? '' : 's'} (and everyone under them) will move under ${preview.plan.destination_upline?.name || 'their former upline'}.`
        : '';
      const ok = await confirmAsync({
        title: 'Remove From Roster',
        message: `Remove ${p.name}? They are archived, not deleted — sales history stays in the records and you can restore them below.${cascade}`,
        confirmText: 'Remove',
      });
      if (!ok) return;
      await api('/api/team/remove-person', { method: 'POST', body: JSON.stringify(args) });
      setExpanded(null);
      await load();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Remove failed';
      if (msg.toLowerCase().includes('destination')) {
        // Root removal (no upline to inherit the team): pick who takes over.
        setDestFor(p);
        return;
      }
      notify('Error', msg);
    }
  };

  const restorePerson = async (p: ArchivedPerson, uplineId?: string) => {
    setRestoreFor(null); setRestoreQuery('');
    try {
      const ok = await confirmAsync({
        title: 'Restore To Roster',
        message: `Restore ${p.name} to the active roster? Their login links back automatically.`,
        confirmText: 'Restore',
      });
      if (!ok) return;
      await api('/api/admin/unarchive-person', {
        method: 'POST', body: JSON.stringify({ agent_id: p.agent_id, upline_agent_id: uplineId || null }) });
      await load();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Restore failed');
    }
  };

  const clearReview = async (p: Person) => {
    try {
      await api('/api/admin/clear-review', { method: 'POST', body: JSON.stringify({ agent_id: p.agent_id }) });
      setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, needs_review: false } : x)));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not mark verified');
    }
  };

  const setTenure = async (p: Person, isRookie: boolean) => {
    if (p.is_rookie === isRookie) return;
    try {
      await api('/api/admin/set-tenure', { method: 'POST', body: JSON.stringify({ agent_id: p.agent_id, is_rookie: isRookie }) });
      setPeople((prev) => prev.map((x) => (x.agent_id === p.agent_id ? { ...x, is_rookie: isRookie } : x)));
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Tenure update failed');
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

        {summary ? (
          <View style={styles.scoreCard} testID="admin-login-scoreboard">
            <Text style={styles.scoreKicker}>LOGIN SCOREBOARD</Text>
            <View style={styles.scoreRow}>
              <Text style={styles.scoreBig}>
                {summary.signed_in}
                <Text style={styles.scoreOf}> / {summary.roster}</Text>
              </Text>
              <Text style={styles.scorePct}>
                {summary.roster > 0 ? Math.round((summary.signed_in / summary.roster) * 100) : 0}%
              </Text>
            </View>
            <View style={styles.scoreTrack}>
              <View
                style={[styles.scoreFill,
                  { width: `${summary.roster > 0 ? Math.round((summary.signed_in / summary.roster) * 100) : 0}%` }]}
              />
            </View>
            <Text style={styles.scoreSub}>
              {summary.roster - summary.signed_in === 0
                ? 'Everyone on the roster has signed in.'
                : `${summary.roster - summary.signed_in} still haven't signed in — tap NOT SIGNED IN below to see who to chase.`}
            </Text>
          </View>
        ) : null}

        <TouchableOpacity style={styles.addBtn} onPress={() => setShowAdd((v) => !v)} testID="admin-toggle-add">
          <Ionicons name={showAdd ? 'chevron-up' : 'person-add'} size={16} color="#000" />
          <Text style={styles.addBtnTxt}>{showAdd ? 'Hide Form' : 'Add Person'}</Text>
        </TouchableOpacity>

        {isFA ? (
          // finance_admin has no tab bar (see (tabs)/_layout.tsx), so the usual
          // More-tab entry point to Company Health/Historical Vault never
          // renders for it — surface it here instead.
          <TouchableOpacity style={styles.addBtn} onPress={() => router.push('/vault')} testID="admin-open-vault">
            <Ionicons name="stats-chart" size={16} color="#000" />
            <Text style={styles.addBtnTxt}>Company Health / Vault</Text>
          </TouchableOpacity>
        ) : null}

        <WarReportImport />

        {/* Hierarchy-repair tools stay is_admin-only — finance_admin's roster
            write scope is level_1..level_3 add/remove/role-change and the WAR
            import above, nothing that restructures the tree or touches
            other people's flags. */}
        {!isFA ? (
          <>
            <OfficeMerge />
            <OrphanRepair candidates={people} onRepaired={load} />
            <DuplicateMerge onMerged={load} />
            <RosterSheetSync onSynced={load} />
            <RosterEmailAudit onFixed={load} />
          </>
        ) : null}

        {showAdd ? (
          <View style={styles.card} testID="admin-add-form">
            <Text style={styles.lab}>NAME</Text>
            <TextInput style={styles.input} value={fName} onChangeText={setFName} placeholder="Full name" placeholderTextColor={COLORS.textMuted} testID="admin-add-name" />
            <Text style={styles.lab}>EMAIL</Text>
            <TextInput style={styles.input} value={fEmail} onChangeText={setFEmail} autoCapitalize="none" keyboardType="email-address" placeholder="name@example.com" placeholderTextColor={COLORS.textMuted} testID="admin-add-email" />
            <Text style={styles.fieldNote}>
              Must exactly match the email they will sign in with (Google or Apple) — a mismatch leaves them stuck on the pending screen.
            </Text>
            <Text style={styles.lab}>PHONE (OPTIONAL)</Text>
            <TextInput style={styles.input} value={fPhone} onChangeText={setFPhone} keyboardType="phone-pad" placeholder="(313) 555-0100" placeholderTextColor={COLORS.textMuted} />
            <Text style={styles.lab}>OFFICE</Text>
            <TextInput style={styles.input} value={fOffice} onChangeText={setFOffice} placeholder="MJ RGA" placeholderTextColor={COLORS.textMuted} />

            <Text style={styles.lab}>ACCESS TIER</Text>
            <View style={styles.tierRow}>
              {tiersForViewer.map((t) => (
                <TouchableOpacity key={t} style={[styles.tierBtn, fRole === t && styles.tierBtnOn]} onPress={() => setFRole(t)}>
                  <Text style={[styles.tierTxt, fRole === t && styles.tierTxtOn]}>{TIER_SHORT[t]}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {fRole === 'finance_admin' ? (
              <Text style={styles.fieldNote}>
                Financial Admin has no production identity — no tenure, no display title, no upline. It can sign in, manage
                Agent through MGA-level team members, upload/print WAR reports, and browse the Historical Vault. Only an RGA
                can grant, remove, or reassign this role.
              </Text>
            ) : (
              <>
                <Text style={styles.lab}>TENURE — DRIVES PLATINUM WALL + ROOKIE BADGE</Text>
                <View style={styles.tierRow}>
                  <TouchableOpacity
                    style={[styles.tierBtn, fRookie === false && styles.tierBtnOn]}
                    onPress={() => setFRookie(false)}
                    testID="admin-add-tenure-vet"
                  >
                    <Text style={[styles.tierTxt, fRookie === false && styles.tierTxtOn]}>VETERAN</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.tierBtn, fRookie === true && styles.tierBtnOn]}
                    onPress={() => setFRookie(true)}
                    testID="admin-add-tenure-rookie"
                  >
                    <Text style={[styles.tierTxt, fRookie === true && styles.tierTxtOn]}>ROOKIE</Text>
                  </TouchableOpacity>
                </View>
                {fRookie === null ? <Text style={styles.fieldNote}>Pick one — there is no default.</Text> : null}

                <Text style={styles.lab}>DISPLAY TITLE (IO ROLE)</Text>
                <View style={styles.chipWrap}>
                  {IO_ROLES.map((r) => (
                    <TouchableOpacity key={r} style={[styles.chip, fIoRole === r && styles.chipOn]} onPress={() => setFIoRole(r)}>
                      <Text style={[styles.chipTxt, fIoRole === r && styles.chipTxtOn]}>{roleTitle(r)}</Text>
                    </TouchableOpacity>
                  ))}
                </View>

                <Text style={styles.lab}>{fRole === 'level_4' ? 'UPLINE (OPTIONAL FOR RGA)' : 'UPLINE (REQUIRED)'}</Text>
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
              </>
            )}

            <TouchableOpacity
              style={[styles.saveBtn, (saving || !fName.trim() || !fEmail.includes('@') ||
                (fRole !== 'finance_admin' && fRookie === null) ||
                (fRole !== 'level_4' && fRole !== 'finance_admin' && !fUpline)) && { opacity: 0.5 }]}
              disabled={saving || !fName.trim() || !fEmail.includes('@') ||
                (fRole !== 'finance_admin' && fRookie === null) ||
                (fRole !== 'level_4' && fRole !== 'finance_admin' && !fUpline)}
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
        <View style={styles.tierRow}>
          {([['all', 'ALL'], ['in', 'SIGNED IN'], ['out', 'NOT SIGNED IN']] as [LoginFilter, string][]).map(([key, label]) => (
            <TouchableOpacity
              key={key}
              style={[styles.tierBtn, styles.loginFilterBtn, loginFilter === key && styles.tierBtnOn]}
              onPress={() => setLoginFilter(key)}
              testID={`admin-login-filter-${key}`}
            >
              <Text style={[styles.tierTxt, loginFilter === key && styles.tierTxtOn]}>{label}</Text>
            </TouchableOpacity>
          ))}
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
                    {p.is_rookie === true ? ' · Rookie' : p.is_rookie === false ? ' · Veteran' : ' · Tenure unknown'}
                  </Text>
                </View>
                {p.needs_review ? (
                  <View style={styles.reviewBadge}>
                    <Text style={styles.reviewBadgeTxt}>VERIFY</Text>
                  </View>
                ) : null}
                <View style={[styles.tierBadge, !p.has_login && styles.tierBadgeDim]}>
                  <Text style={styles.tierBadgeTxt}>{TIER_SHORT[p.role] || '—'}</Text>
                </View>
                {p.is_admin ? <Ionicons name="shield-checkmark" size={14} color={COLORS.gold} /> : null}
                <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={16} color={COLORS.textDim} />
              </TouchableOpacity>

              {open ? (
                <View style={styles.personBody}>
                  <Text style={styles.detail}>{p.email || 'No email on file'}</Text>
                  <Text style={styles.detailDim}>
                    {p.has_login
                      ? `First login ${fmtWhen(p.first_login_at)} · Last seen ${fmtWhen(p.last_seen_at)}`
                      : 'Never signed in'}
                  </Text>

                  {p.needs_review ? (
                    <View style={styles.reviewCard}>
                      <Text style={styles.reviewCardTxt}>
                        Self-registered via the /join web form — check their tier, upline, and team.
                        {p.requested_title ? ` They said they're ${p.requested_title === 'RGA' ? 'an' : 'a'} ${p.requested_title}; the form capped them at L3 — bump the tier if that's right.` : ''}
                      </Text>
                      <TouchableOpacity style={styles.reviewBtn} onPress={() => clearReview(p)} testID={`admin-verify-${p.agent_id}`}>
                        <Ionicons name="checkmark-circle" size={14} color="#000" />
                        <Text style={styles.reviewBtnTxt}>MARK VERIFIED</Text>
                      </TouchableOpacity>
                    </View>
                  ) : null}

                  {/* A finance_admin actor can't touch an RGA or another
                      Financial Admin at all — mirrors the 403 on
                      /api/admin/set-role and /api/team/remove-person. */}
                  {isFA && (p.role === 'level_4' || p.role === 'finance_admin') ? (
                    <Text style={styles.fieldNote}>
                      {p.role === 'level_4' ? 'RGA accounts' : 'Financial Admin accounts'} can only be changed by an RGA.
                    </Text>
                  ) : (
                    <>
                      <Text style={styles.lab}>ACCESS TIER</Text>
                      <View style={styles.tierRow}>
                        {tiersForViewer.map((t) => (
                          <TouchableOpacity key={t} style={[styles.tierBtn, p.role === t && styles.tierBtnOn]} onPress={() => setRole(p, t)} testID={`admin-tier-${p.agent_id}-${t}`}>
                            <Text style={[styles.tierTxt, p.role === t && styles.tierTxtOn]}>{TIER_SHORT[t]}</Text>
                          </TouchableOpacity>
                        ))}
                      </View>

                      <Text style={styles.lab}>TENURE{p.is_rookie === undefined ? ' — NOT RECORDED YET' : ''}</Text>
                      <View style={styles.tierRow}>
                        <TouchableOpacity
                          style={[styles.tierBtn, p.is_rookie === false && styles.tierBtnOn]}
                          onPress={() => setTenure(p, false)}
                          testID={`admin-tenure-${p.agent_id}-vet`}
                        >
                          <Text style={[styles.tierTxt, p.is_rookie === false && styles.tierTxtOn]}>VETERAN</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={[styles.tierBtn, p.is_rookie === true && styles.tierBtnOn]}
                          onPress={() => setTenure(p, true)}
                          testID={`admin-tenure-${p.agent_id}-rookie`}
                        >
                          <Text style={[styles.tierTxt, p.is_rookie === true && styles.tierTxtOn]}>ROOKIE</Text>
                        </TouchableOpacity>
                      </View>
                    </>
                  )}

                  {!isFA ? (
                    <>
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
                    </>
                  ) : null}

                  {isFA && (p.role === 'level_4' || p.role === 'finance_admin') ? null : (
                    <TouchableOpacity
                      style={styles.removeBtn}
                      onPress={() => removePerson(p)}
                      testID={`admin-remove-${p.agent_id}`}
                    >
                      <Ionicons name="person-remove" size={14} color={COLORS.red} />
                      <Text style={styles.removeBtnTxt}>REMOVE FROM ROSTER (ARCHIVE)</Text>
                    </TouchableOpacity>
                  )}
                  {destFor?.agent_id === p.agent_id ? (
                    <View style={styles.pickerBox}>
                      <Text style={styles.fieldNote}>
                        They lead a team and have no upline — pick their direct report to promote, or someone outside the team, to take it over.
                      </Text>
                      <TextInput
                        style={styles.input}
                        value={destQuery}
                        onChangeText={setDestQuery}
                        placeholder="Search destination upline by name"
                        placeholderTextColor={COLORS.textMuted}
                        testID="admin-remove-dest-search"
                      />
                      {people
                        .filter((c) => c.agent_id !== p.agent_id &&
                          destQuery.trim() && c.name.toLowerCase().includes(destQuery.trim().toLowerCase()))
                        .slice(0, 5)
                        .map((c) => (
                          <TouchableOpacity key={c.agent_id} style={styles.uplineRow} onPress={() => removePerson(p, c.agent_id)}>
                            <Text style={styles.uplineName}>{c.name} <Text style={styles.dim}>· {TIER_SHORT[c.role]} · {c.office}</Text></Text>
                          </TouchableOpacity>
                        ))}
                    </View>
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}

        {/* Restoring an archived person stays is_admin-only (RGA-territory —
            not in finance_admin's remove/add/change-role range). */}
        {!isFA && archivedPeople.length > 0 ? (
          <>
            <Text style={[styles.kicker, { marginTop: 24 }]}>ARCHIVED — REMOVED FROM TEAM</Text>
            <Text style={styles.intro}>
              Kept for history, hidden from the roster, login parked on the pending screen. Restore re-links everything.
            </Text>
            {archivedPeople.map((p) => (
              <View key={p.agent_id} style={[styles.person, styles.archivedRow]} testID={`admin-archived-${p.agent_id}`}>
                <View style={styles.personHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.personName}>{p.name}</Text>
                    <Text style={styles.personSub}>
                      {roleTitle(p.io_role, p.role)}{p.office ? ` · ${p.office}` : ''}
                      {p.archived_at ? ` · Removed ${new Date(p.archived_at).toLocaleDateString()}` : ''}
                      {p.archived_by_name ? ` by ${p.archived_by_name}` : ''}
                    </Text>
                  </View>
                  <TouchableOpacity
                    style={styles.restoreBtn}
                    onPress={() => (p.role === 'level_4' ? restorePerson(p) : setRestoreFor(restoreFor?.agent_id === p.agent_id ? null : p))}
                    testID={`admin-restore-${p.agent_id}`}
                  >
                    <Text style={styles.restoreBtnTxt}>RESTORE</Text>
                  </TouchableOpacity>
                </View>
                {restoreFor?.agent_id === p.agent_id ? (
                  <View style={[styles.personBody, styles.pickerBox]}>
                    <Text style={styles.fieldNote}>Pick the upline to restore them under.</Text>
                    <TextInput
                      style={styles.input}
                      value={restoreQuery}
                      onChangeText={setRestoreQuery}
                      placeholder="Search upline by name"
                      placeholderTextColor={COLORS.textMuted}
                      testID="admin-restore-upline-search"
                    />
                    {people
                      .filter((c) => restoreQuery.trim() && c.name.toLowerCase().includes(restoreQuery.trim().toLowerCase()))
                      .slice(0, 5)
                      .map((c) => (
                        <TouchableOpacity key={c.agent_id} style={styles.uplineRow} onPress={() => restorePerson(p, c.agent_id)}>
                          <Text style={styles.uplineName}>{c.name} <Text style={styles.dim}>· {TIER_SHORT[c.role]} · {c.office}</Text></Text>
                        </TouchableOpacity>
                      ))}
                  </View>
                ) : null}
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.gold, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  scoreCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.gold, borderRadius: 6, padding: 14, marginBottom: 10 },
  scoreKicker: { color: COLORS.gold, fontWeight: '900', fontSize: 9, letterSpacing: 1.2 },
  scoreRow: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', marginTop: 6 },
  scoreBig: { color: '#fff', fontWeight: '900', fontSize: 28 },
  scoreOf: { color: COLORS.textDim, fontWeight: '700', fontSize: 16 },
  scorePct: { color: COLORS.gold, fontWeight: '900', fontSize: 16 },
  scoreTrack: { height: 6, borderRadius: 3, backgroundColor: COLORS.surface2, marginTop: 8, overflow: 'hidden' },
  scoreFill: { height: 6, borderRadius: 3, backgroundColor: COLORS.gold },
  scoreSub: { color: COLORS.textDim, fontSize: 11, marginTop: 8 },
  loginFilterBtn: { marginTop: 8 },
  addBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.primary, padding: 12, borderRadius: 6, marginTop: 4 },
  addBtnTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 12, marginBottom: 4 },
  fieldNote: { color: COLORS.textDim, fontSize: 11, marginTop: 4, fontStyle: 'italic' },
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
  reviewBadge: { backgroundColor: 'rgba(255,215,0,0.16)', borderWidth: 1, borderColor: COLORS.gold, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  reviewBadgeTxt: { color: COLORS.gold, fontWeight: '900', fontSize: 9, letterSpacing: 1 },
  reviewCard: { backgroundColor: 'rgba(255,215,0,0.10)', borderWidth: 1, borderColor: 'rgba(255,215,0,0.45)', borderRadius: 8, padding: 10, marginTop: 10 },
  reviewCardTxt: { color: COLORS.gold, fontSize: 12, lineHeight: 17 },
  reviewBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: COLORS.gold, borderRadius: 6, paddingVertical: 8, marginTop: 10 },
  reviewBtnTxt: { color: '#000', fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  tierBadge: { backgroundColor: COLORS.secondary, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  tierBadgeDim: { backgroundColor: COLORS.surface2 },
  tierBadgeTxt: { color: '#fff', fontWeight: '900', fontSize: 10 },
  personBody: { borderTopWidth: 1, borderTopColor: COLORS.border, padding: 12 },
  detail: { color: COLORS.text, fontSize: 12 },
  detailDim: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  flagRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 },
  flagLab: { color: '#fff', fontSize: 13, fontWeight: '600' },
  hint: { color: COLORS.textMuted, fontSize: 11, marginTop: 8, fontStyle: 'italic' },
  removeBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    borderWidth: 1, borderColor: COLORS.red, borderRadius: 6, padding: 10, marginTop: 14,
  },
  removeBtnTxt: { color: COLORS.red, fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  pickerBox: { marginTop: 8 },
  archivedRow: { opacity: 0.85, borderColor: COLORS.red },
  restoreBtn: { borderWidth: 1, borderColor: COLORS.gold, borderRadius: 4, paddingHorizontal: 10, paddingVertical: 6 },
  restoreBtnTxt: { color: COLORS.gold, fontWeight: '900', fontSize: 10, letterSpacing: 1 },
});
