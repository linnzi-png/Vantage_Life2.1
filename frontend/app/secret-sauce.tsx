// Morgans Secret Sauce — the More-tab Easter egg (per owner, 2026-09-17).
// Reached only by accounts the server flags with `secret_sauce` (see
// SECRET_SAUCE_EMAILS in backend/server.py); everyone else finds it on
// Company Health. The download itself is gated server-side either way.
import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Stack } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../src/lib/auth';
import { SecretSauceExport } from '../src/components/SecretSauceExport';

export default function SecretSauceScreen() {
  return (
    <View style={styles.safe}>
      <Stack.Screen options={{ title: 'MORGANS SECRET SAUCE', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <View style={styles.hero}>
          <Ionicons name="flame" size={28} color={COLORS.gold} />
          <Text style={styles.heroTxt}>You found it.</Text>
          <Text style={styles.heroSub}>The week&apos;s top producers, rookies and Plus Lead leaders — one sheet, every office.</Text>
        </View>
        <SecretSauceExport testID="egg-secret-sauce" />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  hero: { alignItems: 'center', gap: 6, paddingVertical: 18 },
  heroTxt: { color: '#fff', fontSize: 20, fontWeight: '900', letterSpacing: 1 },
  heroSub: { color: COLORS.textDim, fontSize: 12, textAlign: 'center', maxWidth: 320 },
});
