// A card that turns over in 3D when tapped and comes forward while it is
// turned: a front and a back, each a GlowCard, rotating about the vertical
// axis (Reanimated rotateY, 450 ms, ease-out, 1.07 scale-up).
//
// The parent owns which card is flipped (`flipped` / `onFlip`), because only
// one card on the screen may be open at a time: opening a second flips the
// first back. That is also why a card can mount already flipped, and why the
// faces must render sensibly with empty data (see the mount-empty-then-open
// tests): the back is mounted from the first frame, hidden behind the front,
// so whatever it renders runs on every dashboard load, not only on a tap.
//
// Reduce Motion: the faces swap instantly with no rotation and no scale.
import React, { useEffect } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, { interpolate, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import GlowCard from './GlowCard';
import { MOTION, useReduceMotion } from '../lib/motion';

/** The screen holds which card is open. Tapping the open card closes it;
 *  tapping any other card opens that one, which flips the first back. */
export const nextFlipped = (current: string | null, tapped: string): string | null =>
  (current === tapped ? null : tapped);

export default function FlipCard({
  front, back, height, accent, flipped, onFlip, frontLabel, backLabel, style, testID,
}: {
  front: () => React.ReactNode;
  back: () => React.ReactNode;
  height: number;
  accent: string;
  flipped: boolean;
  onFlip: () => void;
  /** Read aloud for the front face, ending with what a tap does. */
  frontLabel: string;
  backLabel: string;
  style?: React.ComponentProps<typeof View>['style'];
  testID?: string;
}) {
  const reduceMotion = useReduceMotion();
  const progress = useSharedValue(flipped ? 1 : 0);
  const lift = useSharedValue(flipped ? 1 : 0);

  useEffect(() => {
    const target = flipped ? 1 : 0;
    if (reduceMotion) {
      progress.value = target;
      lift.value = 0;
      return;
    }
    const timing = { duration: MOTION.flipMs, easing: MOTION.flipEasing };
    progress.value = withTiming(target, timing);
    lift.value = withTiming(target, timing);
  }, [flipped, reduceMotion, progress, lift]);

  const frontStyle = useAnimatedStyle(() => ({
    transform: [
      { perspective: MOTION.flipPerspective },
      { rotateY: `${interpolate(progress.value, [0, 1], [0, 180])}deg` },
      { scale: interpolate(lift.value, [0, 1], [1, MOTION.flipScale]) },
    ],
  }));
  const backStyle = useAnimatedStyle(() => ({
    transform: [
      { perspective: MOTION.flipPerspective },
      { rotateY: `${interpolate(progress.value, [0, 1], [180, 360])}deg` },
      { scale: interpolate(lift.value, [0, 1], [1, MOTION.flipScale]) },
    ],
  }));

  return (
    // The open card rises above its neighbours so its scale-up overlaps them
    // instead of sliding underneath.
    <View style={[{ height }, flipped ? styles.raised : null, style]} testID={testID}>
      <Animated.View
        style={[styles.face, frontStyle]}
        pointerEvents={flipped ? 'none' : 'auto'}
        accessibilityElementsHidden={flipped}
        importantForAccessibility={flipped ? 'no-hide-descendants' : 'auto'}
      >
        <Pressable
          style={styles.fill}
          onPress={onFlip}
          accessibilityRole="button"
          accessibilityLabel={frontLabel}
          testID={testID ? `${testID}-front` : undefined}
        >
          <GlowCard accent={accent} fill>{front()}</GlowCard>
        </Pressable>
      </Animated.View>
      <Animated.View
        style={[styles.face, backStyle]}
        pointerEvents={flipped ? 'auto' : 'none'}
        accessibilityElementsHidden={!flipped}
        importantForAccessibility={flipped ? 'auto' : 'no-hide-descendants'}
      >
        <Pressable
          style={styles.fill}
          onPress={onFlip}
          accessibilityRole="button"
          accessibilityLabel={backLabel}
          testID={testID ? `${testID}-back` : undefined}
        >
          <GlowCard accent={accent} fill>{back()}</GlowCard>
        </Pressable>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  face: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backfaceVisibility: 'hidden' },
  fill: { flex: 1 },
  raised: { zIndex: 10, elevation: 10 },
});
