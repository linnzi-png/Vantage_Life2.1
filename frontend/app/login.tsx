// Login screen with Google sign-in + 4 demo level buttons (no Google needed)
// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Platform, ScrollView, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as AppleAuthentication from 'expo-apple-authentication';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import * as AuthSession from 'expo-auth-session';
import { useAuth, COLORS, Role } from '../src/lib/auth';

// Completes the popup-based web flow when Auth0 redirects back to the app.
WebBrowser.maybeCompleteAuthSession();

// Google sign-in via Auth0 Universal Login, routed straight to the Google
// connection (skips Auth0's account chooser). The app gets an Auth0-issued
// ID token back and the backend verifies it (/api/auth/auth0).
const AUTH0_DOMAIN = process.env.EXPO_PUBLIC_AUTH0_DOMAIN || '';
const AUTH0_WEB_CLIENT_ID = process.env.EXPO_PUBLIC_AUTH0_WEB_CLIENT_ID || '';
const AUTH0_IOS_CLIENT_ID = process.env.EXPO_PUBLIC_AUTH0_IOS_CLIENT_ID || '';
const AUTH0_CLIENT_ID = Platform.OS === 'web' ? AUTH0_WEB_CLIENT_ID : (AUTH0_IOS_CLIENT_ID || AUTH0_WEB_CLIENT_ID);
const AUTH0_CONFIGURED = !!(AUTH0_DOMAIN && AUTH0_CLIENT_ID);

const LEVELS: { level: Role; title: string; subtitle: string; tint: string }[] = [
  { level: 'level_1', title: 'AGENT', subtitle: 'Personal stats + Pulse entry', tint: COLORS.primary },
  { level: 'level_2', title: 'GA', subtitle: 'Co-Executive Producer · Team view', tint: COLORS.secondary },
  { level: 'level_3', title: 'MGA', subtitle: 'Executive Producer · Full agency hierarchy', tint: COLORS.gold },
  { level: 'level_4', title: 'RGA', subtitle: 'Executive · Global view + Eraser + Vault', tint: COLORS.orange },
];

export default function LoginScreen() {
  const { signInDemo, signInApple, signInAuth0, signInGoogleSession } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<Role | 'google' | 'apple' | null>(null);

  // Hooks must be unconditional; the placeholder domain is never prompted
  // because onGoogle only calls promptAuth0() when AUTH0_CONFIGURED is true.
  //
  // Authorization Code + PKCE, not Implicit Grant (ResponseType.IdToken):
  // some Auth0 tenants disable Implicit Grant by default on new
  // Applications, which would silently break this button. Code + PKCE works
  // regardless of that tenant setting and needs no client secret for a
  // public (mobile/SPA) client.
  const redirectUri = useMemo(() => AuthSession.makeRedirectUri(), []);
  const discovery = useMemo(
    () => ({
      authorizationEndpoint: `https://${AUTH0_DOMAIN || 'unconfigured.auth0.com'}/authorize`,
      tokenEndpoint: `https://${AUTH0_DOMAIN || 'unconfigured.auth0.com'}/oauth/token`,
    }),
    [],
  );
  const [authRequest, authResponse, promptAuth0] = AuthSession.useAuthRequest(
    {
      clientId: AUTH0_CLIENT_ID || 'unconfigured',
      redirectUri,
      responseType: AuthSession.ResponseType.Code,
      scopes: ['openid', 'profile', 'email'],
      extraParams: { connection: 'google-oauth2' },
    },
    discovery,
  );

  useEffect(() => {
    if (!authResponse) return;
    if (authResponse.type !== 'success') {
      // 'dismiss'/'cancel' are the user closing the sheet — stay silent.
      if (authResponse.type === 'error') {
        Alert.alert('Sign-In Error', authResponse.params?.error_description || 'Please try again.');
      }
      setBusy(null);
      return;
    }
    const code = authResponse.params.code;
    const codeVerifier = authRequest?.codeVerifier;
    if (!code || !codeVerifier) {
      Alert.alert('Sign-In Error', 'Google sign-in did not complete. Please try again.');
      setBusy(null);
      return;
    }
    (async () => {
      try {
        const tokenResponse = await AuthSession.exchangeCodeAsync(
          {
            clientId: AUTH0_CLIENT_ID,
            code,
            redirectUri,
            extraParams: { code_verifier: codeVerifier },
          },
          discovery,
        );
        if (!tokenResponse.idToken) {
          throw new Error('Google did not return an identity token. Please try again.');
        }
        await signInAuth0(tokenResponse.idToken);
        router.replace('/');
      } catch (e: unknown) {
        Alert.alert('Sign-In Error', e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authResponse]);

  const onDemo = async (level: Role) => {
    setBusy(level);
    try {
      await signInDemo(level);
      router.replace('/');
    } catch (e: any) {
      Alert.alert('Login Error', e.message || String(e));
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
      if (!credential.identityToken) {
        throw new Error('Apple did not return an identity token. Please try again.');
      }
      await signInApple(
        credential.identityToken,
        credential.fullName?.givenName ?? null,
        credential.fullName?.familyName ?? null,
      );
      router.replace('/');
    } catch (e: unknown) {
      const err = e as { code?: string; message?: string };
      // User dismissed the Apple sheet — not an error, stay silent.
      if (err.code === 'ERR_REQUEST_CANCELED' || err.code === 'ERR_CANCELED') return;
      Alert.alert('Sign-In Error', err.message || 'Unknown error. Please check your connection and try again.');
    } finally {
      setBusy(null);
    }
  };

  const onGoogle = async () => {
    setBusy('google');
    try {
      if (AUTH0_CONFIGURED) {
        // Auth0 Universal Login opens, federates to Google, and the ID token
        // lands in the authResponse effect above.
        await promptAuth0();
        return;
      }
      // TEMPORARY: no Auth0 tenant configured on this build yet (see
      // EMERGENT_AUTH_URL in backend/server.py) — fall back to the Emergent
      // portal rather than dead-ending on a Google button that can't work.
      // Remove this branch alongside that backend fallback.
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
      Alert.alert('Sign-In Error', e.message || String(e));
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
            <Text style={styles.tagline}>Real-Time Impact Culture · AO Premier</Text>
          </View>
        </View>

        <View style={styles.hero}>
          <Text style={styles.heroLabel}>EXECUTIVE MASTER BUILD</Text>
          <Text style={styles.heroH1}>Sign in to your scoreboard.</Text>
          <Text style={styles.heroSub}>The 174-person sales force lives here. Pulse, Platinum Wall, and the Eraser tool — all in one.</Text>
        </View>

        <TouchableOpacity testID="google-signin-btn" style={styles.googleBtn} onPress={onGoogle} disabled={!!busy || (AUTH0_CONFIGURED && !authRequest)}>
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

        <Text style={styles.footer}>{"By continuing you agree to AO Premier's standards of accountability."}</Text>
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
