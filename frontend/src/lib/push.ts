// Expo push token registration for the 9 PM escalation notifications.
// Best-effort throughout: a denied permission, a simulator with no push
// capability, or a network hiccup should never block sign-in or crash the
// app — the in-app GateBanner is still there as a fallback either way.
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { api } from './auth';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export async function registerForPulseNotifications(): Promise<void> {
  try {
    if (!Device.isDevice) return; // simulators/web have no real push capability

    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('pulse-escalation', {
        name: 'Nightly Pulse Reminders',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 250, 250, 250],
      });
    }

    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== 'granted') {
      const requested = await Notifications.requestPermissionsAsync();
      status = requested.status;
    }
    if (status !== 'granted') return;

    const projectId = Constants.expoConfig?.extra?.eas?.projectId;
    const { data: pushToken } = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );
    await api('/api/push/register', { method: 'POST', body: JSON.stringify({ push_token: pushToken }) });
  } catch {
    // Best-effort — the escalation banner in-app still works without push.
  }
}
