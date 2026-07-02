// Shown when an authenticated identity (Google/Apple) has no matching AO Premiere
// agent record yet. Sign-in succeeds either way — this screen is the gate that
// keeps non-agents from ever reaching real business data.
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth, COLORS } from '../src/lib/auth';

export default function PendingScreen() {
  const { user, signOut } = useAuth();

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.container}>
        <Ionicons name="time-outline" size={48} color={COLORS.gold} />
        <Text style={styles.title}>Account Pending</Text>
        <Text style={styles.body}>
          {user?.email} isn't linked to an AO Premiere agent profile yet. Reach out to your
          office to get added — once you're on the roster, signing in again will take you
          straight to your dashboard.
        </Text>
        <TouchableOpacity style={styles.btn} onPress={signOut}>
          <Text style={styles.btnTxt}>Sign Out</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 14 },
  title: { color: '#fff', fontSize: 22, fontWeight: '900', letterSpacing: 0.4 },
  body: { color: COLORS.textDim, fontSize: 14, textAlign: 'center', lineHeight: 21 },
  btn: { marginTop: 12, paddingVertical: 12, paddingHorizontal: 28, borderRadius: 4, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  btnTxt: { color: '#fff', fontWeight: '800', fontSize: 13, letterSpacing: 0.6 },
});
