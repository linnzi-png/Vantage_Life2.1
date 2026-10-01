// Motion and depth tokens for the dashboard refresh (batch 3, 2026-10-01).
//
// Every card, flip and glow on the refreshed screens reads its numbers from
// here, so batch 5 (the app-wide visual refresh) can retune the whole feel in
// one file instead of hunting through components.
import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';
import { Easing } from 'react-native-reanimated';

export const MOTION = {
  /** Card flip, front to back or back to front (design review, 2026-09-29). */
  flipMs: 450,
  /** The card comes forward by this factor while it is flipped. */
  flipScale: 1.07,
  /** Perspective distance for rotateY; smaller reads as a deeper flip. */
  flipPerspective: 1100,
  flipEasing: Easing.out(Easing.cubic),
  /** One breath of the LIVE pill dot, in and out. */
  pulseMs: 1100,
} as const;

export const DEPTH = {
  radius: 12,
  /** Soft coloured shadow under a raised card. */
  shadowOpacity: 0.28,
  shadowRadius: 18,
  shadowOffsetY: 6,
  /** The brighter top edge of a card, as an alpha on the accent colour. */
  topEdgeAlpha: 0.7,
  /** The accent glow behind a card on Android, where coloured shadows do not render. */
  androidBackerAlpha: 0.2,
  androidElevation: 4,
} as const;

/** "#RRGGBB" plus an alpha 0 to 1, as an rgba() string. */
export function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Follows the system Reduce Motion setting, live. False until it is known. */
export function useReduceMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceMotionEnabled().then((v) => { if (active) setReduce(!!v); }).catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (v) => { if (active) setReduce(!!v); });
    return () => { active = false; sub.remove(); };
  }, []);
  return reduce;
}

/** Follows the system Reduce Transparency setting, live (iOS; false elsewhere). */
export function useReduceTransparency(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceTransparencyEnabled().then((v) => { if (active) setReduce(!!v); }).catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceTransparencyChanged', (v) => { if (active) setReduce(!!v); });
    return () => { active = false; sub.remove(); };
  }, []);
  return reduce;
}
