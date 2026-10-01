// One-time text-message consent card (owner, 2026-09-24; batch 2, PR 0).
//
// Brevo's toll-free number registration wants a screenshot of an explicit,
// recorded opt-in, so this card has to be unmistakable to a reviewer who has
// never seen the app. It shows once, on the first open after this update
// (and on first sign-in for new people), only for someone with an agent
// profile that has a phone number and whose sms_consent has never been
// recorded, and never while the guided walkthrough is on screen or still
// deciding whether to launch — the tour wins and this card takes the next
// render. There is no "later": both buttons record an answer, so the card
// cannot come back. The More tab's switch changes the answer afterwards.
import React, { useState } from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, SmsConsent, useAuth } from '../lib/auth';
import { useTour } from '../lib/tour';
import { notify } from '../lib/dialog';

export const SMS_CONSENT_HEADING = 'TEXT MESSAGE UPDATES';
export const SMS_CONSENT_BODY =
  'VantageLife can text you when the app gets new features or important updates. ' +
  'Messages come from HyperVivid Studios on behalf of AO Premier. Message and data rates may apply. ' +
  'Message frequency varies, usually a few per month. You can turn texts off at any time in the More tab.';

export default function SmsConsentCard() {
  const { user, agent, loading, reload } = useAuth();
  const { active: tourActive, deciding: tourDeciding } = useTour();
  const [saving, setSaving] = useState<'yes' | 'no' | null>(null);
  // Hides the card the instant an answer is accepted, before reload() has
  // refreshed the agent, so it cannot flash back between the two. Keyed by
  // user_id: this component is mounted once in the root layout, so a plain
  // flag would survive a sign-out and hide the card from the next person
  // who signs in on the same running app.
  const [answeredFor, setAnsweredFor] = useState<string | null>(null);
  const answered = !!user && answeredFor === user.user_id;

  // No phone on the profile means nothing to consent to: the server refuses
  // an opt-in without one, so asking would only ever fail. The More tab
  // explains what to do instead.
  const hasPhone = !!agent?.phone?.trim();

  // A Financial Administrator has an agent profile (and often a phone) but
  // the server turns that role away from /api/me/sms-consent, so asking would
  // only ever end in a 403 popup. They are left out of the card entirely.
  const visible =
    !loading && !!user?.agent_id && user.role !== 'finance_admin' && !!agent && hasPhone
    && agent.sms_consent == null && !tourActive && !tourDeciding && !answered;
  if (!visible) return null;

  const answer = async (optedIn: boolean) => {
    if (saving) return;
    setSaving(optedIn ? 'yes' : 'no');
    try {
      await api<{ ok: boolean; sms_consent: SmsConsent }>('/api/me/sms-consent', {
        method: 'POST',
        body: JSON.stringify({ opted_in: optedIn, source: 'onboarding_card' }),
      });
      setAnsweredFor(user.user_id);
      await reload();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Could not save your choice. Try again.');
    } finally {
      setSaving(null);
    }
  };

  // onRequestClose (Android back) does nothing on purpose: the card needs an
  // answer, and both answers are one tap away.
  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent onRequestClose={() => {}}>
      <View style={styles.backdrop}>
        <View style={styles.card} testID="sms-consent-card">
          <Ionicons name="chatbubble-ellipses" size={32} color={COLORS.gold} />
          <Text style={styles.heading}>{SMS_CONSENT_HEADING}</Text>
          <Text style={styles.body}>{SMS_CONSENT_BODY}</Text>
          <TouchableOpacity
            style={[styles.yesBtn, saving && styles.btnBusy]}
            activeOpacity={0.85}
            disabled={!!saving}
            onPress={() => answer(true)}
            testID="sms-consent-yes"
          >
            {saving === 'yes' ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.yesTxt}>YES, TEXT ME</Text>}
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.noBtn, saving && styles.btnBusy]}
            activeOpacity={0.7}
            disabled={!!saving}
            onPress={() => answer(false)}
            testID="sms-consent-no"
          >
            {saving === 'no' ? <ActivityIndicator color={COLORS.textDim} /> : <Text style={styles.noTxt}>NO THANKS</Text>}
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.75)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: COLORS.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: 24,
    alignItems: 'center',
    gap: 12,
  },
  heading: { color: COLORS.text, fontSize: 18, fontWeight: '900', letterSpacing: 1.2 },
  body: { color: COLORS.textDim, fontSize: 13, textAlign: 'center', lineHeight: 19 },
  yesBtn: {
    marginTop: 8,
    width: '100%',
    backgroundColor: COLORS.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: 'center',
  },
  yesTxt: { color: '#FFFFFF', fontWeight: '800', fontSize: 14, letterSpacing: 0.8 },
  noBtn: {
    width: '100%',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: COLORS.border,
    paddingVertical: 12,
    alignItems: 'center',
  },
  noTxt: { color: COLORS.textDim, fontWeight: '700', fontSize: 13, letterSpacing: 0.8 },
  btnBusy: { opacity: 0.6 },
});
