// Historical Vault — Week comparison (Level 4 only)
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform, Share, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS } from '../src/lib/auth';
import { TourAnchor } from '../src/components/TourAnchor';

interface Week { week_id: string; week_start: string; archived_at: string; totals: any; agent_count: number; }

export default function VaultScreen() {
  const [weeks, setWeeks] = useState<Week[]>([]);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [cmp, setCmp] = useState<any>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  useEffect(() => { (async () => { try { const r = await api<{ weeks: Week[] }>('/api/vault/weeks'); setWeeks(r.weeks); } catch {} })(); }, []);

  // Export a week as the WAR-format JSON backup — round-trips through the
  // importer. On web it downloads; on native it opens the share sheet.
  const exportWeek = async (weekStart: string) => {
    setExporting(weekStart);
    try {
      const data = await api<any>(`/api/vault/export?week_start=${weekStart}`);
      const json = JSON.stringify(data, null, 2);
      const filename = `war_export_${weekStart}.json`;
      if (Platform.OS === 'web' && typeof document !== 'undefined') {
        const href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
        const link = document.createElement('a');
        link.href = href; link.download = filename; link.click();
        URL.revokeObjectURL(href);
      } else {
        await Share.share({ message: json, title: filename });
      }
    } catch (e: any) {
      Alert.alert('Export failed', e?.message || 'Could not export this week.');
    } finally {
      setExporting(null);
    }
  };

  useEffect(() => {
    if (a && b && a !== b) {
      api<any>(`/api/vault/compare?week_a=${a}&week_b=${b}`).then(setCmp).catch(() => setCmp(null));
    } else { setCmp(null); }
  }, [a, b]);

  const fmt = (n: number) => `$${Math.round(n).toLocaleString()}`;

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'HISTORICAL VAULT', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 30 }}>
        <TourAnchor id="vault-weeks">
          <Text style={styles.kicker}>LAST 8 ARCHIVED WEEKS</Text>
          <Text style={styles.intro}>Pick two weeks to compare side-by-side with delta percentages.</Text>
        </TourAnchor>

        <View style={styles.weekGrid}>
          {weeks.map((w) => {
            const isA = a === w.week_start; const isB = b === w.week_start;
            return (
              <TouchableOpacity
                key={w.week_id}
                onPress={() => {
                  if (isA) setA(null);
                  else if (isB) setB(null);
                  else if (!a) setA(w.week_start);
                  else if (!b) setB(w.week_start);
                  else setA(w.week_start); // replace A
                }}
                style={[styles.weekCard, (isA || isB) && { borderColor: isA ? COLORS.primary : COLORS.gold, borderWidth: 2 }]}
                testID={`vault-week-${w.week_start}`}
              >
                {isA ? <View style={[styles.tag, { backgroundColor: COLORS.primary }]}><Text style={styles.tagTxt}>A</Text></View> : null}
                {isB ? <View style={[styles.tag, { backgroundColor: COLORS.gold }]}><Text style={styles.tagTxt}>B</Text></View> : null}
                <Text style={styles.weekDate}>{w.week_start}</Text>
                <Text style={styles.weekAlp}>{fmt(w.totals?.gross_alp || 0)}</Text>
                <Text style={styles.weekMeta}>{w.totals?.sales || 0} sales · {w.agent_count} agents</Text>
                <TouchableOpacity
                  onPress={() => exportWeek(w.week_start)}
                  disabled={exporting === w.week_start}
                  style={styles.exportBtn}
                  testID={`vault-export-${w.week_start}`}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                >
                  <Ionicons name="download-outline" size={12} color={COLORS.primary} />
                  <Text style={styles.exportTxt}>{exporting === w.week_start ? 'EXPORTING…' : 'EXPORT'}</Text>
                </TouchableOpacity>
              </TouchableOpacity>
            );
          })}
        </View>

        {cmp ? (
          <View style={styles.compareCard} testID="vault-compare">
            <Text style={styles.kicker}>WEEK COMPARISON</Text>
            <View style={styles.cmpHeader}>
              <Text style={[styles.cmpCol, { color: COLORS.primary }]}>A · {cmp.a.week_start}</Text>
              <Text style={[styles.cmpCol, { color: COLORS.gold, textAlign: 'right' }]}>B · {cmp.b.week_start}</Text>
            </View>
            {(['gross_alp', 'net_alp', 'sales', 'sits'] as const).map((m) => {
              const d = cmp.delta[m];
              const pos = d.delta >= 0;
              const isMoney = m === 'gross_alp' || m === 'net_alp';
              return (
                <View key={m} style={styles.cmpRow}>
                  <Text style={styles.cmpLab}>{m.replace('_', ' ').toUpperCase()}</Text>
                  <View style={styles.cmpValues}>
                    <Text style={styles.cmpAVal}>{isMoney ? fmt(d.a) : Math.round(d.a).toLocaleString()}</Text>
                    <View style={[styles.deltaPill, { backgroundColor: pos ? 'rgba(49,152,66,0.15)' : 'rgba(255,59,48,0.15)' }]}>
                      <Ionicons name={pos ? 'arrow-up' : 'arrow-down'} size={11} color={pos ? COLORS.primary : COLORS.red} />
                      <Text style={[styles.deltaPillTxt, { color: pos ? COLORS.primary : COLORS.red }]}>{pos ? '+' : ''}{d.pct.toFixed(1)}%</Text>
                    </View>
                    <Text style={styles.cmpBVal}>{isMoney ? fmt(d.b) : Math.round(d.b).toLocaleString()}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  weekGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  weekCard: { width: '48%', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 12 },
  weekDate: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  weekAlp: { color: '#fff', fontSize: 18, fontWeight: '900', marginTop: 4 },
  weekMeta: { color: COLORS.textMuted, fontSize: 10, marginTop: 2 },
  exportBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8, alignSelf: 'flex-start', borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 5 },
  exportTxt: { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  tag: { position: 'absolute', top: 6, right: 6, width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  tagTxt: { color: '#000', fontWeight: '900', fontSize: 11 },
  compareCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopWidth: 2, borderTopColor: COLORS.primary, borderRadius: 6, padding: 14, marginTop: 16 },
  cmpHeader: { flexDirection: 'row', justifyContent: 'space-between', marginVertical: 8 },
  cmpCol: { fontWeight: '900', fontSize: 11, letterSpacing: 1, flex: 1 },
  cmpRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  cmpLab: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  cmpValues: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, gap: 6 },
  cmpAVal: { color: '#fff', fontWeight: '900', fontSize: 13, flex: 1 },
  cmpBVal: { color: '#fff', fontWeight: '900', fontSize: 13, flex: 1, textAlign: 'right' },
  deltaPill: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12 },
  deltaPillTxt: { fontWeight: '900', fontSize: 11 },
});
