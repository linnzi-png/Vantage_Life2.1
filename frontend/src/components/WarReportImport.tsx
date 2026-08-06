// WAR report import — in-app replacement for the terminal backfill script.
// Admin screen only; every upload goes through POST /api/admin/import-war-report,
// which is gated by require_admin server-side.
import React, { useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Alert, ActivityIndicator, Switch, Platform,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { Ionicons } from '@expo/vector-icons';
import { apiUpload, COLORS } from '../lib/auth';

interface UnmatchedAgent {
  name: string;
  mga?: string | null;
  ga?: string | null;
  sa?: string | null;
  state?: string | null;
  rows: number;
}

interface ImportResult {
  ok: boolean;
  dry_run: boolean;
  file: string;
  office: string;
  week_start: string;
  days: string[];
  inserted: number;
  replaced: number;
  protected: number;
  skipped_unmatched: number;
  created_agents: string[];
  unmatched: UnmatchedAgent[];
}

interface PickedFile {
  name: string;
  uri: string;
  file?: File; // web only — RN passes the uri through instead
}

interface RowState {
  name: string;
  status: 'pending' | 'running' | 'done' | 'error';
  result?: ImportResult;
  error?: string;
}

const MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export function WarReportImport() {
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [rows, setRows] = useState<RowState[]>([]);
  const [dryRun, setDryRun] = useState(true);
  const [createMissing, setCreateMissing] = useState(false);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState(false);

  const pick = async () => {
    const res = await DocumentPicker.getDocumentAsync({
      multiple: true,
      copyToCacheDirectory: true,
      type: [MIME_XLSX, 'application/vnd.ms-excel.sheet.macroEnabled.12'],
    });
    if (res.canceled) return;
    // Chronological order is not cosmetic: each report shares two sales days
    // with the following week's, and the later file is authoritative. Uploading
    // out of order would let a stale value overwrite a correction.
    const picked = res.assets
      .map((a) => ({ name: a.name, uri: a.uri, file: (a as { file?: File }).file }))
      .sort((a, b) => a.name.localeCompare(b.name));
    setFiles(picked);
    setRows(picked.map((f) => ({ name: f.name, status: 'pending' as const })));
  };

  const runImport = async () => {
    setRunning(true);
    setRows(files.map((f) => ({ name: f.name, status: 'pending' as const })));
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, status: 'running' } : r)));
      try {
        const form = new FormData();
        if (Platform.OS === 'web') {
          // On web the picker hands back a real File object.
          const blob = f.file ?? (await (await fetch(f.uri)).blob());
          form.append('file', blob, f.name);
        } else {
          // React Native's FormData takes a {uri,name,type} descriptor.
          form.append('file', {
            uri: f.uri, name: f.name, type: MIME_XLSX,
          } as unknown as Blob);
        }
        form.append('dry_run', dryRun ? 'true' : 'false');
        form.append('create_missing', createMissing ? 'true' : 'false');

        const result = await apiUpload<ImportResult>('/api/admin/import-war-report', form);
        setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, status: 'done', result } : r)));
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Upload failed';
        setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, status: 'error', error: msg } : r)));
      }
    }
    setRunning(false);
  };

  const confirmRun = () => {
    if (!files.length) return;
    if (dryRun) { runImport(); return; }
    Alert.alert(
      'Import for real?',
      `${files.length} report(s) will be written to production data. Entries agents submitted in the app are never overwritten.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Import', onPress: runImport },
      ],
    );
  };

  const totals = useMemo(() => {
    const done = rows.filter((r) => r.result);
    return {
      files: done.length,
      inserted: done.reduce((n, r) => n + (r.result?.inserted ?? 0), 0),
      replaced: done.reduce((n, r) => n + (r.result?.replaced ?? 0), 0),
      protectedCount: done.reduce((n, r) => n + (r.result?.protected ?? 0), 0),
      skipped: done.reduce((n, r) => n + (r.result?.skipped_unmatched ?? 0), 0),
      errors: rows.filter((r) => r.status === 'error').length,
    };
  }, [rows]);

  const unmatchedNames = useMemo(() => {
    const seen = new Map<string, UnmatchedAgent>();
    rows.forEach((r) => r.result?.unmatched.forEach((u) => {
      const prev = seen.get(u.name);
      seen.set(u.name, prev ? { ...prev, rows: prev.rows + u.rows } : u);
    }));
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [rows]);

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="war-import-open">
        <Ionicons name="cloud-upload-outline" size={16} color={COLORS.gold} />
        <Text style={styles.openTxt}>IMPORT WAR REPORTS</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Import War Reports</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="war-import-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Upload weekly WAR spreadsheets. Files must be named with the week&apos;s Wednesday
        (e.g. 2026-02-18_MJ_War_Report.xlsx). Reports overlap by two days — the later
        file wins, so pick them all at once and they upload in date order.
      </Text>

      <TouchableOpacity style={styles.pickBtn} onPress={pick} disabled={running} testID="war-import-pick">
        <Ionicons name="document-attach-outline" size={16} color="#000" />
        <Text style={styles.pickTxt}>
          {files.length ? `${files.length} FILE${files.length === 1 ? '' : 'S'} SELECTED` : 'CHOOSE FILES'}
        </Text>
      </TouchableOpacity>

      <View style={styles.flagRow}>
        <View style={styles.flagLabels}>
          <Text style={styles.flagLab}>Preview only (dry run)</Text>
          <Text style={styles.flagHint}>Shows what would change without writing anything.</Text>
        </View>
        <Switch
          value={dryRun}
          onValueChange={setDryRun}
          disabled={running}
          trackColor={{ true: COLORS.primary, false: COLORS.surface2 }}
        />
      </View>
      <View style={styles.flagRow}>
        <View style={styles.flagLabels}>
          <Text style={styles.flagLab}>Create agents not on the roster</Text>
          <Text style={styles.flagHint}>
            Off by default. Agents created here have no upline, so they stay invisible in
            team rollups until you set one — prefer adding them via Add Person.
          </Text>
        </View>
        <Switch
          value={createMissing}
          onValueChange={setCreateMissing}
          disabled={running}
          trackColor={{ true: COLORS.orange, false: COLORS.surface2 }}
        />
      </View>

      <TouchableOpacity
        style={[styles.runBtn, (!files.length || running) && styles.runBtnOff]}
        onPress={confirmRun}
        disabled={!files.length || running}
        testID="war-import-run"
      >
        {running ? <ActivityIndicator color="#000" /> : (
          <Text style={styles.runTxt}>{dryRun ? 'PREVIEW IMPORT' : 'IMPORT FOR REAL'}</Text>
        )}
      </TouchableOpacity>

      {rows.length ? (
        <View style={styles.results}>
          {rows.map((r) => (
            <View key={r.name} style={styles.resultRow}>
              <Ionicons
                name={r.status === 'done' ? 'checkmark-circle' : r.status === 'error' ? 'alert-circle' : r.status === 'running' ? 'time-outline' : 'ellipse-outline'}
                size={14}
                color={r.status === 'done' ? COLORS.primary : r.status === 'error' ? COLORS.red : COLORS.textMuted}
              />
              <View style={styles.resultBody}>
                <Text style={styles.resultName}>{r.name}</Text>
                {r.result ? (
                  <Text style={styles.resultMeta}>
                    {r.result.inserted} new · {r.result.replaced} updated
                    {r.result.protected ? ` · ${r.result.protected} protected` : ''}
                    {r.result.skipped_unmatched ? ` · ${r.result.skipped_unmatched} skipped` : ''}
                  </Text>
                ) : null}
                {r.error ? <Text style={styles.resultErr}>{r.error}</Text> : null}
              </View>
            </View>
          ))}

          {totals.files ? (
            <View style={styles.summary}>
              <Text style={styles.summaryTitle}>
                {rows.some((r) => r.result?.dry_run) ? 'PREVIEW TOTAL' : 'IMPORTED'}
              </Text>
              <Text style={styles.summaryTxt}>
                {totals.inserted} entries added · {totals.replaced} updated by a later report
                {totals.protectedCount ? ` · ${totals.protectedCount} agent-submitted left untouched` : ''}
                {totals.skipped ? ` · ${totals.skipped} skipped (agent not on roster)` : ''}
                {totals.errors ? ` · ${totals.errors} file(s) failed` : ''}
              </Text>
            </View>
          ) : null}

          {unmatchedNames.length ? (
            <View style={styles.warn}>
              <Text style={styles.warnTitle}>NOT ON THE ROSTER — {unmatchedNames.length} AGENT(S)</Text>
              <Text style={styles.warnHint}>
                Their rows were skipped. Add them via Add Person (with the right upline), then re-run.
              </Text>
              {unmatchedNames.map((u) => (
                <Text key={u.name} style={styles.warnRow}>
                  • {u.name}{u.ga ? ` — under ${u.ga}` : u.mga ? ` — under ${u.mga}` : ''} ({u.rows} day{u.rows === 1 ? '' : 's'})
                </Text>
              ))}
            </View>
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
  pickBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.primary, padding: 12, borderRadius: 6, marginTop: 12 },
  pickTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  flagRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 14 },
  flagLabels: { flex: 1 },
  flagLab: { color: '#fff', fontSize: 13, fontWeight: '600' },
  flagHint: { color: COLORS.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  runBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 16 },
  runBtnOff: { opacity: 0.4 },
  runTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  results: { marginTop: 16, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 12 },
  resultRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginBottom: 8 },
  resultBody: { flex: 1 },
  resultName: { color: COLORS.text, fontSize: 12, fontWeight: '600' },
  resultMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 1 },
  resultErr: { color: COLORS.red, fontSize: 11, marginTop: 1 },
  summary: { backgroundColor: COLORS.surface2, borderRadius: 6, padding: 10, marginTop: 6 },
  summaryTitle: { color: COLORS.gold, fontWeight: '900', fontSize: 10, letterSpacing: 1.2 },
  summaryTxt: { color: COLORS.text, fontSize: 12, marginTop: 4, lineHeight: 17 },
  warn: { borderWidth: 1, borderColor: COLORS.orange, borderRadius: 6, padding: 10, marginTop: 10 },
  warnTitle: { color: COLORS.orange, fontWeight: '900', fontSize: 10, letterSpacing: 1.2 },
  warnHint: { color: COLORS.textDim, fontSize: 11, marginTop: 4, lineHeight: 15 },
  warnRow: { color: COLORS.text, fontSize: 12, marginTop: 4 },
});
