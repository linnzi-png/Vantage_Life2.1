// Platinum Rule nominations inbox — level_2+ endorse (SA is a level_2 title,
// so SA/GA/MGA/RGA); MGA/RGA post to the Platinum Wall.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Stack } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, useAuth, levelNum } from '../src/lib/auth';
import { SearchBar } from '../src/components/SearchBar';
import { TourAnchor } from '../src/components/TourAnchor';
import { AgentContactSheet, AgentContact } from '../src/components/AgentContactSheet';
import { confirmAsync, notify } from '../src/lib/dialog';

interface Endorsement { agent_id: string; name: string; ts: string; }
interface Nomination {
  nomination_id: string;
  nominee_name: string; nominee_office: string;
  nominee_role: string; nominee_io_role: string;
  nominee_phone: string; nominee_email: string;
  nominator_name: string;
  reason: string;
  status: 'open' | 'threshold_met' | 'posted' | string;
  endorsements: Endorsement[];
  created_at: string;
}

export default function NominationsScreen() {
  const { user } = useAuth();
  const lvl = levelNum(user?.role);
  const canEndorse = lvl >= 2;
  const [items, setItems] = useState<Nomination[]>([]);
  const [threshold, setThreshold] = useState(3);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [contactAgent, setContactAgent] = useState<AgentContact | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const r = await api<{ nominations: Nomination[]; threshold: number }>('/api/nominations');
      setItems(r.nominations);
      setThreshold(r.threshold);
    } catch {}
  }, []);

  useEffect(() => {
    // Fetching + polling an external API on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchAll();
    const i = setInterval(fetchAll, 30000);
    return () => clearInterval(i);
  }, [fetchAll]);

  const endorse = async (n: Nomination) => {
    setBusyId(n.nomination_id);
    try {
      await api(`/api/nominations/${n.nomination_id}/endorse`, { method: 'POST' });
      await fetchAll();
    } catch (e: any) {
      notify('Could not endorse', String(e?.message || e));
    } finally {
      setBusyId(null);
    }
  };

  const postToWall = async (n: Nomination) => {
    const ok = await confirmAsync({
      title: 'Post to Platinum Wall?',
      message: `Recognize ${n.nominee_name} for living the Platinum Rule. This appears org-wide.`,
      confirmText: 'Post it',
    });
    if (!ok) return;
    setBusyId(n.nomination_id);
    try {
      await api(`/api/nominations/${n.nomination_id}/post-to-wall`, { method: 'POST' });
      await fetchAll();
    } catch (e: any) {
      notify('Could not post', String(e?.message || e));
    } finally {
      setBusyId(null);
    }
  };

  if (!canEndorse) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <Stack.Screen options={{ title: 'NOMINATIONS' }} />
        <View style={styles.center}>
          <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
          <Text style={styles.emptyTxt}>The nominations inbox is for SA, GA, MGA, and RGA roles.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const iEndorsed = (n: Nomination) => n.endorsements.some((e) => e.agent_id === user?.agent_id);
  const q = query.trim().toLowerCase();
  const visible = q
    ? items.filter((n) => `${n.nominee_name} ${n.nominee_office} ${n.nominator_name} ${n.reason}`.toLowerCase().includes(q))
    : items;

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <Stack.Screen options={{ title: 'NOMINATIONS' }} />
      <View style={styles.head}>
        <Text style={styles.kicker}>PLATINUM RULE</Text>
        <Text style={styles.title}>NOMINATIONS</Text>
        <Text style={styles.sub}>{threshold} endorsements from leadership flag a nomination for the wall.</Text>
      </View>
      <TourAnchor id="noms-header">
        <SearchBar value={query} onChange={setQuery} placeholder="Search nominee, office, reason" testID="nominations-search" />
      </TourAnchor>
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await fetchAll(); setRefreshing(false); }} tintColor={COLORS.primary} />}
      >
        {visible.length === 0 ? (
          <Text style={styles.emptyTxt}>{q ? 'No matches for your search.' : 'No nominations for your team yet.'}</Text>
        ) : visible.map((n) => {
          const count = n.endorsements.length;
          const ready = n.status === 'threshold_met';
          const posted = n.status === 'posted';
          return (
            <View
              key={n.nomination_id}
              style={[styles.card, ready && styles.cardReady, posted && styles.cardPosted]}
              testID={`nomination-${n.nomination_id}`}
            >
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <TouchableOpacity
                  onPress={() => setContactAgent({
                    name: n.nominee_name, role: n.nominee_role || 'level_1', io_role: n.nominee_io_role,
                    phone: n.nominee_phone, email: n.nominee_email, office: n.nominee_office,
                  })}
                  activeOpacity={0.7}
                  testID={`nominee-contact-${n.nomination_id}`}
                >
                  <Text style={styles.nominee}>{n.nominee_name}</Text>
                </TouchableOpacity>
                <Text style={styles.office}> · {n.nominee_office}</Text>
                <View style={{ marginLeft: 'auto' }}>
                  {posted ? (
                    <View style={[styles.pill, { borderColor: COLORS.primary }]}>
                      <Text style={[styles.pillTxt, { color: COLORS.primary }]}>ON THE WALL</Text>
                    </View>
                  ) : (
                    <View style={[styles.pill, ready && { borderColor: '#E5E4E2' }]}>
                      <Text style={[styles.pillTxt, ready && { color: '#E5E4E2' }]}>{count}/{threshold}</Text>
                    </View>
                  )}
                </View>
              </View>
              <Text style={styles.reason}>&quot;{n.reason}&quot;</Text>
              <Text style={styles.meta}>
                Nominated by {n.nominator_name}
                {count > 0 ? ` · endorsed by ${n.endorsements.map((e) => e.name).join(', ')}` : ''}
              </Text>

              {!posted ? (
                <View style={styles.actions}>
                  <TouchableOpacity
                    style={[styles.btn, iEndorsed(n) && styles.btnDisabled]}
                    disabled={iEndorsed(n) || busyId === n.nomination_id}
                    onPress={() => endorse(n)}
                    testID={`endorse-${n.nomination_id}`}
                  >
                    <Ionicons name="thumbs-up" size={13} color={iEndorsed(n) ? COLORS.textMuted : COLORS.primary} />
                    <Text style={[styles.btnTxt, iEndorsed(n) && { color: COLORS.textMuted }]}>
                      {iEndorsed(n) ? 'ENDORSED' : 'ENDORSE'}
                    </Text>
                  </TouchableOpacity>
                  {lvl >= 3 && ready ? (
                    <TouchableOpacity
                      style={[styles.btn, styles.btnWall]}
                      disabled={busyId === n.nomination_id}
                      onPress={() => postToWall(n)}
                      testID={`post-${n.nomination_id}`}
                    >
                      <Ionicons name="medal" size={13} color="#000" />
                      <Text style={[styles.btnTxt, { color: '#000' }]}>POST TO PLATINUM WALL</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
      <AgentContactSheet agent={contactAgent} onClose={() => setContactAgent(null)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  head: { paddingHorizontal: 16, paddingVertical: 12 },
  kicker: { color: '#E5E4E2', fontSize: 11, fontWeight: '900', letterSpacing: 2 },
  title: { color: '#fff', fontSize: 22, fontWeight: '900' },
  sub: { color: COLORS.textDim, fontSize: 11, marginTop: 4 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  emptyTxt: { color: COLORS.textDim, marginTop: 12, textAlign: 'center' },
  card: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 6, padding: 14, marginBottom: 10,
  },
  cardReady: { borderColor: '#E5E4E2', borderLeftWidth: 3, borderLeftColor: '#E5E4E2' },
  cardPosted: { opacity: 0.7 },
  nominee: { color: '#fff', fontWeight: '800', fontSize: 15 },
  office: { color: COLORS.textDim, fontSize: 12 },
  reason: { color: '#fff', fontSize: 13, marginTop: 8, fontStyle: 'italic', lineHeight: 19 },
  meta: { color: COLORS.textMuted, fontSize: 11, marginTop: 8 },
  pill: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  pillTxt: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 12, flexWrap: 'wrap' },
  btn: {
    flexDirection: 'row', gap: 6, alignItems: 'center', borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 5, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: COLORS.surface2,
  },
  btnDisabled: { opacity: 0.6 },
  btnWall: { backgroundColor: '#E5E4E2', borderColor: '#E5E4E2' },
  btnTxt: { color: COLORS.primary, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
});
