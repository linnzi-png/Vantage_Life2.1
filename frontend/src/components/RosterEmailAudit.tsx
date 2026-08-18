// Roster email audit — Admin screen only.
//
// Login authorization is an exact match of the lowercased sign-in email
// against agent_profiles.email, so a stale or misspelled stored email strands
// a real agent on the pending screen even though their sign-in succeeded.
// This card runs the server-side audit against the committed roster sheet
// snapshot (backend/data/roster/): a dry-run report first, then a separate
// confirmed action to apply the email corrections. Missing people are never
// auto-created — they need role + upline, so onboard them via Add Person.
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { confirmAsync, notify } from '../lib/dialog';

interface AuditMismatch { name: string; db_email: string; sheet_email: string; }
interface AuditPerson { name: string; email: string; }
interface AuditMissing { app_id: string; name: string; email: string; }
interface AuditAmbiguous { name: string; sheet_email: string; candidates: AuditPerson[]; }
interface AuditConflictHolder { name: string; role: string; agent_id: string; }
interface AuditConflict { name: string; sheet_email: string; holders: AuditConflictHolder[]; }
interface AuditExtra { name: string; email: string; role: string; }

interface AuditReport {
  fixed: boolean;
  roster_size: number;
  ok: number;
  mismatches: AuditMismatch[];
  not_lowercase: AuditPerson[];
  missing: AuditMissing[];
  ambiguous: AuditAmbiguous[];
  conflicts: AuditConflict[];
  extra: AuditExtra[];
}

