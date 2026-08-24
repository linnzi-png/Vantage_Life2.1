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
    else if (user) router.replace('/(tabs)');
    else router.replace('/login');
  }, [user, loading]);

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
