// Audit Log — Level 4 only
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { api, COLORS, useAuth, hasFullControl } from '../src/lib/auth';
import { TourAnchor } from '../src/components/TourAnchor';
import { LoadState } from '../src/components/LoadState';

// /api/manager/audit returns the whole audit_log, not just ALP adjustments:
// adding, removing, reassigning and merging people are all in here, as are
// tenure, state and role changes. Only the ALP actions carry money in
// original_value/new_value — the rest carry a role name, a tenure flag, a
// state code, or nothing at all — so every field below is optional and the
// value type is whatever that action recorded.
interface Audit {
  audit_id: string; ts: string; action: string;
  agent_name?: string; changed_by_name?: string;
  original_value?: number | string | boolean | null;
  new_value?: number | string | boolean | null;
  delta?: number;
  sales_day?: string; reason?: string;
}

// The two actions whose values are Net ALP. Everything else is rendered as
// plain text: running a role like "level_3" through Math.round printed "$NaN".
const MONEY_ACTIONS = new Set(['adjust_alp', 'self_correct_pulse']);

function formatValue(v: Audit['original_value'], money: boolean): string {
  if (v === null || v === undefined || v === '') return '—';
  if (money) {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? `$${Math.round(n).toLocaleString()}` : '—';
  }
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

export default function AuditScreen() {
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<Audit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ items: Audit[] }>('/api/manager/audit');
      setItems(r.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'The audit log could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetching on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  // The header has said "Level 4 only" since this was written while the file
  // imported no role helper at all. The backend enforces /api/manager/audit,
  // so nothing leaked — but an agent who reached /audit saw the chrome and an
  // empty ledger, which reads as broken rather than as not-for-them.
  if (authLoading) {
    return (
      <View style={styles.gate}>
        <ActivityIndicator color={COLORS.primary} accessibilityLabel="Checking your access" />
      </View>
    );
  }
  // hasFullControl, not a bare level check: /api/manager/audit is gated by
  // require_level4_or_admin, and the More menu offers this screen to is_admin
  // at any tier, so a `< 4` gate showed those accounts a link that then locked
  // them out.
  if (!hasFullControl(user)) {
    return (
      <View style={styles.gate}>
        <Stack.Screen options={{ title: 'AUDIT LOG', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
        <Ionicons name="lock-closed" size={32} color={COLORS.textDim} />
        <Text style={styles.gateTxt}>The audit log is limited to RGA and admin accounts.</Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ title: 'AUDIT LOG', headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: '#fff' }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 30 }}>
        <TourAnchor id="audit-intro">
          <Text style={styles.kicker}>IMMUTABLE LEDGER</Text>
          <Text style={styles.intro}>Every Net ALP adjustment, roster change and role change is recorded with a timestamp and who made it.</Text>
        </TourAnchor>
        <LoadState
          loading={loading}
          error={error}
          onRetry={load}
          isEmpty={items.length === 0}
          emptyText="Nothing recorded yet."
          loadingText="Loading the ledger…"
          testID="audit"
        >
          {items.map((a) => {
          const money = MONEY_ACTIONS.has(a.action);
          const dropped = money && typeof a.delta === 'number' && a.delta < 0;
          // Only the ALP actions have a direction to show; a role or tenure
          // change is neither a gain nor a loss.
          const icon = money ? (dropped ? 'remove-circle' : 'add-circle') : 'swap-horizontal';
          const iconColor = money ? (dropped ? COLORS.red : COLORS.primary) : COLORS.textDim;
          const hasValues = a.original_value !== undefined || a.new_value !== undefined;
          return (
            <View key={a.audit_id} style={styles.row} testID={`audit-${a.audit_id}`}>
              <View style={styles.rowHead}>
                <Ionicons name={icon} size={16} color={iconColor} />
                {/* replace(/_/g) — the old single replace left "self set_role" */}
                <Text style={styles.action}>{a.action.replace(/_/g, ' ').toUpperCase()}</Text>
                <Text style={styles.ts}>{new Date(a.ts).toLocaleString()}</Text>
              </View>
              <Text style={styles.agent}>
                {a.agent_name || '—'}
                {a.sales_day ? <Text style={styles.dim}> · {a.sales_day}</Text> : null}
              </Text>
              {hasValues ? (
                <View style={styles.values}>
                  <View style={{ flex: 1 }}><Text style={styles.lab}>ORIGINAL</Text><Text style={styles.val}>{formatValue(a.original_value, money)}</Text></View>
                  <Ionicons name="arrow-forward" size={14} color={COLORS.textDim} />
                  <View style={{ flex: 1, alignItems: 'flex-end' }}><Text style={styles.lab}>NEW</Text><Text style={styles.val}>{formatValue(a.new_value, money)}</Text></View>
                </View>
              ) : null}
              {a.reason ? (
                <>
                  <Text style={styles.lab}>REASON</Text>
                  <Text style={styles.reason}>{`"${a.reason}"`}</Text>
                </>
              ) : null}
              <Text style={styles.by}>By {a.changed_by_name || 'system'}</Text>
            </View>
          );
          })}
        </LoadState>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  gate: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg, padding: 28, gap: 12 },
  gateTxt: { color: COLORS.textDim, fontSize: 14, textAlign: 'center' },
  kicker: { color: COLORS.orange, fontWeight: '900', fontSize: 11, letterSpacing: 2 },
  intro: { color: COLORS.textDim, fontSize: 12, marginVertical: 8 },
  empty: { color: COLORS.textMuted, marginTop: 20, textAlign: 'center' },
  row: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 3, borderLeftColor: COLORS.orange, padding: 14, borderRadius: 6, marginTop: 8 },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  action: { color: '#fff', fontWeight: '900', fontSize: 12, letterSpacing: 1, flex: 1 },
  ts: { color: COLORS.textMuted, fontSize: 10 },
  agent: { color: '#fff', fontWeight: '700', marginTop: 6 },
  dim: { color: COLORS.textDim, fontWeight: '500' },
  values: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  lab: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1.2, marginTop: 6 },
  val: { color: '#fff', fontWeight: '900', fontSize: 14 },
  reason: { color: COLORS.text, fontStyle: 'italic', fontSize: 12, marginTop: 4 },
  by: { color: COLORS.textMuted, fontSize: 10, marginTop: 6 },
});