export function RosterEmailAudit({ onFixed }: { onFixed: () => void }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [busy, setBusy] = useState<'audit' | 'fix' | null>(null);
  const [showMissing, setShowMissing] = useState(false);
  const [showExtra, setShowExtra] = useState(false);

  const runAudit = async () => {
    setBusy('audit');
    try {
      setReport(await api<AuditReport>('/api/admin/roster-audit'));
    } catch (e: unknown) {
      notify('Audit failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(null);
    }
  };

  const fixable = report ? report.mismatches.length + report.not_lowercase.length : 0;

  const applyFixes = async () => {
    if (!report) return;
    const ok = await confirmAsync({
      title: 'Apply Email Fixes',
      message: `Update ${fixable} stored email${fixable === 1 ? '' : 's'} to match the roster sheet? Anyone already signed in with the correct address is linked immediately.`,
      confirmText: 'Apply',
    });
    if (!ok) return;
    setBusy('fix');
    try {
      const r = await api<AuditReport>('/api/admin/roster-audit/fix', { method: 'POST' });
      setReport(r);
      notify('Emails synced', `${r.mismatches.length + r.not_lowercase.length} email${r.mismatches.length + r.not_lowercase.length === 1 ? '' : 's'} corrected. Audit log updated.`);
      onFixed();
    } catch (e: unknown) {
      notify('Fix failed', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(null);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="roster-audit-open">
        <Ionicons name="mail-unread-outline" size={16} color={COLORS.gold} />
        <Text style={styles.openTxt}>VERIFY LOGIN EMAILS</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Login Email Audit</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="roster-audit-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Sign-in matches each person&apos;s email exactly, so a stale address on the
        roster leaves a real agent stuck on the pending screen. This checks every
        stored email against the office&apos;s agent list and can correct the
        differences in one step.
      </Text>

      <TouchableOpacity
        style={[styles.runBtn, busy !== null && { opacity: 0.5 }]}
        onPress={runAudit}
        disabled={busy !== null}
        testID="roster-audit-run"
      >
        {busy === 'audit' ? <ActivityIndicator color="#000" /> : (
          <Text style={styles.runTxt}>{report ? 'Re-Run Audit' : 'Run Audit'}</Text>
        )}
      </TouchableOpacity>

      {report ? (
        <View style={{ marginTop: 12 }}>
          <Text style={styles.summary}>
            {report.ok} of {report.roster_size} on the sheet already match.
          </Text>

          {report.mismatches.length > 0 ? (
            <>
              <Text style={styles.sectionBad}>WRONG EMAIL IN DATABASE · {report.mismatches.length}</Text>
              {report.mismatches.map((m) => (
                <View key={m.sheet_email} style={styles.row}>
                  <Text style={styles.name}>{m.name}</Text>
                  <Text style={styles.meta}>{m.db_email} → {m.sheet_email}</Text>
                </View>
              ))}
            </>
          ) : null}

          {report.not_lowercase.length > 0 ? (
            <>
              <Text style={styles.sectionBad}>BROKEN FORMATTING · {report.not_lowercase.length}</Text>
              {report.not_lowercase.map((p) => (
                <View key={p.email} style={styles.row}>
                  <Text style={styles.name}>{p.name}</Text>
                  <Text style={styles.meta}>{p.email}</Text>
                </View>
              ))}
            </>
          ) : null}

          {fixable > 0 && !report.fixed ? (
            <TouchableOpacity
              style={[styles.fixBtn, busy !== null && { opacity: 0.5 }]}
              onPress={applyFixes}
              disabled={busy !== null}
              testID="roster-audit-fix"
            >
              {busy === 'fix' ? <ActivityIndicator color="#000" /> : (
                <Text style={styles.fixTxt}>Apply {fixable} Email Fix{fixable === 1 ? '' : 'es'}</Text>
              )}
            </TouchableOpacity>
          ) : null}
          {fixable === 0 ? (
            <Text style={styles.clear}>Every stored email matches the sheet.</Text>
          ) : null}

          {report.conflicts.length > 0 ? (
            <>
              <Text style={styles.sectionBad}>EMAIL HELD BY ANOTHER PROFILE · {report.conflicts.length}</Text>
              <Text style={styles.hint}>
                Never fixed automatically: writing this email would leave two profiles
                sharing one login. Resolve the profile that shouldn&apos;t hold it first.
              </Text>
              {report.conflicts.map((c) => (
                <View key={c.sheet_email} style={styles.row}>
                  <Text style={styles.name}>{c.name}</Text>
                  <Text style={styles.meta}>
                    {c.sheet_email} is already on: {c.holders.map((h) => `${h.name} (${h.role})`).join(', ')}
                  </Text>
                </View>
              ))}
            </>
          ) : null}

          {report.ambiguous.length > 0 ? (
            <>
              <Text style={styles.sectionWarn}>NEEDS A HUMAN DECISION · {report.ambiguous.length}</Text>
              {report.ambiguous.map((a) => (
                <View key={a.sheet_email} style={styles.row}>
                  <Text style={styles.name}>{a.name}</Text>
                  <Text style={styles.meta}>
                    Sheet says {a.sheet_email}, but several roster entries could be this
                    person: {a.candidates.map((c) => `${c.name} (${c.email})`).join(', ')}
                  </Text>
                </View>
              ))}
            </>
          ) : null}

          {report.missing.length > 0 ? (
            <>
              <TouchableOpacity style={styles.toggleRow} onPress={() => setShowMissing((v) => !v)} testID="roster-audit-missing-toggle">
                <Text style={styles.sectionWarn}>ON SHEET, NOT ON ROSTER · {report.missing.length}</Text>
                <Ionicons name={showMissing ? 'chevron-up' : 'chevron-down'} size={14} color={COLORS.textDim} />
              </TouchableOpacity>
              <Text style={styles.hint}>
                These people will sit on the pending screen after signing in. Add them
                with Add Person (needs their tier and upline — not guessed automatically).
              </Text>
              {showMissing ? report.missing.map((m) => (
                <View key={m.app_id} style={styles.row}>
                  <Text style={styles.name}>{m.name} <Text style={styles.dim}>· {m.app_id}</Text></Text>
                  <Text style={styles.meta}>{m.email}</Text>
                </View>
              )) : null}
            </>
          ) : null}

          {report.extra.length > 0 ? (
            <>
              <TouchableOpacity style={styles.toggleRow} onPress={() => setShowExtra((v) => !v)} testID="roster-audit-extra-toggle">
                <Text style={styles.sectionDim}>ON ROSTER, NOT ON SHEET · {report.extra.length}</Text>
                <Ionicons name={showExtra ? 'chevron-up' : 'chevron-down'} size={14} color={COLORS.textDim} />
              </TouchableOpacity>
              {showExtra ? report.extra.map((p) => (
                <View key={p.email || p.name} style={styles.row}>
                  <Text style={styles.name}>{p.name}</Text>
                  <Text style={styles.meta}>{p.email}</Text>
                </View>
              )) : null}
            </>
          ) : null}
        </View>
      ) : null}
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
  runBtn: { backgroundColor: COLORS.primary, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 12 },
  runTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  fixBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 12 },
  fixTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  summary: { color: COLORS.text, fontSize: 12, fontWeight: '700' },
  sectionBad: { color: COLORS.orange, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12 },
  sectionWarn: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12 },
  sectionDim: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  row: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, marginTop: 6, padding: 9 },
  name: { color: '#fff', fontWeight: '700', fontSize: 13 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  meta: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  clear: { color: COLORS.primary, fontSize: 12, marginTop: 10, fontWeight: '700' },
  hint: { color: COLORS.textMuted, fontSize: 11, marginTop: 4, fontStyle: 'italic' },
});
