// Auth gate: redirects to login or tabs based on session
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth, COLORS, setToken } from '../src/lib/auth';

// TEMPORARY: the Emergent portal hands the session back in the URL fragment
// (see EMERGENT_AUTH_URL in backend/server.py) — only reached when login.tsx's
// AUTH0_CONFIGURED is false. Remove alongside that fallback.
//
// Read once, on first render: the exchange clears the hash, and both effects
// below have to keep knowing an exchange is in flight after that.
function readSessionFragment(): string | null {
  if (typeof window === 'undefined' || !window.location) return null;
  const hash = window.location.hash || '';
  if (!hash.includes('session_id=')) return null;
  return hash.split('session_id=')[1].split('&')[0] || null;
}

function clearSessionFragment() {
  if (typeof window !== 'undefined' && window.location) window.location.hash = '';
}

const EXCHANGE_TIMEOUT_MS = 15000;

export default function Index() {
  const router = useRouter();
  const { user, loading, reload } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(readSessionFragment);
  const [exchangeError, setExchangeError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (loading) return;
    // Don't route while the fragment exchange is still running or sitting on
    // its error card: redirecting mid-exchange was the loader -> login ->
    // full page reload -> dashboard flicker.
    if (sessionId || exchangeError) return;
    if (user && user.role === 'pending') router.replace('/pending');
    // Financial Admin has no production identity — it skips Pulse entry and
    // the rest of the tab bar entirely, landing straight on its admin panel.
    else if (user && user.role === 'finance_admin') router.replace('/admin');
    else if (user) router.replace('/(tabs)');
    else router.replace('/login');
  }, [user, loading, sessionId, exchangeError, router]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), EXCHANGE_TIMEOUT_MS);

    (async () => {
      try {
        const res = await fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL}/api/auth/session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ session_id: sessionId }),
          signal: controller.signal,
        });
        if (!res.ok) {
          let detail = `The server returned ${res.status}.`;
          try {
            const j = await res.json();
            if (j?.detail) detail = String(j.detail);
          } catch {
            // Non-JSON error body — the status is all we have.
          }
          throw new Error(detail);
        }
        const j = await res.json();
        await setToken(j.session_token);
        if (cancelled) return;
        clearSessionFragment();
        // reload() instead of window.location.href = '/': the redirect effect
        // above routes once the session lands, with no full page reload.
        await reload();
        if (!cancelled) setSessionId(null);
      } catch (e: unknown) {
        if (cancelled) return;
        const aborted = e instanceof Error && e.name === 'AbortError';
        // Reacting to the exchange's outcome, not deriving local state.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setExchangeError(
          aborted
            ? 'The request timed out. Check your connection and try again.'
            : (e instanceof Error ? e.message : String(e)),
        );
      } finally {
        clearTimeout(timer);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
    // reload is re-created on every AuthProvider render; including it here
    // would restart the exchange on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, attempt]);

  const retry = useCallback(() => {
    setExchangeError(null);
    setAttempt((n) => n + 1);
  }, []);

  const backToSignIn = useCallback(() => {
    clearSessionFragment();
    setExchangeError(null);
    setSessionId(null);
    router.replace('/login');
  }, [router]);

  if (exchangeError) {
    return (
      <View style={styles.center}>
        <Text style={styles.brand}>
          VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text>
        </Text>
        <Text style={styles.title}>We couldn&apos;t finish signing you in</Text>
        <Text style={styles.detail} numberOfLines={4}>{exchangeError}</Text>
        <TouchableOpacity
          style={styles.btn}
          onPress={retry}
          accessibilityRole="button"
          accessibilityLabel="Try signing in again"
          testID="session-exchange-retry"
        >
          <Text style={styles.btnTxt}>TRY AGAIN</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={backToSignIn}
          accessibilityRole="button"
          accessibilityLabel="Back to sign in"
          testID="session-exchange-back"
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <Text style={styles.link}>Back to Sign In</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.center}>
      <Text style={styles.brand}>
        VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text>
      </Text>
      <ActivityIndicator
        color={COLORS.primary}
        style={{ marginTop: 12 }}
        accessibilityLabel={sessionId ? 'Signing you in' : 'Loading'}
      />
      {sessionId ? <Text style={styles.detail}>Signing you in…</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: COLORS.bg,
    padding: 28,
    gap: 10,
  },
  brand: { color: COLORS.text, fontSize: 28, fontWeight: '900', letterSpacing: 2 },
  title: { color: COLORS.text, fontSize: 16, fontWeight: '800', textAlign: 'center', marginTop: 10 },
  detail: { color: COLORS.textDim, fontSize: 13, textAlign: 'center', lineHeight: 19 },
  btn: {
    marginTop: 8,
    backgroundColor: COLORS.primary,
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 32,
    minHeight: 44,
    justifyContent: 'center',
  },
  btnTxt: { color: '#000', fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  link: { color: COLORS.textDim, fontSize: 13, fontWeight: '700', paddingVertical: 8 },
});
