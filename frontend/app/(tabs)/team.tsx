// Team View — Level 2+
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, levelNum, roleTitle } from '../../src/lib/auth';
import { AgentContactSheet, AgentContact, formatPhone } from '../../src/components/AgentContactSheet';

interface TeamRow {
  agent_id: string; name: string; office: string; role: string; io_role: string;
  phone: string; email: string; is_rookie: boolean;
  gross_alp: number; net_alp: number; sits: number; sales: number; close_ratio: number; avg_deal: number; alerts: string[];
}

const ALERT_LABELS: Record<string, { label: string; color: string }> = {
  low_close_ratio: { label: 'Low Close', color: COLORS.red },
  low_avg_deal:    { label: 'Low Avg',   color: COLORS.orange },
  no_pulse:        { label: 'No Pulse',  color: COLORS.yellow },
};

export default function TeamScreen() {
  const { user } = useAuth();
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [upline, setUpline] = useState<AgentContact | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sortKey, setSortKey] = useState<keyof TeamRow>('gross_alp');
  const [selected, setSelected] = useState<TeamRow | null>(null);
  const [uplineOpen, setUplineOpen] = useState(false);
  const [readyNoms, setReadyNoms] = useState(0);

  const fetchAll = async () => {
    try {
      const [r, u, n] = await Promise.all([
        api<{ team: TeamRow[] }>('/api/team'),
        api<{ upline: AgentContact | null }>('/api/my-upline').catch(() => ({ upline: null })),
        api<{ nominations: any[] }>('/api/nominations?status=threshold_met').catch(() => ({ nominations: [] })),
      ]);
      setRows(r.team);
      setUpline(u.upline);
      setReadyNoms(n.nominations.length);
    } catch {}
  };
  useEffect(() => { fetchAll(); const i = setInterval(fetchAll, 30000); return () => clearInterval(i); }, []);

  const sorted = [...rows].sort((a, b) => (Number(b[sortKey]) || 0) - (Number(a[sortKey]) || 0));

  if (levelNum(user?.role) < 2) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.empty}>
          <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
          <Text style={styles.emptyTxt}>Team View is for GA, MGA, and RGA roles.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const sortBtn = (key: keyof TeamRow, label: string) => (
    <TouchableOpacity
      onPress={() => setSortKey(key)}
      style={[styles.sortBtn, sortKey === key && styles.sortBtnActive]}
      testID={`team-sort-${key}`}
      hitSlop={{ top: 9, bottom: 9, left: 0, right: 0 }}
    >
      <Text style={[styles.sortTxt, sortKey === key && styles.sortTxtActive]}>{label}</Text>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={[styles.head, { flexDirection: 'row', alignItems: 'center' }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>HIERARCHY VIEW · LIVE</Text>
          <Text style={styles.title}>TEAM PRODUCTION</Text>
        </View>
        <TouchableOpacity style={styles.nomBtn} onPress={() => router.push('/nominations')} testID="open-nominations">
          <Ionicons name="medal" size={14} color="#E5E4E2" />
          <Text style={styles.nomBtnTxt}>NOMINATIONS</Text>
          {readyNoms > 0 ? (
            <View style={styles.badge} testID="nominations-badge">
              <Text style={styles.badgeTxt}>{readyNoms}</Text>
            </View>
          ) : null}
        </TouchableOpacity>
      </View>

      {upline && levelNum(user?.role) < 4 ? (
        <TouchableOpacity
          style={styles.uplineCard}
          onPress={() => setUplineOpen(true)}
          activeOpacity={0.75}
          testID="team-upline-card"
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.uplineKicker}>YOUR {roleTitle(upline.io_role, upline.role).toUpperCase()}</Text>
            <Text style={styles.uplineName}>{upline.name}</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            {upline.phone ? <Ionicons name="call" size={15} color={COLORS.primary} /> : null}
            {upline.phone ? <Ionicons name="chatbubble" size={15} color={COLORS.secondary} /> : null}
            <Ionicons name="chevron-forward" size={14} color={COLORS.textDim} />
          </View>
        </TouchableOpacity>
      ) : null}

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.sortBar}>
        {sortBtn('gross_alp', 'Gross ALP')}
        {sortBtn('net_alp', 'Net ALP')}
        {sortBtn('sales', 'Sales')}
        {sortBtn('close_ratio', 'Close %')}
        {sortBtn('avg_deal', 'Avg Deal')}
      </ScrollView>
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingTop: 4, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); }} tintColor={COLORS.primary} />}
      >
        {sorted.length === 0 ? (
          <Text style={styles.emptyTxt}>No team data yet.</Text>
        ) : sorted.map((r) => (
          <TouchableOpacity
            key={r.agent_id}
            style={styles.row}
            testID={`team-row-${r.agent_id}`}
            onPress={() => setSelected(r)}
            activeOpacity={0.75}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={styles.name} numberOfLines={1}>{r.name}</Text>
                {r.is_rookie ? <View style={styles.rookie}><Text style={styles.rookieTxt}>R</Text></View> : null}
                <Ionicons name="chevron-forward" size={12} color={COLORS.textDim} style={{ marginLeft: 'auto' }} />
              </View>
              <Text style={styles.meta}>
                {r.office} · {roleTitle(r.io_role, r.role) || r.role.replace('level_', 'L')}
                {r.phone ? ` · ${formatPhone(r.phone)}` : ''}
              </Text>
              {r.alerts?.length ? (
                <View style={{ flexDirection: 'row', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                  {r.alerts.map((a) => (
                    <View key={a} style={[styles.alert, { borderColor: ALERT_LABELS[a]?.color || COLORS.textDim }]}>
                      <Text style={[styles.alertTxt, { color: ALERT_LABELS[a]?.color || COLORS.textDim }]}>{ALERT_LABELS[a]?.label || a}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.alp}>${Math.round(r.gross_alp).toLocaleString()}</Text>
              <Text style={styles.metric}>{r.sales} sales · {r.close_ratio}%</Text>
              {Math.abs(r.gross_alp - r.net_alp) > 0.01 ? (
                <Text style={styles.netAlp}>NET ${Math.round(r.net_alp).toLocaleString()}</Text>
              ) : null}
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <AgentContactSheet agent={selected} onClose={() => setSelected(null)} />
      <AgentContactSheet agent={uplineOpen ? upline : null} onClose={() => setUplineOpen(false)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:          { flex: 1, backgroundColor: COLORS.bg },
  head:          { paddingHorizontal: 16, paddingVertical: 12 },
  kicker:        { color: COLORS.primary, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  title:         { color: '#fff', fontSize: 22, fontWeight: '900' },
  sortBar:       { gap: 6, paddingHorizontal: 16, paddingBottom: 8 },
  sortBtn:       { paddingHorizontal: 10, paddingVertical: 6, borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, backgroundColor: COLORS.surface },
  sortBtnActive: { borderColor: COLORS.primary, backgroundColor: 'rgba(49,152,66,0.12)' },
  sortTxt:       { color: COLORS.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  sortTxtActive: { color: COLORS.primary },
  empty:         { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  emptyTxt:      { color: COLORS.textDim, marginTop: 12, textAlign: 'center' },
  row:           { flexDirection: 'row', alignItems: 'flex-start', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, padding: 12, borderRadius: 6, marginBottom: 6 },
  name:          { color: '#fff', fontWeight: '800', fontSize: 14, flexShrink: 1 },
  meta:          { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  alp:           { color: COLORS.primary, fontWeight: '900', fontSize: 16, fontVariant: ['tabular-nums' as any] },
  metric:        { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  netAlp:        { color: COLORS.orange, fontSize: 10, fontWeight: '800', marginTop: 2, letterSpacing: 0.5 },
  alert:         { borderWidth: 1, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  alertTxt:      { fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  rookie:        { backgroundColor: COLORS.orange, paddingHorizontal: 4, borderRadius: 2 },
  rookieTxt:     { color: '#000', fontWeight: '900', fontSize: 9 },
  uplineCard:    {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginHorizontal: 16, marginBottom: 8,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderLeftWidth: 3, borderLeftColor: COLORS.primary,
    padding: 12, borderRadius: 6,
  },
  uplineKicker:  { color: COLORS.primary, fontSize: 9, fontWeight: '900', letterSpacing: 1.8, marginBottom: 2 },
  uplineName:    { color: '#fff', fontWeight: '800', fontSize: 14 },
  nomBtn:        {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    borderWidth: 1, borderColor: '#E5E4E2', borderRadius: 5,
    paddingHorizontal: 10, paddingVertical: 7, backgroundColor: 'rgba(229,228,226,0.08)',
  },
  nomBtnTxt:     { color: '#E5E4E2', fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  badge:         { backgroundColor: COLORS.red, borderRadius: 8, minWidth: 16, height: 16, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  badgeTxt:      { color: '#fff', fontSize: 9, fontWeight: '900' },
});
