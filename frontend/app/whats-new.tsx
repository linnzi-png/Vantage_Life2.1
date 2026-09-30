// What's New history (owner, 2026-09-24; batch 2, PR B): every announcement
// in this person's audience, newest first, seen or not. Tapping one replays
// its cards in the same overlay the first-open pop-up uses, without
// touching the seen state.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS } from '../src/lib/auth';
import { LoadState } from '../src/components/LoadState';
import { Announcement, WhatsNewDeck } from '../src/components/WhatsNewOverlay';

export default function WhatsNewScreen() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Announcement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ announcements: Announcement[] }>('/api/announcements/history');
      setItems(r.announcements);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not load announcements.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetching on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  return (
    <View style={styles.root}>
      <Stack.Screen options={{ title: "WHAT'S NEW", headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.intro}>Every feature announcement sent to you, newest first. Tap one to see its cards again.</Text>
        <LoadState loading={loading} error={error} onRetry={load} isEmpty={items.length === 0} emptyText="No announcements yet." testID="whats-new-history">
          {items.map((a) => (
            <TouchableOpacity key={a.announcement_id} style={styles.row} onPress={() => setOpen(a)} testID={`whats-new-history-${a.announcement_id}`}>
              <Ionicons name="sparkles" size={16} color={COLORS.gold} />
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{a.title}</Text>
                <Text style={styles.rowMeta}>
                  {new Date(a.created_at).toLocaleDateString()} · {a.cards.length} {a.cards.length === 1 ? 'card' : 'cards'}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
            </TouchableOpacity>
          ))}
        </LoadState>
      </ScrollView>
      <Modal visible={!!open} transparent statusBarTranslucent animationType="fade" onRequestClose={() => setOpen(null)}>
        <View style={styles.backdrop}>
          {open ? <WhatsNewDeck key={open.announcement_id} announcement={open} onDone={() => setOpen(null)} doneLabel="CLOSE" /> : null}
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: 16, paddingBottom: 40 },
  intro: { color: COLORS.textDim, fontSize: 12, lineHeight: 17, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginBottom: 8 },
  rowTitle: { color: '#fff', fontWeight: '800', fontSize: 14 },
  rowMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.78)', alignItems: 'center', justifyContent: 'center', padding: 24 },
});
