// The dashboard's Daily / Weekly / Monthly control: three 44px segments, the
// active one in a green gradient with a glow. On iOS 26 the three segments are
// Liquid Glass inside one GlassContainer, the active one tinted brand green;
// everywhere else, and whenever Reduce Transparency is on, it is the plain
// version. Same value and onChange as PeriodSelector, which the other screens
// keep using.
import React from 'react';
import { Platform, Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import { GlassContainer, GlassView } from 'expo-glass-effect';
import { COLORS } from '../lib/auth';
import { glassAvailable } from '../lib/glass';
import { DEPTH, useReduceTransparency, withAlpha } from '../lib/motion';
import { PERIODS, Period } from './PeriodSelector';

const LABELS: Record<Period, string> = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };
export const SEGMENT_HEIGHT = 44;
// The darker end of the active gradient keeps white text above AA contrast.
const GREEN_DEEP = '#2A8239';

export default function PeriodSegmented({ value, onChange, testID = 'period-segmented' }: {
  value: Period;
  onChange: (p: Period) => void;
  testID?: string;
}) {
  const reduceTransparency = useReduceTransparency();
  const glass = glassAvailable();

  const segments = PERIODS.map((p) => {
    const active = value === p;
    return (
      <Pressable
        key={p}
        onPress={() => onChange(p)}
        style={styles.segment}
        accessibilityRole="button"
        accessibilityState={{ selected: active }}
        accessibilityLabel={`${LABELS[p]} figures`}
        testID={`${testID}-${p}`}
      >
        {glass ? (
          <GlassView
            style={[StyleSheet.absoluteFill, styles.glassFill]}
            pointerEvents="none"
            isInteractive
            tintColor={active ? COLORS.primary : undefined}
            glassEffectStyle={reduceTransparency ? 'none' : { style: 'regular', animate: true }}
          />
        ) : active ? (
          <View style={[StyleSheet.absoluteFill, styles.activeFill, glowStyle]} pointerEvents="none">
            <Svg width="100%" height="100%" preserveAspectRatio="none">
              <Defs>
                <LinearGradient id="segmentActive" x1="0" y1="0" x2="0" y2="1">
                  <Stop offset="0" stopColor={COLORS.primary} />
                  <Stop offset="1" stopColor={GREEN_DEEP} />
                </LinearGradient>
              </Defs>
              <Rect x="0" y="0" width="100%" height="100%" rx={DEPTH.radius - 2} fill="url(#segmentActive)" />
            </Svg>
          </View>
        ) : null}
        <Text style={[styles.txt, active && styles.txtActive]}>{LABELS[p]}</Text>
      </Pressable>
    );
  });

  if (glass) {
    return (
      <GlassContainer spacing={6} style={styles.bar} testID={testID}>
        {segments}
      </GlassContainer>
    );
  }
  return <View style={[styles.bar, styles.track]} testID={testID}>{segments}</View>;
}

const glowStyle: ViewStyle = Platform.select<ViewStyle>({
  ios: { shadowColor: COLORS.primary, shadowOpacity: 0.55, shadowRadius: 10, shadowOffset: { width: 0, height: 0 } },
  android: { elevation: 4 },
  default: { boxShadow: `0 0 14px ${withAlpha(COLORS.primary, 0.5)}` } as ViewStyle,
}) ?? {};

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  track: {
    padding: 3, borderRadius: DEPTH.radius, backgroundColor: COLORS.surface,
    borderWidth: 1, borderColor: COLORS.border,
  },
  segment: { flex: 1, height: SEGMENT_HEIGHT, alignItems: 'center', justifyContent: 'center' },
  glassFill: { borderRadius: DEPTH.radius },
  // The solid backing gives the glow a shape to cast from; the SVG gradient
  // paints over it with the same rounded corners.
  activeFill: { borderRadius: DEPTH.radius - 2, backgroundColor: COLORS.primary },
  txt: { color: COLORS.textDim, fontSize: 13, fontWeight: '800', letterSpacing: 0.8 },
  txtActive: { color: '#FFFFFF' },
});
