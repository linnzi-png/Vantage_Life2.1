// The Team tab's team views (owner: MJ 2026-09-25; Linnzi 2026-09-26,
// 2026-09-29, 2026-10-02): office-wide totals for every SA, GA or MGA team,
// the best and worst team in four categories, and the caller's competition.
//
//   * A team under the caller expands to its people, using the rows
//     /api/team already returned (the screen renders them, so tapping a
//     person works exactly as it does on the people list).
//   * Any other team opens a contact card and nothing else: a total line is
//     all the caller may read about a team that is not theirs.
//   * A competitor is a card that flips to that team's Gross ALP for the
//     window and nothing more. Only one card is open at a time (FlipCard's
//     contract), and the back is mounted from the first frame, so it renders
//     sensibly with no data.
//
// Built on the batch 3 surfaces: GlowCard for the lines, FlipCard for the
// competitors. No expo-linear-gradient anywhere (the current binary lacks it).
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, roleTitle } from '../lib/auth';
import {
  BranchesResponse, BranchLine, BranchTier, BestWorst, CATEGORIES, Competitor, TIER_ROLE, TeamWindow,
  VIEW_LABEL, branchesPath, formatMoney, membersOf, namesOf, sortLines,
} from '../lib/teamViews';
import { AgentContactSheet, AgentContact } from './AgentContactSheet';
import FlipCard, { nextFlipped } from './FlipCard';
import GlowCard from './GlowCard';
import { LoadState } from './LoadState';

const COMPETITOR_W = 156;
const COMPETITOR_H = 104;
// Text on a card face stops growing at this multiple of the phone's text size, so a
// large-text setting cannot push it past the card (Linnzi, 2026-10-10).
const FACE_MAX_SCALE = 1.15;

interface MemberRow { agent_id: string; gross_alp: number }

// ---------------- a team line ----------------

interface LineProps {
  line: BranchLine;
  tier: BranchTier;
  expanded: boolean;
  onPress: (line: BranchLine) => void;
  children?: React.ReactNode;
}

// memo: a long board re-renders on every 30 s poll and on every expand, and a
// line only changes when its own figures or its open state do.
const TeamLine = memo(function TeamLine({ line, tier, expanded, onPress, children }: LineProps) {
  const yours = line.in_my_downline;
  return (
    <View style={styles.lineWrap}>
      <TouchableOpacity
        activeOpacity={0.8}
        onPress={() => onPress(line)}
        accessibilityRole="button"
        accessibilityLabel={yours
          ? `${line.name}, team ${formatMoney(line.team_gross_alp)}. ${expanded ? 'Hide' : 'Show'} the people on this team`
          : `${line.name}, team ${formatMoney(line.team_gross_alp)}. Open contact details`}
        testID={`team-line-${line.agent_id}`}
      >
        <GlowCard accent={line.team_rank === 1 && line.team_gross_alp > 0 ? COLORS.gold : COLORS.primary}
          contentStyle={styles.lineBody}>
          <View style={styles.rankWrap}>
            <Text style={[styles.rankTxt, line.team_rank === 1 && line.team_gross_alp > 0 && styles.rankTop]}>
              {line.team_gross_alp > 0 ? line.team_rank : '—'}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.lineName} numberOfLines={1}>{line.name}</Text>
            <Text style={styles.lineMeta} numberOfLines={1}>
              {roleTitle(line.io_role, TIER_ROLE[tier])} · {line.head_count} {line.head_count === 1 ? 'person' : 'people'}
            </Text>
            <Text style={styles.lineRatios} numberOfLines={1}>
              {line.team_sales} sales · {line.close_ratio}% close · {line.refs_per_sit.toFixed(2)} refs/sit
            </Text>
            <Text style={styles.lineRatios} numberOfLines={1}>
              {line.show_ratio.toFixed(1)}% show · {formatMoney(line.avg_alp)} avg ALP
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={styles.lineAlp}>{formatMoney(line.team_gross_alp)}</Text>
            <Text style={styles.lineAlpLabel}>TEAM ALP</Text>
            <Ionicons
              name={yours ? (expanded ? 'chevron-up' : 'chevron-down') : 'call-outline'}
              size={14}
              color={COLORS.textDim}
              style={{ marginTop: 6 }}
            />
          </View>
        </GlowCard>
      </TouchableOpacity>
      {expanded ? <View style={styles.members} testID={`team-line-members-${line.agent_id}`}>{children}</View> : null}
    </View>
  );
});

