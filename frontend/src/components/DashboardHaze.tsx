// Two faint radial hazes behind the dashboard: green at the top left, orange
// at the right. They give the flat page background some depth for the cards
// to sit on. Drawn with react-native-svg (expo-linear-gradient is not in the
// current binary), non-interactive, and behind everything.
import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, RadialGradient, Rect, Stop } from 'react-native-svg';
import { COLORS } from '../lib/auth';

export default function DashboardHaze() {
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill} testID="dashboard-haze">
      <Svg width="100%" height="100%" preserveAspectRatio="none">
        <Defs>
          <RadialGradient id="hazeGreen" cx="0.1" cy="0.08" rx="0.75" ry="0.4" fx="0.1" fy="0.08">
            <Stop offset="0" stopColor={COLORS.primary} stopOpacity="0.2" />
            <Stop offset="1" stopColor={COLORS.primary} stopOpacity="0" />
          </RadialGradient>
          <RadialGradient id="hazeOrange" cx="1" cy="0.42" rx="0.7" ry="0.32" fx="1" fy="0.42">
            <Stop offset="0" stopColor={COLORS.orange} stopOpacity="0.12" />
            <Stop offset="1" stopColor={COLORS.orange} stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#hazeGreen)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#hazeOrange)" />
      </Svg>
    </View>
  );
}
