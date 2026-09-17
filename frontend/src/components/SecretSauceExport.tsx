// Morgans Secret Sauce — the one-sheet weekly recognition report (per owner,
// 2026-09-17): Top 4 Producers, Top Rookie Producers, Top Plus Lead Sales,
// Top Plus Leads Collected. Every office, agents and leaders together, one
// Wed-to-Tue week. Built from live production data, so any recent week works.
//
// One component, two homes: the Company Health screen and the More-tab Easter
// egg (/secret-sauce) for the accounts on SECRET_SAUCE_EMAILS. The server
// gates the download itself (RGA / admin / finance_admin).
//
// Web only, like the WAR workbooks: a binary file needs a real download.
import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { apiBlob, COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';

// "2026-06-10" -> "6/10"
const shortDate = (iso: string) => {
  const [, m, d] = iso.split('-');
  return `${Number(m)}/${Number(d)}`;
};

// The most recent `n` reporting-week starts (Wednesdays), newest first, as
// YYYY-MM-DD. Local calendar date is close enough for picking a week; the
// server does the real 6 AM / Wednesday bookkeeping.
export const recentWednesdays = (n: number): string[] => {
  const out: string[] = [];
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() - 3 + 7) % 7)); // back to Wednesday
  for (let i = 0; i < n; i++) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    out.push(`${y}-${m}-${day}`);
    d.setDate(d.getDate() - 7);
  }
  return out;
};

export function SecretSauceExport({ testID = 'secret-sauce' }: { testID?: string }) {
  const [week, setWeek] = useState<string>(() => recentWednesdays(8)[0]);
  const [busy, setBusy] = useState(false);

  const download = async () => {
    if (Platform.OS !== 'web' || typeof document === 'undefined') {
      notify('Open on the web', 'Morgans Secret Sauce downloads from the web app — the phone can only share text.');
      return;
    }
    setBusy(true);
    try {
      const blob = await apiBlob(`/api/vault/secret-sauce?week_start=${week}`);
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href; link.download = `${week}_Morgans_Secret_Sauce.xlsx`; link.click();
      URL.revokeObjectURL(href);
    } catch (e: unknown) {
      notify('Export failed', e instanceof Error ? e.message : 'Could not build the report.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} testID={testID}>
      <Text style={styles.kicker}>MORGANS SECRET SAUCE</Text>
      <Text style={styles.intro}>
        Top 4 Producers, Top Rookie Producers, Top Plus Lead Sales and Top Plus Leads Collected — every office, one sheet. Pick the week.
      </Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {recentWednesdays(8).map((w) => {
          const sel = w === week;
          return (
            <TouchableOpacity
              key={w}
              onPress={() => setWeek(w)}
              style={[styles.tab, sel && styles.tabOn]}
              testID={`${testID}-week-${w}`}
            >
              <Text style={[styles.tabTxt, sel && styles.tabTxtOn]}>WK OF {shortDate(w)}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
      <TouchableOpacity onPress={download} disabled={busy} style={styles.btn} testID={`${testID}-download`}>
        <Ionicons name="flame" size={14} color="#000" />
        <Text style={styles.btnTxt}>{busy ? 'BUILDING…' : 'MORGANS SECRET SAUCE'}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopWidth: 2, borderTopColor: COLORS.gold, borderRadius: 6, padding: 14, marginTop: 20 },
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  tabs: { gap: 6, paddingBottom: 4 },
  tab: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  tabOn: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  tabTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '800' },
  tabTxtOn: { color: '#fff' },
  btn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 12, backgroundColor: COLORS.gold, borderRadius: 6, paddingVertical: 10 },
  btnTxt: { color: '#000', fontSize: 11, fontWeight: '900', letterSpacing: 1.4 },
});
