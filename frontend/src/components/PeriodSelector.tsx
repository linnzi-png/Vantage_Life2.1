// Shared Daily / Weekly / Monthly scoreboard selector.
// Windows are computed server-side by scoreboard_window() in backend/server.py:
// weekly = most recent Wednesday 2:00 PM Detroit → now; monthly = 1st → now.
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { COLORS } from '../lib/auth';

export type Period = 'daily' | 'weekly' | 'monthly';
export const PERIODS: Period[] = ['daily', 'weekly', 'monthly'];
const LABELS: Record<Period, string> = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };
export const isPeriod = (v: unknown): v is Period => v === 'daily' || v === 'weekly' || v === 'monthly';

/**
 * Period state persisted per-screen so each screen keeps its own choice across
 * app restarts (e.g. Team defaults Weekly, Dashboard defaults Daily).
 */
export function usePersistedPeriod(storageKey: string, initial: Period = 'weekly'): [Period, (p: Period) => void] {
  const [period, setPeriod] = useState<Period>(initial);
  useEffect(() => {
    AsyncStorage.getItem(storageKey).then((saved) => { if (isPeriod(saved)) setPeriod(saved); }).catch(() => {});
  }, [storageKey]);
  const change = useCallback((p: Period) => {
    setPeriod(p);
    AsyncStorage.setItem(storageKey, p).catch(() => {});
  }, [storageKey]);
  return [period, change];
}

export function PeriodSelector({ value, onChange, testID = 'period-selector' }: {
  value: Period;
  onChange: (p: Period) => void;
  testID?: string;
}) {
  return (
    <View style={styles.bar} testID={testID}>
      {PERIODS.map((p) => (
        <TouchableOpacity
          key={p}
          onPress={() => onChange(p)}
          style={[styles.btn, value === p && styles.btnActive]}
          testID={`${testID}-${p}`}
          accessibilityRole="button"
          accessibilityState={{ selected: value === p }}
        >
          <Text style={[styles.txt, value === p && styles.txtActive]}>{LABELS[p]}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  bar:       { flexDirection: 'row', alignItems: 'center', gap: 6 },
  btn:       { flex: 1, alignItems: 'center', paddingVertical: 8, borderWidth: 1, borderColor: COLORS.border, borderRadius: 4, backgroundColor: COLORS.surface },
  btnActive: { borderColor: COLORS.primary, backgroundColor: 'rgba(49,152,66,0.12)' },
  txt:       { color: COLORS.textDim, fontSize: 12, fontWeight: '900', letterSpacing: 0.8 },
  txtActive: { color: COLORS.primary },
});
