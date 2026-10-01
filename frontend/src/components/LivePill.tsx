// The LIVE pill beside the day picker in the dashboard header. A pulsing green
// dot and "LIVE" on today and on the rolling windows; "HISTORY" in gold, with
// a still dot, when a past sales day is open.
//
// The pulse stops when Reduce Motion is on. On iOS 26 the pill is a Liquid
// Glass chip (plain when Reduce Transparency is on); elsewhere it is a bordered
// chip. Never stacked on another glass surface.
import React, { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, { cancelAnimation, Easing, useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';
import { GlassView } from 'expo-glass-effect';
import { COLORS } from '../lib/auth';
import { glassAvailable } from '../lib/glass';
import { MOTION, useReduceMotion, useReduceTransparency, withAlpha } from '../lib/motion';

export default function LivePill({ history = false, testID = 'live-pill' }: { history?: boolean; testID?: string }) {
  const reduceMotion = useReduceMotion();
  const reduceTransparency = useReduceTransparency();
  const glass = glassAvailable();
  const colour = history ? COLORS.gold : COLORS.primary;
  const pulse = useSharedValue(0);
  const animate = !history && !reduceMotion;

  useEffect(() => {
    if (animate) {
      pulse.value = withRepeat(withTiming(1, { duration: MOTION.pulseMs, easing: Easing.inOut(Easing.sin) }), -1, true);
    } else {
      cancelAnimation(pulse);
      pulse.value = 0;
    }
    return () => cancelAnimation(pulse);
  }, [animate, pulse]);

  const haloStyle = useAnimatedStyle(() => ({
    opacity: 0.55 * (1 - pulse.value),
    transform: [{ scale: 1 + pulse.value * 1.2 }],
  }));

  const label = history ? 'HISTORY' : 'LIVE';
  return (
    <View
      style={[styles.pill, { borderColor: withAlpha(colour, glass ? 0.0 : 0.55) }]}
      accessibilityRole="text"
      accessibilityLabel={history ? 'Viewing history' : 'Live'}
      testID={testID}
    >
      {glass ? (
        <GlassView
          style={StyleSheet.absoluteFill}
          pointerEvents="none"
          tintColor={withAlpha(colour, 0.35)}
          glassEffectStyle={reduceTransparency ? 'none' : 'regular'}
        />
      ) : null}
      <View style={styles.dotBox}>
        {animate ? <Animated.View style={[styles.halo, { backgroundColor: colour }, haloStyle]} /> : null}
        <View style={[styles.dot, { backgroundColor: colour }]} />
      </View>
      <Text style={[styles.txt, { color: colour }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row', alignItems: 'center', gap: 6, overflow: 'hidden',
    borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, height: 30,
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  dotBox: { width: 10, height: 10, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 6, height: 6, borderRadius: 3 },
  halo: { position: 'absolute', width: 6, height: 6, borderRadius: 3 },
  txt: { fontSize: 11, fontWeight: '900', letterSpacing: 1.2 },
});
