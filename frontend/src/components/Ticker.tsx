// Scrolling marquee ticker — sports scoreboard meets trading floor
import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Easing, useWindowDimensions } from 'react-native';
import { COLORS } from '../lib/auth';

export interface TickerItem {
  agent_name: string;
  alp: number;
  market: string;
  reps: number;
  ts: string;
}

export default function Ticker({ items }: { items: TickerItem[] }) {
  const translateX = useRef(new Animated.Value(0)).current;
  const { width: screenW } = useWindowDimensions();

  const display = items.length
    ? items
    : [{ agent_name: 'Awaiting Live Activity', alp: 0, market: '—', reps: 0, ts: '' } as TickerItem];

  useEffect(() => {
    translateX.setValue(0);
    const totalWidth = Math.max(2000, display.length * 320);
    Animated.loop(
      Animated.timing(translateX, {
        toValue: -totalWidth,
        duration: Math.max(20000, totalWidth * 14),
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    ).start();
    return () => translateX.stopAnimation();
  }, [items.length, screenW]);

  // Duplicate items so the loop is seamless
  const seq = [...display, ...display, ...display];

  return (
    <View style={styles.bar} testID="dashboard-ticker">
      <View style={styles.label}><Text style={styles.labelText}>LIVE</Text></View>
      <View style={styles.scrollArea}>
        <Animated.View style={[styles.row, { transform: [{ translateX }] }]}>
          {seq.map((it, i) => (
            <View key={i} style={styles.cell}>
              <Text style={styles.dot}>●</Text>
              <Text style={styles.agent} numberOfLines={1}>{it.agent_name}</Text>
              <Text style={styles.alp}>${Math.round(it.alp).toLocaleString()}</Text>
              <Text style={styles.market}>{it.market}</Text>
              <Text style={styles.reps}>· {it.reps} REPS</Text>
            </View>
          ))}
        </Animated.View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 36,
    backgroundColor: '#000',
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    overflow: 'hidden',
  },
  label: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: COLORS.primary,
    height: '100%',
    justifyContent: 'center',
  },
  labelText: { color: '#000', fontWeight: '900', fontSize: 11, letterSpacing: 1.5 },
  scrollArea: { flex: 1, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center' },
  cell: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, height: 36 },
  dot: { color: COLORS.primary, marginRight: 8, fontSize: 8 },
  agent: { color: COLORS.text, fontWeight: '700', fontSize: 12, marginRight: 8, maxWidth: 140 },
  alp: { color: COLORS.primary, fontWeight: '900', fontSize: 13, marginRight: 8, fontVariant: ['tabular-nums' as any] },
  market: { color: COLORS.textDim, fontSize: 11, marginRight: 6 },
  reps: { color: COLORS.gold, fontSize: 11, fontWeight: '700' },
});
