// Admin Panel: "Announce" (owner, 2026-09-24; batch 2, PR B). An admin
// writes a What's New announcement — a short title that becomes the push,
// one to six cards — picks the audience, and sends. Creating it pushes to
// everyone in the audience immediately and shows the cards in the app on
// their next open, so a typed confirm stands between the button and the
// fleet. Past announcements list below with their push and text counts.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Switch } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS } from '../lib/auth';
import { notify } from '../lib/dialog';
import { TypedConfirm } from './TypedConfirm';
import { Announcement, AnnouncementCard } from './WhatsNewOverlay';

const MAX_CARDS = 6;
const emptyCard = (): AnnouncementCard => ({ heading: '', body: '' });

interface OfficeRow { office: string; agents: number }

export interface SmsLogRow {
  announcement_id: string;
  agent_id: string | null;
  name?: string | null;
  office?: string | null;
  to: string | null;
  status: 'sent' | 'error' | 'skipped';
  reason: string | null;
  ts: string;
}

export function AnnouncePanel() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [cards, setCards] = useState<AnnouncementCard[]>([emptyCard()]);
  const [scope, setScope] = useState<'agency' | 'office'>('agency');
  const [office, setOffice] = useState<string | null>(null);
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  const [smsAvailable, setSmsAvailable] = useState(false);
  const [sendSms, setSendSms] = useState(false);
  const [past, setPast] = useState<Announcement[]>([]);
  const [smsLog, setSmsLog] = useState<SmsLogRow[] | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [o, s, p] = await Promise.all([
        api<{ offices: OfficeRow[] }>('/api/admin/offices'),
        api<{ available: boolean }>('/api/announcements/sms-status'),
        api<{ announcements: Announcement[] }>('/api/admin/announcements'),
      ]);
      setOffices(o.offices);
      setSmsAvailable(s.available);
      setPast(p.announcements);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load announcements.');
    }
  }, []);

  const toggleLog = async () => {
    if (showLog) { setShowLog(false); return; }
    setShowLog(true);
    try {
      const r = await api<{ sms_log: SmsLogRow[] }>('/api/admin/sms-log');
      setSmsLog(r.sms_log);
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not load the text log.');
    }
  };

  useEffect(() => {
    if (!open) return;
    // Fetching when the panel opens, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [open, load]);

  const filled = cards.filter((c) => c.heading.trim() || c.body.trim());
  const valid = title.trim().length > 0 && title.trim().length <= 80
    && filled.length > 0 && filled.every((c) => c.heading.trim())
    && (scope === 'agency' || !!office);
  const recipients = scope === 'agency'
    ? offices.reduce((n, o) => n + o.agents, 0)
    : (offices.find((o) => o.office === office)?.agents ?? 0);

  const updateCard = (i: number, patch: Partial<AnnouncementCard>) =>
    setCards((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const send = async () => {
    setBusy(true);
    try {
      await api('/api/admin/announcements', {
        method: 'POST',
        body: JSON.stringify({
          title: title.trim(),
          cards: filled.map((c) => ({ heading: c.heading.trim(), body: c.body.trim() })),
          audience: scope === 'agency' ? { scope } : { scope, office },
          send_sms: sendSms && smsAvailable,
        }),
      });
      setConfirming(false);
      setTitle(''); setCards([emptyCard()]); setScope('agency'); setOffice(null); setSendSms(false);
      notify('Sent', 'The announcement is out. People see it the next time they open the app.');
      await load();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not send the announcement.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <TouchableOpacity style={styles.openBtn} onPress={() => setOpen(true)} testID="announce-open">
        <Ionicons name="megaphone-outline" size={16} color={COLORS.gold} />
        <Text style={styles.openTxt}>ANNOUNCE · WHAT&apos;S NEW</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.card} testID="announce-panel">
      <View style={styles.headRow}>
        <Text style={styles.title}>Announce</Text>
        <TouchableOpacity onPress={() => setOpen(false)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} testID="announce-close">
          <Ionicons name="close" size={20} color={COLORS.textDim} />
        </TouchableOpacity>
      </View>
      <Text style={styles.intro}>
        Everyone in the audience gets a push right away and sees these cards under WHAT&apos;S NEW the next time they open the app. Each person sees it once.
      </Text>

      <Text style={styles.lab}>TITLE · THIS IS THE PUSH NOTIFICATION</Text>
      <TextInput
        style={styles.input}
        value={title}
        onChangeText={setTitle}
        placeholder="e.g. Pick any date range on the Team tab"
        placeholderTextColor={COLORS.textMuted}
        maxLength={80}
        testID="announce-title"
      />

      {cards.map((c, i) => (
        <View key={i} style={styles.cardBox} testID={`announce-card-${i}`}>
          <View style={styles.headRow}>
            <Text style={styles.lab}>CARD {i + 1}</Text>
            {cards.length > 1 ? (
              <TouchableOpacity onPress={() => setCards((cs) => cs.filter((_, j) => j !== i))} testID={`announce-card-remove-${i}`}>
                <Text style={styles.removeTxt}>REMOVE</Text>
              </TouchableOpacity>
            ) : null}
          </View>
          <TextInput
            style={styles.input}
            value={c.heading}
            onChangeText={(v) => updateCard(i, { heading: v })}
            placeholder="Heading"
            placeholderTextColor={COLORS.textMuted}
            testID={`announce-card-heading-${i}`}
          />
          <TextInput
            style={[styles.input, styles.multiline]}
            value={c.body}
            onChangeText={(v) => updateCard(i, { body: v })}
            placeholder="What changed and what to do"
            placeholderTextColor={COLORS.textMuted}
            multiline
            testID={`announce-card-body-${i}`}
          />
        </View>
      ))}
      {cards.length < MAX_CARDS ? (
        <TouchableOpacity style={styles.addBtn} onPress={() => setCards((cs) => [...cs, emptyCard()])} testID="announce-card-add">
          <Ionicons name="add" size={16} color={COLORS.primary} />
          <Text style={styles.addTxt}>ADD A CARD</Text>
        </TouchableOpacity>
      ) : null}

      <Text style={styles.lab}>AUDIENCE</Text>
      <View style={styles.chipWrap}>
        <TouchableOpacity style={[styles.chip, scope === 'agency' && styles.chipOn]} onPress={() => { setScope('agency'); setOffice(null); }} testID="announce-scope-agency">
          <Text style={[styles.chipTxt, scope === 'agency' && styles.chipTxtOn]}>WHOLE AGENCY</Text>
        </TouchableOpacity>
        {offices.map((o) => (
          <TouchableOpacity
            key={o.office}
            style={[styles.chip, scope === 'office' && office === o.office && styles.chipOn]}
            onPress={() => { setScope('office'); setOffice(o.office); }}
            testID={`announce-office-${o.office}`}
          >
            <Text style={[styles.chipTxt, scope === 'office' && office === o.office && styles.chipTxtOn]}>{o.office} · {o.agents}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={[styles.switchRow, !smsAvailable && styles.dim]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.switchLab}>Also send a text message</Text>
          <Text style={styles.switchNote}>
            {smsAvailable
              ? 'Goes only to people who turned on text updates.'
              : 'Not available until the text-message service is set up.'}
          </Text>
        </View>
        <Switch
          value={sendSms && smsAvailable}
          onValueChange={setSendSms}
          disabled={!smsAvailable}
          trackColor={{ false: COLORS.surface2, true: COLORS.primary }}
          thumbColor="#fff"
          ios_backgroundColor={COLORS.surface2}
          testID="announce-sms"
        />
      </View>

      <TouchableOpacity
        style={[styles.sendBtn, (!valid || busy) && styles.sendBtnOff]}
        disabled={!valid || busy}
        onPress={() => setConfirming(true)}
        testID="announce-send"
      >
        <Text style={styles.sendTxt}>
          {valid ? `SEND TO ${recipients} ${recipients === 1 ? 'PERSON' : 'PEOPLE'}` : 'TITLE, ONE CARD AND AN AUDIENCE TO SEND'}
        </Text>
      </TouchableOpacity>

      <TypedConfirm
        visible={confirming}
        title="Send this announcement?"
        message={`A push goes to ${recipients} ${recipients === 1 ? 'person' : 'people'} now${sendSms && smsAvailable ? ', plus a text to everyone who opted in' : ''}. This cannot be recalled.`}
        word="SEND"
        confirmText="Send now"
        busy={busy}
        onCancel={() => setConfirming(false)}
        onConfirm={send}
      />

      {past.length ? (
        <>
          <Text style={styles.lab}>PAST ANNOUNCEMENTS</Text>
          {past.map((a) => (
            <View key={a.announcement_id} style={styles.pastRow} testID={`announce-past-${a.announcement_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.pastTitle}>{a.title}</Text>
                <Text style={styles.pastMeta}>
                  {new Date(a.created_at).toLocaleDateString()} · {a.audience.scope === 'agency' ? 'Whole agency' : a.audience.office} · {a.cards.length} {a.cards.length === 1 ? 'card' : 'cards'}
                </Text>
              </View>
              <Text style={styles.pastCounts}>{a.push_count ?? 0} push{(a.sms_count ?? 0) > 0 ? ` · ${a.sms_count} text` : ''}</Text>
            </View>
          ))}
        </>
      ) : null}

      <TouchableOpacity style={styles.logBtn} onPress={toggleLog} testID="announce-sms-log-toggle">
        <Text style={styles.logBtnTxt}>{showLog ? 'HIDE TEXT MESSAGE LOG' : 'SHOW TEXT MESSAGE LOG'}</Text>
      </TouchableOpacity>
      {showLog ? (
        smsLog === null ? null : smsLog.length === 0 ? (
          <Text style={styles.pastMeta} testID="announce-sms-log-empty">No text messages have been sent yet.</Text>
        ) : (
          smsLog.map((row, i) => (
            <View key={`${row.announcement_id}-${row.agent_id}-${i}`} style={styles.pastRow} testID={`announce-sms-log-${i}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.pastTitle}>{row.name || row.agent_id || 'Unknown'}{row.to ? ` · ${row.to}` : ''}</Text>
                <Text style={styles.pastMeta}>
                  {new Date(row.ts).toLocaleString()}{row.office ? ` · ${row.office}` : ''}{row.reason ? ` · ${row.reason}` : ''}
                </Text>
              </View>
              <Text style={[styles.pastCounts, row.status === 'sent' ? styles.logOk : styles.logBad]}>{row.status.toUpperCase()}</Text>
            </View>
          ))
        )
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  openBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.gold, padding: 12, borderRadius: 6, marginTop: 10 },
  openTxt: { color: COLORS.gold, fontWeight: '900', fontSize: 13, letterSpacing: 0.5 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 14, marginTop: 10 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: '#fff', fontWeight: '900', fontSize: 15 },
  intro: { color: COLORS.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 14, marginBottom: 6 },
  input: { backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10, color: '#fff', fontSize: 13, marginTop: 6 },
  multiline: { minHeight: 72, textAlignVertical: 'top' },
  cardBox: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, padding: 10, marginTop: 10 },
  removeTxt: { color: COLORS.red, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 14 },
  addBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, marginTop: 8 },
  addTxt: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 1 },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface2 },
  chipOn: { backgroundColor: COLORS.gold, borderColor: COLORS.gold },
  chipTxt: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  chipTxtOn: { color: '#000' },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 16 },
  dim: { opacity: 0.55 },
  switchLab: { color: '#fff', fontWeight: '800', fontSize: 13 },
  switchNote: { color: COLORS.textDim, fontSize: 11, marginTop: 2, lineHeight: 15 },
  sendBtn: { backgroundColor: COLORS.gold, alignItems: 'center', padding: 12, borderRadius: 6, marginTop: 16 },
  sendBtnOff: { opacity: 0.4 },
  sendTxt: { color: '#000', fontWeight: '900', fontSize: 13 },
  pastRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border },
  pastTitle: { color: '#fff', fontWeight: '700', fontSize: 13 },
  pastMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  pastCounts: { color: COLORS.textDim, fontSize: 11, fontWeight: '700' },
  logBtn: { alignItems: 'center', paddingVertical: 10, marginTop: 10 },
  logBtnTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 10, letterSpacing: 1.2 },
  logOk: { color: COLORS.primary },
  logBad: { color: COLORS.red },
});