// ---------------- best and worst ----------------

function BestWorstPanel({ bw, office }: { bw: BestWorst; office: string }) {
  return (
    <GlowCard accent={COLORS.gold} style={styles.bwCard} contentStyle={styles.bwBody} testID={`best-worst-${office || 'all'}`}>
      <Text style={styles.bwKicker}>BEST AND WORST TEAM</Text>
      {CATEGORIES.map((c) => {
        const { best, worst } = bw?.[c.key] ?? { best: [], worst: [] };
        return (
          <View key={c.key} style={styles.bwRow} testID={`best-worst-${c.key}`}>
            <Text style={styles.bwLabel}>{c.label}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.bwBest} numberOfLines={2}>
                BEST {best.length ? `${namesOf(best)} · ${c.format(best[0].value)}` : '—'}
              </Text>
              <Text style={styles.bwWorst} numberOfLines={2}>
                WORST {worst.length ? `${namesOf(worst)} · ${c.format(worst[0].value)}` : '—'}
              </Text>
            </View>
          </View>
        );
      })}
    </GlowCard>
  );
}

// ---------------- competitors ----------------

function CompetitorRow({ competitors, viewerRole, windowLabel }: {
  competitors: Competitor[]; viewerRole?: string; windowLabel: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (competitors.length === 0) return null;
  return (
    <View style={styles.compWrap} testID="team-competitors">
      <Text style={styles.sectionKicker}>YOUR COMPETITION · TOP {competitors.length} BY TEAM ALP</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 14, paddingHorizontal: 12 }}>
        {competitors.map((c) => (
          <FlipCard
            key={c.agent_id}
            testID={`competitor-${c.agent_id}`}
            height={COMPETITOR_H}
            style={{ width: COMPETITOR_W }}
            accent={COLORS.secondary}
            flipped={open === c.agent_id}
            onFlip={() => setOpen((cur) => nextFlipped(cur, c.agent_id))}
            frontLabel={`${c.name}, ${c.office}. Show their team ALP`}
            backLabel={`${c.name} team ALP ${formatMoney(c.team_gross_alp)}. Back to the card`}
            front={() => (
              <View style={styles.compFace}>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} style={styles.compName} numberOfLines={1}>{c.name}</Text>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} style={styles.compMeta} numberOfLines={1}>{roleTitle(c.io_role, viewerRole)} · {c.office}</Text>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} style={styles.compHint}>TAP FOR TEAM ALP</Text>
              </View>
            )}
            back={() => (
              <View style={styles.compFace}>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} style={styles.compBackLabel}>TEAM ALP</Text>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} adjustsFontSizeToFit numberOfLines={1} style={styles.compAlp}>{formatMoney(c.team_gross_alp)}</Text>
                <Text maxFontSizeMultiplier={FACE_MAX_SCALE} style={styles.compHint} numberOfLines={1}>{windowLabel}</Text>
              </View>
            )}
          />
        ))}
      </ScrollView>
    </View>
  );
}

// ---------------- the view ----------------

interface Props {
  tier: BranchTier;
  window: TeamWindow;
  windowLabel: string;
  sortKey: string;
  /** The rows /api/team returned for this window, to expand a team under the caller. */
  rows: MemberRow[];
  /** Renders one person exactly as the people list does. */
  renderMember: (row: any) => React.ReactNode;
  viewerRole?: string;
  /** Changes whenever the screen has fresh rows, so the totals refresh with them. */
  refreshKey?: unknown;
}

