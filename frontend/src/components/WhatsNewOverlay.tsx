// WHAT'S NEW (owner, 2026-09-24; batch 2, PR B). An admin posts an
// announcement from the Admin Panel; the next time each person opens the
// app this overlay walks them through its cards, once, in the guided
// walkthrough's visual style. Seen state lives on the server
// (announcement_seen), so a second device does not repeat it. If nothing
// is unseen, nothing shows. It never shares the screen with the tour: on
// a first sign-in the tour goes first and this waits for the next open.
//
// Also used by the More tab's What's New history, which hands it a single
// announcement to replay without marking anything seen.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { api, COLORS, useAuth } from '../lib/auth';
import { useTour } from '../lib/tour';

export interface AnnouncementCard { heading: string; body: string }
export interface Announcement {
  announcement_id: string;
  title: string;
  cards: AnnouncementCard[];
  audience: { scope: 'agency' | 'office'; office?: string };
  created_at: string;
  created_by_name?: string | null;
  push_count?: number;
  sms_count?: number;
}

/** The card deck for one announcement. Pure presentation; the two hosts
 *  below decide when it shows and what "done" means. */
export function WhatsNewDeck({ announcement, onDone, doneLabel = 'DONE' }: {
  announcement: Announcement;
  onDone: () => void;
  doneLabel?: string;
}) {
  const [index, setIndex] = useState(0);
  const cards = announcement.cards.length ? announcement.cards : [{ heading: announcement.title, body: '' }];
  const card = cards[Math.min(index, cards.length - 1)];
  const isLast = index >= cards.length - 1;
  return (
    <View style={styles.card} testID="whats-new-card">
      <Text style={styles.banner}>WHAT&apos;S NEW</Text>
      <Text style={styles.title}>{announcement.title}</Text>
      <View style={styles.dots}>
        {cards.map((_, i) => <View key={i} style={[styles.dot, i === index && styles.dotOn]} />)}
      </View>
      <ScrollView style={styles.scroll} contentContainerStyle={{ paddingBottom: 4 }}>
        <Text style={styles.heading}>{card.heading}</Text>
        {card.body ? <Text style={styles.body}>{card.body}</Text> : null}
      </ScrollView>
      <View style={styles.btnRow}>
        {index > 0 ? (
          <TouchableOpacity style={[styles.btn, styles.btnGhost]} onPress={() => setIndex((i) => Math.max(i - 1, 0))} testID="whats-new-back">
            <Text style={styles.btnGhostTxt}>BACK</Text>
          </TouchableOpacity>
        ) : <View style={{ flex: 1 }} />}
        <TouchableOpacity
          style={[styles.btn, styles.btnPrimary]}
          onPress={() => (isLast ? onDone() : setIndex((i) => i + 1))}
          testID="whats-new-next"
        >
          <Text style={styles.btnPrimaryTxt}>{isLast ? doneLabel : 'NEXT'}</Text>
        </TouchableOpacity>
      </View>
      {!isLast ? (
        <TouchableOpacity onPress={onDone} style={styles.skipBtn} testID="whats-new-skip">
          <Text style={styles.skipTxt}>SKIP</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

/** Root-layout host: fetches unseen announcements after auth resolves and
 *  shows them one after the other, newest first, marking each seen. */
export default function WhatsNewOverlay() {
  const { user, loading } = useAuth();
  const { active: tourActive, deciding: tourDeciding } = useTour();
  // The queue is tagged with the identity it was fetched for, so a sign-out
  // (or a different person signing in) makes it stale without an effect:
  // a stale queue reads as empty and the fetch re-arms for the new identity.
  const [fetched, setFetched] = useState<{ identity: string; queue: Announcement[] } | null>(null);
  // One in-flight or completed fetch per identity per app open.
  const fetchedFor = useRef<string | null>(null);

  const identity = user?.user_id ?? null;
  const ready = !loading && !!identity && !tourActive && !tourDeciding;

  useEffect(() => {
    if (!ready || !identity || fetchedFor.current === identity) return;
    fetchedFor.current = identity;
    let stale = false;
    api<{ announcements: Announcement[] }>('/api/announcements/unseen')
      .then((r) => { if (!stale) setFetched({ identity, queue: r.announcements }); })
      .catch(() => { /* nothing to show is the right outcome when this fails */ });
    return () => { stale = true; };
  }, [ready, identity]);

  // A sign-out re-arms the fetch for whoever signs in next. The queue needs
  // no reset: it is tagged with the identity it belongs to (below).
  useEffect(() => {
    if (!identity) fetchedFor.current = null;
  }, [identity]);

  const queue = fetched && fetched.identity === identity ? fetched.queue : [];
  const current = queue[0];
  const dismiss = useCallback(() => {
    if (!current) return;
    api(`/api/announcements/${encodeURIComponent(current.announcement_id)}/seen`, { method: 'POST' }).catch(() => {});
    setFetched((f) => (f ? { ...f, queue: f.queue.slice(1) } : f));
  }, [current]);

  if (!ready || !current) return null;
  return (
    <Modal visible transparent statusBarTranslucent animationType="fade" onRequestClose={dismiss}>
      <View style={styles.backdrop} testID="whats-new-overlay">
        <WhatsNewDeck key={current.announcement_id} announcement={current} onDone={dismiss} />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.78)', alignItems: 'center', justifyContent: 'center', padding: 24 },
  card: {
    width: '100%',
    maxWidth: 380,
    maxHeight: '80%',
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderTopWidth: 3,
    borderTopColor: COLORS.gold,
    borderRadius: 6,
    padding: 18,
  },
  banner: { color: COLORS.gold, fontSize: 26, fontWeight: '900', letterSpacing: 3, textAlign: 'center' },
  title: { color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'center', marginTop: 6, letterSpacing: 0.4 },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 12 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: COLORS.border },
  dotOn: { backgroundColor: COLORS.gold, width: 16 },
  scroll: { marginTop: 14, flexGrow: 0 },
  heading: { color: '#fff', fontSize: 17, fontWeight: '900', letterSpacing: 0.3 },
  body: { color: COLORS.textDim, fontSize: 13, lineHeight: 19, marginTop: 8 },
  btnRow: { flexDirection: 'row', gap: 8, marginTop: 16 },
  btn: { flex: 1, paddingVertical: 12, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryTxt: { color: '#000', fontWeight: '900', letterSpacing: 1 },
  btnGhost: { borderWidth: 1, borderColor: COLORS.border },
  btnGhostTxt: { color: COLORS.textDim, fontWeight: '900', letterSpacing: 1 },
  skipBtn: { alignSelf: 'center', marginTop: 12, paddingHorizontal: 8, paddingVertical: 2 },
  skipTxt: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.5 },
});
