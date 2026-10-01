// Liquid Glass gate (batch 3, 2026-10-01).
//
// Glass is for the chrome layer only: the Daily / Weekly / Monthly control and
// the LIVE pill. Cards are content and stay on GlowCard, and glass is never
// stacked on glass. Every use asks this gate first; when it says no (Android,
// web, iOS before 26, or an iOS 26 point release that lacks the API) the
// caller draws its plain version, so a surface is never empty.
import { Platform } from 'react-native';
import { isGlassEffectAPIAvailable, isLiquidGlassAvailable } from 'expo-glass-effect';

/** True only where native Liquid Glass can actually render. */
export function glassAvailable(): boolean {
  if (Platform.OS !== 'ios') return false;
  try {
    return isLiquidGlassAvailable() && isGlassEffectAPIAvailable();
  } catch {
    // Some iOS 26 betas crash on the native probe; treat any throw as "no".
    return false;
  }
}