export function TeamViews({ tier, window: win, windowLabel, sortKey, rows, renderMember, viewerRole, refreshKey }: Props) {
  const [data, setData] = useState<BranchesResponse | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [contact, setContact] = useState<AgentContact | null>(null);
  const path = branchesPath(tier, win);
  const latest = useRef(path);
  latest.current = path;

  const load = useCallback(async () => {
    const asked = path;
    try {
      const r = await api<BranchesResponse>(asked);
      // A slower answer for a tier or window the caller has already left must
      // not overwrite the one on screen.
      if (latest.current !== asked) return;
      setData(r);
      setLoadedFor(asked);
      setError(null);
    } catch (e: unknown) {
      if (latest.current !== asked) return;
      setError(e instanceof Error ? e.message : 'The team views could not be loaded.');
    }
  }, [path]);

  useEffect(() => {
    // Fetching an external API, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, refreshKey]);

  // A different tier or window is a different set of teams.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpanded(null);
  }, [path]);

  const matches = loadedFor === path;
  const onLinePress = useCallback((line: BranchLine) => {
    if (line.in_my_downline) {
      setExpanded((cur) => (cur === line.agent_id ? null : line.agent_id));
      return;
    }
    // Contact only: no agent_id, so the sheet shows no history (decision 4).
    setContact({
      name: line.name, role: line.role, io_role: line.io_role, phone: line.phone, email: line.email, office: line.office,
    });
  }, []);

  const sections = useMemo(
    () => (data?.offices ?? []).map((s) => ({ ...s, lines: sortLines(s.lines, sortKey) })),
    [data, sortKey]);
  const total = sections.reduce((n, s) => n + s.lines.length, 0);

  return (
    <View testID="team-views">
      <LoadState
        loading={!matches && !error}
        error={matches ? null : error}
        onRetry={load}
        isEmpty={matches && total === 0}
        emptyText={`No ${VIEW_LABEL[tier].toLowerCase()} in this window.`}
        loadingText="Loading team totals…"
        testID="team-views-load"
      >
        <CompetitorRow competitors={data?.competitors ?? []} viewerRole={viewerRole} windowLabel={windowLabel} />
        {sections.map((s) => (
          <View key={s.office || 'unassigned'} testID={`team-views-office-${s.office || 'unassigned'}`}>
            {sections.length > 1 ? <Text style={styles.officeHead}>{s.office || 'UNASSIGNED'}</Text> : null}
            <BestWorstPanel bw={s.best_worst} office={s.office} />
            <Text style={styles.sectionKicker}>{VIEW_LABEL[tier]} · {s.lines.length}</Text>
            {s.lines.map((line) => (
              <TeamLine
                key={line.agent_id}
                line={line}
                tier={tier}
                expanded={expanded === line.agent_id}
                onPress={onLinePress}
              >
                {expanded === line.agent_id ? (() => {
                  const people = membersOf(line, rows);
                  return people.length > 0
                    ? people.map((r) => renderMember(r))
                    : <Text style={styles.noMembers}>No one on this team has numbers in this window.</Text>;
                })() : null}
              </TeamLine>
            ))}
          </View>
        ))}
      </LoadState>
      <AgentContactSheet agent={contact} onClose={() => setContact(null)} />
    </View>
  );
}

const styles = StyleSheet.create({
  officeHead: { color: '#fff', fontWeight: '900', fontSize: 13, letterSpacing: 1.2, marginTop: 8, marginBottom: 10 },
  sectionKicker: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 1.6, marginTop: 10, marginBottom: 6 },
  lineWrap: { marginBottom: 8 },
  lineBody: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12 },
  rankWrap: { width: 26, alignItems: 'center', justifyContent: 'center' },
  rankTxt: { color: COLORS.textDim, fontSize: 14, fontWeight: '900' },
  rankTop: { color: COLORS.gold, fontSize: 17 },
  lineName: { color: '#fff', fontWeight: '800', fontSize: 14 },
  lineMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  lineRatios: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  lineAlp: { color: COLORS.primary, fontWeight: '900', fontSize: 17 },
  lineAlpLabel: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  members: { marginTop: 6, marginLeft: 10, paddingLeft: 8, borderLeftWidth: 2, borderLeftColor: COLORS.border },
  noMembers: { color: COLORS.textDim, fontSize: 12, paddingVertical: 8 },
  bwCard: { marginTop: 4, marginBottom: 4 },
  bwBody: { padding: 12 },
  bwKicker: { color: COLORS.gold, fontSize: 10, fontWeight: '900', letterSpacing: 1.8, marginBottom: 6 },
  bwRow: { flexDirection: 'row', gap: 10, paddingVertical: 5 },
  bwLabel: { width: 84, color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 0.8 },
  bwBest: { color: '#fff', fontSize: 12, fontWeight: '800' },
  bwWorst: { color: COLORS.textDim, fontSize: 12, marginTop: 1 },
  compWrap: { marginBottom: 4 },
  compFace: { flex: 1, padding: 10, justifyContent: 'center' },
  compName: { color: '#fff', fontWeight: '800', fontSize: 14 },
  compMeta: { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  compHint: { color: COLORS.textMuted, fontSize: 9, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  compBackLabel: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.4 },
  compAlp: { color: COLORS.secondary, fontWeight: '900', fontSize: 24, marginTop: 2 },
});
