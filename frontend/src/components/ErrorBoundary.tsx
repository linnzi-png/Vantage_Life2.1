// Catches render-time throws anywhere below it. Without this the whole app
// unmounts to a blank screen with no way back — a single bad row (a null
// `role` reaching a `.replace`, a partial API payload) took the session with
// it. Resetting re-mounts the subtree, which is enough to recover from a bad
// render caused by transient data.
import React, { Component, ErrorInfo, ReactNode } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { COLORS } from '../lib/auth';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the stack somewhere a developer can reach it; the user-facing card
    // deliberately shows only the message.
    console.error('Unhandled render error:', error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <View style={styles.safe}>
        <ScrollView contentContainerStyle={styles.center}>
          <Text style={styles.brand}>
            VANTAGE<Text style={{ color: COLORS.primary }}>LIFE</Text>
          </Text>
          <Text style={styles.title}>Something went wrong on this screen</Text>
          <Text style={styles.body}>
            The app hit an unexpected error. Your numbers are safe — nothing was submitted or
            changed. Try again, and if it keeps happening let your upline know what you were
            doing when it appeared.
          </Text>
          <Text style={styles.detail} numberOfLines={4}>
            {error.message || String(error)}
          </Text>
          <TouchableOpacity
            style={styles.btn}
            onPress={this.reset}
            accessibilityRole="button"
            accessibilityLabel="Try again"
            testID="error-boundary-retry"
          >
            <Text style={styles.btnTxt}>TRY AGAIN</Text>
          </TouchableOpacity>
        </ScrollView>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  center: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  brand: { color: COLORS.text, fontSize: 22, fontWeight: '900', letterSpacing: 2 },
  title: { color: COLORS.text, fontSize: 17, fontWeight: '800', textAlign: 'center', marginTop: 8 },
  body: { color: COLORS.textDim, fontSize: 13, lineHeight: 19, textAlign: 'center' },
  detail: { color: COLORS.textMuted, fontSize: 12, textAlign: 'center', fontStyle: 'italic' },
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
});

export default ErrorBoundary;
