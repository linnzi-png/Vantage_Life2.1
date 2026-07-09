// Premier Shoutouts Feed
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth } from '../../src/lib/auth';
import { NominateSheet } from '../../src/components/NominateSheet';
import { AgentContactSheet, AgentContact } from '../../src/components/AgentContactSheet';

interface Shoutout {
  shoutout_id: string;
  type: 'players_club' | 'first_deal' | 'streak' | 'platinum_rule' | string;
  scope: string;
  agent_id?: string;
  agent_name: string;
  office: string;
  sales_day?: string;
  amount?: number;
  streak?: number;
  reason?: string;
  nominator_name?: string;
  ts: string;
  role?: string;
  io_role?: string;
  phone?: string;
  email?: string;
}

const cfg: Record<string, { icon: any; color: string; title: string; bg: string }> = {
  players_club: { icon: 'trophy', color: COLORS.gold, title: "PLAYER'S CLUB", bg: 'rgba(255,215,0,0.08)' },
  first_deal: { icon: 'sparkles', color: COLORS.primary, title: 'WELCOME TO THE BOARD', bg: 'rgba(49,152,66,0.08)' },
  streak: { icon: 'flame', color: COLORS.orange, title: 'PERFORMANCE STREAK', bg: 'rgba(255,140,0,0.08)' },
  platinum_rule: { icon: 'medal', color: '#E5E4E2', title: 'PLATINUM RULE', bg: 'rgba(229,228,226,0.07)' },
};

export default function ShoutoutsScreen() {
  const { user } = useAuth();
  const [items, setItems] = useState<Shoutout[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [nominateOpen, setNominateOpen] = useState(false);
  const [contactAgent, setContactAgent] = useState<AgentContact | null>(null);
  const fetchAll = async () => {
    try { const r = await api<{ shoutouts: Shoutout[] }>('/api/shoutouts'); setItems(r.shoutouts); }
    catch {}
  };
  useEffect(() => { fetchAll(); const i = setInterval(fetchAll, 30000); return () => clearInterval(i); }, []);

  if (!user?.agent_id) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={36} color={COLORS.orange} />
          <Text style={styles.notLinked}>This account isn't linked to an agent profile yet.</Text>
          <Text style={styles.notLinkedSub}>Try the Demo Login screen and pick "AGENT" to test the Pulse flow.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={[styles.head, { flexDirection: 'row', alignItems: 'center' }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>VICTORY CULTURE</Text>
          <Text style={styles.title}>PREMIER SHOUTOUTS</Text>
        </View>
        <TouchableOpacity style={styles.nominateBtn} onPress={() => setNominateOpen(true)} testID="open-nominate">
          <Ionicons name="medal" size={14} color="#E5E4E2" />
          <Text style={styles.nominateTxt}>NOMINATE</Text>
        </TouchableOpacity>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 30 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); }} tintColor={COLORS.primary} />}
      >
        {items.length === 0 ? (
          <Text style={styles.empty}>No shoutouts yet — go close one.</Text>
        ) : items.map((s) => {
          const c = cfg[s.type] || { icon: 'megaphone', color: COLORS.text, title: s.type.toUpperCase(), bg: 'transparent' };
          return (
            <View key={s.shoutout_id} style={[styles.card, { borderTopColor: c.color, backgroundColor: c.bg }]} testID={`shoutout-${s.shoutout_id}`}>
              <View style={styles.iconWrap}>
                <Ionicons name={c.icon} size={20} color={c.color} />
              </View>
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={[styles.cardTitle, { color: c.color }]}>{c.title}</Text>
                <TouchableOpacity
                  onPress={() => setContactAgent({
                    name: s.agent_name, role: s.role || 'level_1', io_role: s.io_role,
                    phone: s.phone, email: s.email, office: s.office,
                  })}
                  activeOpacity={0.7}
                  testID={`shoutout-agent-${s.shoutout_id}`}
                >
                  <Text style={styles.agent}>{s.agent_name}<Text style={styles.dim}> · {s.office}</Text></Text>
                </TouchableOpacity>
                {s.type === 'players_club' && s.amount ? (
                  <Text style={styles.detail}>${Math.round(s.amount).toLocaleString()} Gross ALP — {s.sales_day}</Text>
                ) : null}
                {s.type === 'streak' && s.streak ? (
                  <Text style={styles.detail}>{s.streak} consecutive on-time pulses 🔥</Text>
                ) : null}
                {s.type === 'first_deal' ? (
                  <Text style={styles.detail}>Closed their first deal — visible to GA Team only.</Text>
                ) : null}
                {s.type === 'platinum_rule' && s.reason ? (
                  <Text style={[styles.detail, { fontStyle: 'italic' }]}>
                    "{s.reason}"{s.nominator_name ? ` — nominated by ${s.nominator_name}` : ''}
                  </Text>
                ) : null}
                <Text style={styles.ts}>{new Date(s.ts).toLocaleString()}</Text>
              </View>
            </View>
          );
        })}
      </ScrollView>
      <NominateSheet visible={nominateOpen} onClose={() => setNominateOpen(false)} onSubmitted={fetchAll} />
      <AgentContactSheet agent={contactAgent} onClose={() => setContactAgent(null)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  head: { paddingHorizontal: 16, paddingVertical: 12 },
  kicker: { color: COLORS.primary, fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  title: { color: '#fff', fontSize: 22, fontWeight: '900', letterSpacing: 0.5 },
  empty: { color: COLORS.textMuted, fontSize: 12, textAlign: 'center', marginTop: 24 },
  card: { flexDirection: 'row', borderWidth: 1, borderColor: COLORS.border, borderTopWidth: 3, borderRadius: 6, padding: 14, marginBottom: 10 },
  iconWrap: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontWeight: '900', fontSize: 11, letterSpacing: 1.5 },
  agent: { color: '#fff', fontWeight: '800', fontSize: 14, marginTop: 2 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  detail: { color: COLORS.textDim, fontSize: 12, marginTop: 4 },
  ts: { color: COLORS.textMuted, fontSize: 10, marginTop: 6 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  notLinked: { color: '#fff', fontWeight: '800', fontSize: 16, marginTop: 12, textAlign: 'center' },
  notLinkedSub: { color: COLORS.textDim, marginTop: 6, textAlign: 'center' },
  nominateBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    borderWidth: 1, borderColor: '#E5E4E2', borderRadius: 5,
    paddingHorizontal: 10, paddingVertical: 7, backgroundColor: 'rgba(229,228,226,0.08)',
  },
  nominateTxt: { color: '#E5E4E2', fontSize: 10, fontWeight: '900', letterSpacing: 1 },
});
