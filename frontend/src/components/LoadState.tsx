// One wrapper for the four states every fetched screen has: loading, failed,
// empty, and loaded.
//
// The bug this exists to kill: almost every screen caught its fetch error with
// a bare `catch {}` and then rendered its empty-state copy, so a 500 told the
// agent "No team data yet." or "No one on file for this office yet." — the app
// blaming the user for an outage, with no retry and no way to tell the two
// apart. An error must never render as an empty state, so `error` is checked
// before `isEmpty` here and the screens cannot get that order wrong.
import React, { ReactNode } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

interface Props {
  loading: boolean;
  /** Message from the failed request. Null/undefined means it succeeded. */
  error?: string | null;
  /** Omit to render the error without a retry control. */
  onRetry?: () => void;
  /** True when the request succeeded and legitimately returned nothing. */
  isEmpty?: boolean;
  emptyText?: string;
  /** Shown under the spinner. Keep it short. */
  loadingText?: string;
  children: ReactNode;
  testID?: string;
}

export function LoadState({
  loading,
  error,
  onRetry,
  isEmpty,
  emptyText = 'Nothing here yet.',
  loadingText,
  children,
  testID,
}: Props) {
  // Order matters: error wins over isEmpty, so a failure can never reach the
  // user as "nothing here". Whether a failure that happened while data was
  // already on screen is worth taking that screen over is the caller's call —
  // the polled screens pass `error` only when they have nothing to show, so a
  // flaky 30s tick doesn't replace a good list with an error card.
  if (error) {
    return (
      <View style={styles.box} testID={testID ? `${testID}-error` : 'loadstate-error'}>
        <Ionicons name="cloud-offline-outline" size={28} color={COLORS.orange} />
        <Text style={styles.title}>Couldn&apos;t load this</Text>
        <Text style={styles.detail} numberOfLines={3}>{error}</Text>
        {onRetry ? (
          <TouchableOpacity
            style={styles.btn}
            onPress={onRetry}
            accessibilityRole="button"
            accessibilityLabel="Retry loading"
            testID={testID ? `${testID}-retry` : 'loadstate-retry'}
          >
            <Text style={styles.btnTxt}>RETRY</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    );
  }

  if (loading) {
    return (
      <View style={styles.box} testID={testID ? `${testID}-loading` : 'loadstate-loading'}>
        <ActivityIndicator color={COLORS.primary} accessibilityLabel={loadingText || 'Loading'} />
        {loadingText ? <Text style={styles.detail}>{loadingText}</Text> : null}
      </View>
    );
  }

  if (isEmpty) {
    return (
      <View style={styles.box} testID={testID ? `${testID}-empty` : 'loadstate-empty'}>
        <Text style={styles.detail}>{emptyText}</Text>
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  box: { alignItems: 'center', justifyContent: 'center', paddingVertical: 34, paddingHorizontal: 20, gap: 10 },
  title: { color: COLORS.text, fontSize: 15, fontWeight: '800', textAlign: 'center' },
  detail: { color: COLORS.textDim, fontSize: 13, lineHeight: 19, textAlign: 'center' },
  btn: {
    marginTop: 4,
    borderWidth: 1,
    borderColor: COLORS.primary,
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 26,
    minHeight: 44,
    justifyContent: 'center',
  },
  btnTxt: { color: COLORS.primary, fontSize: 12, fontWeight: '900', letterSpacing: 1 },
});

export default LoadState;
