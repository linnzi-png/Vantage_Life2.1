// Code-date import — loads the RGA's roster workbook (Agent / Code Date /
// MGA Name) and sets each matched agent's code_date and rookie/veteran flag.
// Rookie = coded within the last 12 months, rolling (per owner, 2026-09-17).
// Admin Panel only; POST /api/admin/import-code-dates is gated server-side
// to is_admin and finance_admin.
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Switch, Platform,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { Ionicons } from '@expo/vector-icons';
import { apiUpload, COLORS } from '../lib/auth';
import { confirmAsync } from '../lib/dialog';

interface ImportResult {
  ok: boolean;
  dry_run: boolean;
  file: string;
  as_of: string;
  rows: number;
  matched: number;
  rookies: number;
  veterans: number;
  changed: number;
  unmatched: string[];
  ambiguous: string[];
  no_date: string[];
}

interface PickedFile {
  name: string;
  uri: string;
  file?: File; // web only — RN passes the uri through instead
}

const MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export function CodeDatesImport() {
  const [picked, setPicked] = useState<PickedFile | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pick = async () => {
    const res = await DocumentPicker.getDocumentAsync({
      multiple: false,
      copyToCacheDirectory: true,
      type: [MIME_XLSX, 'application/vnd.ms-excel.sheet.macroEnabled.12'],
    });
    if (res.canceled || !res.assets[0]) return;
    const a = res.assets[0];
    setPicked({ name: a.name, uri: a.uri, file: (a as { file?: File }).file });
    setResult(null);
    setError(null);
  };

  const run = async () => {
    if (!picked) return;
    setRunning(true);
    setError(null);
    try {
      const form = new FormData();
      if (Platform.OS === 'web') {
        const blob = picked.file ?? (await (await fetch(picked.uri)).blob());
        form.append('file', blob, picked.name);
      } else {
        form.append('file', { uri: picked.uri, name: picked.name, type: MIME_XLSX } as unknown as Blob);
      }
      form.append('dry_run', dryRun ? 'true' : 'false');
      setResult(await apiUpload<ImportResult>('/api/admin/import-code-dates', form));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setRunning(false);
    }
  };

  const confirmRun = async () => {
    if (!picked) return;
    if (dryRun) { run(); return; }
    const ok = await confirmAsync({
      title: 'Update rookie / veteran for real?',
      message: 'Every agent on the sheet gets their code date saved and their rookie or veteran status set from it. Agents not on the sheet are left as they are.',
      confirmText: 'Update',
    });
    if (ok) run();
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="code-dates-open">
        <Ionicons name="calendar-outline" size={16} color={COLORS.gold} />
        <Text style={styles.openTxt}>IMPORT CODE DATES (ROOKIE / VETERAN)</Text>
      </TouchableOpacity>
    );
  }

  const problems = result
    ? [...result.unmatched.map((n) => `${n} — not on the roster`),
       ...result.ambiguous.map((n) => `${n} — matches more than one agent`),
       ...result.no_date.map((n) => `${n} — no code date on the sheet`)]
    : [];

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>Import Code Dates</Text>
        <TouchableOpacity onPress={() => setOpen(false)} testID="code-dates-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Upload the RGA code-date workbook (a sheet with Agent and Code Date columns; the MGA tab
        is read too). Rookie means coded within the last 12 months — each agent flips to veteran on
        their one-year anniversary, so re-upload whenever the roster changes.
      </Text>

      <TouchableOpacity style={styles.pickBtn} onPress={pick} disabled={running} testID="code-dates-pick">
        <Ionicons name="document-attach-outline" size={16} color="#000" />
        <Text style={styles.pickTxt}>{picked ? picked.name.toUpperCase() : 'CHOOSE FILE'}</Text>
      </TouchableOpacity>

      <View style={styles.flagRow}>
        <View style={styles.flagLabels}>
          <Text style={styles.flagLab}>Preview only (dry run)</Text>
          <Text style={styles.flagHint}>Shows who matches and who would change without writing anything.</Text>
        </View>
        <Switch value={dryRun} onValueChange={setDryRun} disabled={running}
          trackColor={{ true: COLORS.primary, false: COLORS.surface2 }} />
      </View>

      <TouchableOpacity
        style={[styles.runBtn, (!picked || running) && styles.runBtnOff]}
        onPress={confirmRun}
        disabled={!picked || running}
        testID="code-dates-run"
      >
        {running ? <ActivityIndicator color="#000" /> : (
          <Text style={styles.runTxt}>{dryRun ? 'PREVIEW' : 'UPDATE FOR REAL'}</Text>
        )}
      </TouchableOpacity>

      {error ? <Text style={styles.err}>{error}</Text> : null}

      {result ? (
        <View style={styles.results}>
          <View style={styles.summary}>
            <Text style={styles.summaryTitle}>{result.dry_run ? 'PREVIEW' : 'UPDATED'} · AS OF {result.as_of}</Text>
            <Text style={styles.summaryTxt}>
              {result.matched} of {result.rows} rows matched an agent · {result.rookies} rookies · {result.veterans} veterans
              {result.changed ? ` · ${result.changed} status change${result.changed === 1 ? '' : 's'}` : ' · no status changes'}
            </Text>
          </View>
          {problems.length ? (
            <View style={styles.warn}>
              <Text style={styles.warnTitle}>NOT UPDATED — {problems.length}</Text>
              {problems.map((p) => <Text key={p} style={styles.warnRow}>• {p}</Text>)}
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
  err: { color: COLORS.red, fontSize: 12, marginTop: 10 },
  results: { marginTop: 16, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 12 },
  summary: { backgroundColor: COLORS.surface2, borderRadius: 6, padding: 10 },
  summaryTitle: { color: COLORS.gold, fontWeight: '900', fontSize: 10, letterSpacing: 1.2 },
  summaryTxt: { color: COLORS.text, fontSize: 12, marginTop: 4, lineHeight: 17 },
  warn: { borderWidth: 1, borderColor: COLORS.orange, borderRadius: 6, padding: 10, marginTop: 10 },
  warnTitle: { color: COLORS.orange, fontWeight: '900', fontSize: 10, letterSpacing: 1.2 },
  warnRow: { color: COLORS.text, fontSize: 12, marginTop: 4 },
});
