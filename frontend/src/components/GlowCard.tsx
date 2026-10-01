// The raised surface every refreshed dashboard card sits on: a gradient from
// surface2 to surface, a hairline border with a brighter top edge in the
// card's accent, and a soft shadow in the accent colour.
//
// The gradient is drawn with react-native-svg, not expo-linear-gradient: that
// native module is missing from the current binary, and importing it would
// crash an OTA update on devices that have not had a new build.
//
// Layering: the outer view carries the shadow (an overflow-hidden view would
// clip it on iOS), the inner view clips the gradient to the rounded corners.
// Android cannot draw a coloured shadow, so it gets elevation plus a faint
// accent backer view behind the card instead.
import React from 'react';
import { Platform, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import { COLORS } from '../lib/auth';
import { DEPTH, withAlpha } from '../lib/motion';

export default function GlowCard({
  accent = COLORS.primary, children, style, contentStyle, fill = false, testID,
}: {
  accent?: string;
  children?: React.ReactNode;
  /** Stretch to the parent's height (a flip face); otherwise size to content. */
  fill?: boolean;
  /** Outer view: margins, flex, width. Never padding. */
  style?: StyleProp<ViewStyle>;
  /** Inner view: padding and layout of the content. */
  contentStyle?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  const shadow: ViewStyle = Platform.select<ViewStyle>({
    ios: {
      shadowColor: accent,
      shadowOpacity: DEPTH.shadowOpacity,
      shadowRadius: DEPTH.shadowRadius,
      shadowOffset: { width: 0, height: DEPTH.shadowOffsetY },
    },
    android: { elevation: DEPTH.androidElevation },
    default: {},
  }) ?? {};
  // react-native-web ignores the iOS shadow props, so the web build takes a
  // boxShadow instead.
  const webShadow = Platform.OS === 'web'
    ? ({ boxShadow: `0 ${DEPTH.shadowOffsetY + 2}px ${DEPTH.shadowRadius + 10}px ${withAlpha(accent, DEPTH.shadowOpacity)}` } as ViewStyle)
    : null;

  return (
    <View style={[styles.outer, fill && styles.fill, shadow, webShadow, style]} testID={testID}>
      {Platform.OS === 'android' ? (
        <View pointerEvents="none" style={styles.backer}>
          <Svg width="100%" height="100%" preserveAspectRatio="none">
            <Defs>
              <LinearGradient id="glowBacker" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={accent} stopOpacity="0" />
                <Stop offset="1" stopColor={accent} stopOpacity={DEPTH.androidBackerAlpha} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100%" height="100%" rx={DEPTH.radius + 4} fill="url(#glowBacker)" />
          </Svg>
        </View>
      ) : null}
      <View style={[styles.inner, fill && styles.fill]}>
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <Svg width="100%" height="100%" preserveAspectRatio="none">
            <Defs>
              <LinearGradient id="glowCardSurface" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={COLORS.surface2} />
                <Stop offset="1" stopColor={COLORS.surface} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100%" height="100%" fill="url(#glowCardSurface)" />
          </Svg>
        </View>
        <View pointerEvents="none" style={[styles.topEdge, { backgroundColor: withAlpha(accent, DEPTH.topEdgeAlpha) }]} />
        <View style={[fill && styles.fill, contentStyle]}>{children}</View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outer: {
    borderRadius: DEPTH.radius,
    backgroundColor: COLORS.surface,
  },
  inner: {
    borderRadius: DEPTH.radius,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
  },
  fill: { flex: 1 },
  topEdge: { position: 'absolute', top: 0, left: 0, right: 0, height: 1 },
  backer: { position: 'absolute', top: 6, left: -3, right: -3, bottom: -6 },
});
