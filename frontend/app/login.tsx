// Login screen with Google sign-in + 4 demo level buttons (no Google needed)
// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Platform, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as AppleAuthentication from 'expo-apple-authentication';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import { useAuth, COLORS, Role } from '../src/lib/auth';

const LEVELS: { level: Role; title: string; subtitle: string; tint: string }[] = [
  { level: 'level_1', title: 'AGENT', subtitle: 'Personal stats + Pulse entry', tint: COLORS.primary },
  { level: 'level_2', title: 'GA', subtitle: 'Co-Executive Producer · Team view', tint: COLORS.secondary },
  { level: 'level_3', title: 'MGA', subtitle: 'Executive Producer · Full agency hierarchy', tint: COLORS.gold },
  { level: 'level_4', title: 'RGA', subtitle: 'Executive · Global view + Eraser + Vault', tint: COLORS.orange },
];

export default function LoginScreen() {
  const { signInDemo, signInApple, signInGoogleSession } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<Role | 'google' | 'apple' | null>(null);

  const onDemo = async (level: Role) => {
    setBusy(level);
    try {
      await signInDemo(level);
      router.replace('/');
    } catch (e: any) {
      alert(`Login failed: ${e.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  const onApple = async () => {
    setBusy('apple');
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      await signInApple(
        credential.identityToken!,
        credential.fullName?.givenName ?? null,
        credential.fullName?.familyName ?? null,
      );
      router.replace('/');
    } catch (e: any) {
      if (e.code !== 'ERR_REQUEST_CANCELED') {
        alert(`Apple Sign-In failed: ${e.message || e}`);
      }
    } finally {
      setBusy(null);
    }
  };

  const onGoogle = async () => {
    setBusy('google');
    try {
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        const redirectUrl = window.location.origin + '/';
        window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
        return;
      }
      // Native (iOS/Android): open the same Emergent portal in the system
      // browser and catch the deep-link redirect back into the app.
      const redirectUrl = Linking.createURL('');
      const result = await WebBrowser.openAuthSessionAsync(
        `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`,
        redirectUrl,
      );
      if (result.type === 'success') {
        const hash = result.url.split('#')[1] ?? '';
        const sid = hash.split('session_id=')[1]?.split('&')[0];
        if (!sid) throw new Error('No session_id returned from sign-in');
        await signInGoogleSession(sid);
        router.replace('/');
      }
    } catch (e: any) {
      alert(`Google Sign-In failed: ${e.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.brandRow}>
          <View style={styles.brandMark}><Text style={styles.markTxt}>V</Text></View>
          <View>
            <Text style={styles.brand}>VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text> 2.1</Text>
            <Text style={styles.tagline}>Real-Time Impact Culture · AO Premiere</Text>
          </View>
        </View>

        <View style={styles.hero}>
          <Text style={styles.heroLabel}>EXECUTIVE MASTER BUILD</Text>
          <Text style={styles.heroH1}>Sign in to your scoreboard.</Text>
          <Text style={styles.heroSub}>The 174-person sales force lives here. Pulse, Platinum Wall, and the Eraser tool — all in one.</Text>
        </View>

        <TouchableOpacity testID="google-signin-btn" style={styles.googleBtn} onPress={onGoogle} disabled={!!busy}>
          {busy === 'google' ? (
            <ActivityIndicator color="#000" />
          ) : (
            <>
              <Ionicons name="logo-google" size={18} color="#000" />
              <Text style={styles.googleTxt}>Sign in with Google</Text>
            </>
          )}
        </TouchableOpacity>

        {Platform.OS === 'ios' && (
          <AppleAuthentication.AppleAuthenticationButton
            buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
            buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
            cornerRadius={4}
            style={{ width: '100%', height: 48, marginTop: 8 }}
            onPress={onApple}
          />
        )}

        <View style={styles.divider}>
          <View style={styles.divLine} />
          <Text style={styles.divTxt}>OR DEMO BY LEVEL</Text>
          <View style={styles.divLine} />
        </View>

        <View style={{ gap: 8 }}>
          {LEVELS.map((l) => (
            <TouchableOpacity
              key={l.level}
              testID={`demo-login-${l.level}`}
              style={[styles.lvlBtn, { borderLeftColor: l.tint }]}
              onPress={() => onDemo(l.level)}
              disabled={!!busy}
            >
              <View style={styles.lvlLeft}>
                <View style={[styles.badge, { backgroundColor: l.tint + '22', borderColor: l.tint }]}>
                  <Text style={[styles.badgeTxt, { color: l.tint }]}>{l.level.replace('level_', 'L')}</Text>
                </View>
                <View style={{ marginLeft: 12, flex: 1 }}>
                  <Text style={styles.lvlTitle}>{l.title}</Text>
                  <Text style={styles.lvlSub}>{l.subtitle}</Text>
                </View>
              </View>
              {busy === l.level ? <ActivityIndicator color={l.tint} /> : <Ionicons name="chevron-forward" size={18} color={COLORS.textDim} />}
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.footer}>{"By continuing you agree to AO Premiere's standards of accountability."}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  container: { padding: 22, gap: 18, paddingBottom: 60 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 18 },
  brandMark: { width: 38, height: 38, borderRadius: 4, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  markTxt: { color: '#000', fontWeight: '900', fontSize: 22 },
  brand: { color: '#fff', fontSize: 18, fontWeight: '900', letterSpacing: 1.5 },
  tagline: { color: COLORS.textDim, fontSize: 11, marginTop: 2, letterSpacing: 0.6 },
  hero: { marginTop: 8 },
  heroLabel: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 2.5 },
  heroH1: { color: '#fff', fontSize: 30, fontWeight: '900', marginTop: 4, letterSpacing: -0.5 },
  heroSub: { color: COLORS.textDim, fontSize: 13, marginTop: 6, lineHeight: 19 },
  googleBtn: {
    backgroundColor: '#fff', flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    paddingVertical: 14, borderRadius: 4, gap: 10, marginTop: 4,
  },
  googleTxt: { color: '#000', fontWeight: '800', fontSize: 14, letterSpacing: 0.4 },
  divider: { flexDirection: 'row', alignItems: 'center', gap: 8, marginVertical: 4 },
  divLine: { flex: 1, height: 1, backgroundColor: COLORS.border },
  divTxt: { color: COLORS.textMuted, fontSize: 10, letterSpacing: 1.6, fontWeight: '800' },
  lvlBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: COLORS.surface, padding: 14, borderRadius: 6,
    borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 3,
  },
  lvlLeft: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  badge: { width: 36, height: 36, borderRadius: 4, alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  badgeTxt: { fontWeight: '900', fontSize: 13 },
  lvlTitle: { color: '#fff', fontWeight: '900', fontSize: 14, letterSpacing: 0.6 },
  lvlSub: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  footer: { color: COLORS.textMuted, fontSize: 10, textAlign: 'center', marginTop: 18 },
});
