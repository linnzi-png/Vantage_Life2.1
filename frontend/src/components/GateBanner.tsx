// 9 PM Yellow Warning + 6 AM Red Lock banners
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export default function GateBanner({ gate }: { gate: { state: string; message: string; color: string } | null }) {
  if (!gate) return null;
  if (gate.state === 'open') return null;
  const isWarning = gate.color === 'yellow';
  const bg = isWarning ? '#3A2D00' : '#3A0000';
  const fg = isWarning ? COLORS.yellow : COLORS.red;
  const border = isWarning ? COLORS.yellow : COLORS.red;
  const icon = isWarning ? 'warning' : 'lock-closed';
  return (
    <View style={[styles.bar, { backgroundColor: bg, borderColor: border }]} testID="gate-banner">
      <Ionicons name={icon as any} size={16} color={fg} />
      <Text style={[styles.text, { color: fg }]} numberOfLines={2}>{gate.message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderLeftWidth: 3,
    gap: 10,
  },
  text: { fontWeight: '700', fontSize: 12, flex: 1, letterSpacing: 0.3 },
});
