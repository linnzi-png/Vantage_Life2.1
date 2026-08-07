// Lightweight SVG chart primitives for the Company Health dashboard.
//
// Deliberately hand-rolled rather than pulling a charting library: these render
// identically on web and native via react-native-svg, and the dashboard only
// needs three shapes. Every chart takes an explicit width so callers can size
// them from useWindowDimensions rather than relying on flex measurement, which
// is unreliable inside a ScrollView on first paint.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Path, Rect, Line, Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import { COLORS } from '../lib/auth';

export interface Point {
  label: string;
  value: number;
}

const PAD_L = 8;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 18;

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag) * mag;
}

/** Filled area + line. Used for the ALP trend. */
export function LineChart({
  data, width, height = 160, color = COLORS.primary, formatValue,
}: {
  data: Point[];
  width: number;
  height?: number;
  color?: string;
  formatValue?: (n: number) => string;
}) {
  if (data.length === 0) return <EmptyChart width={width} height={height} />;

  const innerW = Math.max(width - PAD_L - PAD_R, 1);
  const innerH = Math.max(height - PAD_T - PAD_B, 1);
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  // A single point has no span to divide by; centre it instead of dividing by 0.
  const stepX = data.length > 1 ? innerW / (data.length - 1) : 0;
  const x = (i: number) => PAD_L + (data.length > 1 ? i * stepX : innerW / 2);
  const y = (v: number) => PAD_T + innerH - (v / max) * innerH;

  const line = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(d.value)}`).join(' ');
  const area = `${line} L${x(data.length - 1)},${PAD_T + innerH} L${x(0)},${PAD_T + innerH} Z`;
  const last = data[data.length - 1];

  return (
    <View>
      <Svg width={width} height={height}>
        <Defs>
          <LinearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={color} stopOpacity="0.35" />
            <Stop offset="1" stopColor={color} stopOpacity="0" />
          </LinearGradient>
        </Defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <Line
            key={f}
            x1={PAD_L} x2={width - PAD_R}
            y1={PAD_T + innerH * f} y2={PAD_T + innerH * f}
            stroke={COLORS.border} strokeWidth={1}
          />
        ))}
        <Path d={area} fill="url(#areaFill)" />
        <Path d={line} stroke={color} strokeWidth={2} fill="none" />
        {data.length > 1 ? (
          <Circle cx={x(data.length - 1)} cy={y(last.value)} r={3.5} fill={color} />
        ) : null}
      </Svg>
      <View style={styles.axisRow}>
        <Text style={styles.axisTxt}>{data[0]?.label}</Text>
        <Text style={styles.axisTxt}>
          {formatValue ? `peak ${formatValue(max)}` : ''}
        </Text>
        <Text style={styles.axisTxt}>{last?.label}</Text>
      </View>
    </View>
  );
}

/** Vertical bars. Used for weekly sales counts. */
export function BarChart({
  data, width, height = 140, color = COLORS.secondary,
}: {
  data: Point[];
  width: number;
  height?: number;
  color?: string;
}) {
  if (data.length === 0) return <EmptyChart width={width} height={height} />;

  const innerW = Math.max(width - PAD_L - PAD_R, 1);
  const innerH = Math.max(height - PAD_T - PAD_B, 1);
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const slot = innerW / data.length;
  const barW = Math.max(Math.min(slot * 0.68, 22), 1);

  return (
    <View>
      <Svg width={width} height={height}>
        {data.map((d, i) => {
          const h = (d.value / max) * innerH;
          return (
            <Rect
              key={d.label}
              x={PAD_L + i * slot + (slot - barW) / 2}
              y={PAD_T + innerH - h}
              width={barW}
              height={Math.max(h, d.value > 0 ? 1 : 0)}
              rx={2}
              fill={i === data.length - 1 ? COLORS.gold : color}
            />
          );
        })}
        <Line
          x1={PAD_L} x2={width - PAD_R}
          y1={PAD_T + innerH} y2={PAD_T + innerH}
          stroke={COLORS.border} strokeWidth={1}
        />
      </Svg>
      <View style={styles.axisRow}>
        <Text style={styles.axisTxt}>{data[0]?.label}</Text>
        <Text style={styles.axisTxt}>peak {max}</Text>
        <Text style={styles.axisTxt}>{data[data.length - 1]?.label}</Text>
      </View>
    </View>
  );
}

function EmptyChart({ width, height }: { width: number; height: number }) {
  return (
    <View style={[styles.empty, { width, height }]}>
      <Text style={styles.emptyTxt}>No data for this period</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  axisRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 },
  axisTxt: { color: COLORS.textMuted, fontSize: 9 },
  empty: { alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border, borderRadius: 6 },
  emptyTxt: { color: COLORS.textMuted, fontSize: 11 },
});
