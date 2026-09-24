// Static coaching reference for uplines/leaders, shown at the bottom of an
// agent's card. Deliberately NOT wired to this agent's live numbers (per
// owner decision, 2026-09) — it's a fixed toolkit a leader can read straight
// off the four stats above (Close Ratio, Show Ratio, Sits/Appointments, ALP per
// Sale) and decide for themselves which apply. Dynamic "your close rate is
// low, try X" recommendations are a later phase, not this one.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS } from '../lib/auth';

interface TipGroup {
  metric: string;
  tips: string[];
}

const GROUPS: TipGroup[] = [
  {
    metric: 'CLOSE RATIO (Sales ÷ Sits)',
    tips: [
      "Trending low? Sit in on 2-3 live presentations before assuming it's a lead problem — it usually isn't.",
      'Role-play the actual close, not the whole pitch. Most reps who know the product still fumble the exact moment they ask for the sale.',
      "Split close ratio by lead source (referral vs. cold vs. response card). A lopsided drop tells you it's one source, not the agent's overall skill.",
    ],
  },
  {
    metric: 'SHOW RATIO ((Sits + N1) ÷ Sets)',
    tips: [
      "A low show ratio is usually a confirmation problem, not a selling problem — check whether appointments get confirmed the day before AND morning-of.",
      'Look at who set the appointment (the agent vs. a dialer vs. a referral). Show ratio often splits sharply by who booked it.',
      "Sits strong but sales weak? That's a close-ratio issue — don't coach the wrong stage of the funnel.",
    ],
  },
  {
    metric: 'SITS OUT OF APPOINTMENTS (raw counts)',
    tips: [
      'A wide gap between Sets and Sits (lots booked, few run) points at bad lead data or a scheduling habit — check both before blaming effort.',
      "Watch the gap week over week. A sudden widening usually traces back to one new lead source or one day of the week.",
    ],
  },
  {
    metric: 'AVERAGE ALP PER SALE',
    tips: [
      'Low ALP/sale with a healthy close ratio often means the agent is closing but underselling — check whether they run a full needs analysis or default to the cheapest plan.',
      "Compare this agent's ALP/sale against a top performer's. The gap is usually in how thoroughly needs get uncovered, not in “better closing.”",
      'High ALP/sale but low volume can mean the agent is cherry-picking bigger cases and passing on smaller, faster closes — worth a pipeline-balance conversation.',
    ],
  },
];

export function CoachingTips() {
  return (
    <View style={styles.section} testID="coaching-tips">
      <View style={styles.headRow}>
        <Text style={styles.kicker}>COACHING TOOLKIT</Text>
        <View style={styles.badge}><Text style={styles.badgeTxt}>FOR LEADERS</Text></View>
      </View>
      <Text style={styles.subnote}>
        A static reference, not tied to this agent’s numbers yet — read the four stats above and pick what applies.
      </Text>
      {GROUPS.map((g) => (
        <View key={g.metric} style={styles.group}>
          <Text style={styles.metricLabel}>{g.metric}</Text>
          {g.tips.map((t, i) => (
            <View key={i} style={styles.tipRow}>
              <Text style={styles.bullet}>•</Text>
              <Text style={styles.tipTxt}>{t}</Text>
            </View>
          ))}
        </View>
      ))}
      <View style={styles.footerNote}>
        <Text style={styles.footerTxt}>
          Look at two metrics together before drawing a conclusion — e.g. low close ratio + high show ratio usually
          means a presentation problem, while low close ratio + low show ratio usually means a lead-quality or
          scheduling problem. Confirm with the agent directly before assuming which stage needs work.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 14, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 12 },
  headRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  kicker: { color: COLORS.primary, fontWeight: '900', fontSize: 10, letterSpacing: 1.4 },
  badge: {
    backgroundColor: 'rgba(255,215,0,0.14)', borderWidth: 1, borderColor: COLORS.gold,
    borderRadius: 3, paddingHorizontal: 6, paddingVertical: 2,
  },
  badgeTxt: { color: COLORS.gold, fontSize: 8, fontWeight: '900', letterSpacing: 1 },
  subnote: { color: COLORS.textMuted, fontSize: 10, marginTop: 6, fontStyle: 'italic' },
  group: { marginTop: 12 },
  metricLabel: { color: '#fff', fontSize: 11, fontWeight: '900', letterSpacing: 0.5, marginBottom: 6 },
  tipRow: { flexDirection: 'row', gap: 6, marginBottom: 5, paddingRight: 4 },
  bullet: { color: COLORS.secondary, fontSize: 12, lineHeight: 17 },
  tipTxt: { color: COLORS.textDim, fontSize: 12, lineHeight: 17, flex: 1 },
  footerNote: {
    marginTop: 10, backgroundColor: COLORS.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.border, padding: 10,
  },
  footerTxt: { color: COLORS.textMuted, fontSize: 10.5, lineHeight: 15, fontStyle: 'italic' },
});
