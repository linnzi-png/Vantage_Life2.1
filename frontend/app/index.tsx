// Auth gate: redirects to login or tabs based on session
import React, { useEffect } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth, COLORS } from '../src/lib/auth';

export default function Index() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (user && user.role === 'pending') router.replace('/pending');
    // Financial Admin has no production identity — it skips Pulse entry and
    // the rest of the tab bar entirely, landing straight on its admin panel.
    else if (user && user.role === 'finance_admin') router.replace('/admin');
    else if (user) router.replace('/(tabs)');
    else router.replace('/login');
  }, [user, loading]);

  // TEMPORARY: handle the Emergent portal's OAuth fragment on web (see
  // EMERGENT_AUTH_URL in backend/server.py) — only reached when
  // login.tsx's AUTH0_CONFIGURED is false. Remove alongside that fallback.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.location) return;
    const hash = window.location.hash || '';
    if (hash.includes('session_id=')) {
      const sid = hash.split('session_id=')[1].split('&')[0];
      const url = `${process.env.EXPO_PUBLIC_BACKEND_URL}/api/auth/session`;
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ session_id: sid }),
      }).then(async (r) => {
        if (r.ok) {
          const j = await r.json();
          // Persist token in AsyncStorage for native fallback
          const AS = (await import('@react-native-async-storage/async-storage')).default;
          await AS.setItem('vl_session_token', j.session_token);
          window.location.hash = '';
          window.location.href = '/';
        }
      }).catch(() => {});
    }
  }, []);

  return (
    <View style={styles.center}>
      <Text style={styles.brand}>VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text></Text>
      <ActivityIndicator color={COLORS.primary} style={{ marginTop: 12 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  brand: { color: '#fff', fontSize: 28, fontWeight: '900', letterSpacing: 2 },
});
