// Persistent (but dismissible) nag shown whenever OS-level notification
// permission is off for a linked agent. VantageLife's 9 PM escalation and
// upline confirmation pushes both depend on this permission -- there is no
// in-app lockout tied to it (Apple's Guideline 4.5.4 forbids requiring push
// for an app to function), so this overlay is the legitimate lever instead:
// re-surfaced every time the app returns to the foreground until the person
// either enables notifications or the account is no longer linked.
import React, { useEffect, useRef, useState } from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity, Linking, AppState, AppStateStatus } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { COLORS, useAuth } from '../lib/auth';

export default function NotificationNagOverlay() {
  const { user } = useAuth();
  const [status, setStatus] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const appState = useRef<AppStateStatus>(AppState.currentState);

  const check = async () => {
    if (!Device.isDevice) return; // simulators/web have no real permission to check
    try {
      const result = await Notifications.getPermissionsAsync();
      setStatus(result.status);
    } catch {
      // Best-effort -- an unreadable permission state just skips the nag.
    }
  };

  useEffect(() => {
    // Reading the OS permission state, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (user?.agent_id) check();
  }, [user?.agent_id]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (appState.current.match(/inactive|background/) && next === 'active') {
        setDismissed(false); // re-arm every time the app comes back to the foreground
        check();
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, []);

  const visible = !!user?.agent_id && status !== null && status !== 'granted' && !dismissed;
  if (!visible) return null;

  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Ionicons name="notifications-off" size={32} color={COLORS.yellow} />
          <Text style={styles.title}>Notifications Are Off</Text>
          <Text style={styles.body}>
            VantageLife uses push notifications to remind you to log your Nightly Numbers
            and to confirm submissions with your upline. With notifications off, you won&apos;t
            get the 9 PM reminders and your upline won&apos;t be notified when you submit.
          </Text>
          <TouchableOpacity
            style={styles.enableBtn}
            activeOpacity={0.85}
            onPress={() => Linking.openSettings()}
          >
            <Text style={styles.enableTxt}>Enable in Settings</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.dismissBtn} activeOpacity={0.7} onPress={() => setDismissed(true)}>
            <Text style={styles.dismissTxt}>Not Now</Text>
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
  title: { color: COLORS.text, fontSize: 18, fontWeight: '800', letterSpacing: 0.2 },
  body: { color: COLORS.textDim, fontSize: 13, textAlign: 'center', lineHeight: 19 },
  enableBtn: {
    marginTop: 8,
    width: '100%',
    backgroundColor: COLORS.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  enableTxt: { color: '#FFFFFF', fontWeight: '700', fontSize: 14 },
  dismissBtn: { paddingVertical: 8 },
  dismissTxt: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
});
