// Guided-walkthrough step registry — one tour per RBAC tier, composed from
// shared groups. The step list IS the access guard: a tier's list simply never
// contains a screen that tier can't reach, so the tour engine needs no
// role checks of its own.
//
// Anchor rule: every anchored target must render above the fold on a fresh
// navigation to its screen. The overlay falls back to a centered card when an
// anchor is missing or scrolled out of view, so a violation degrades — it
// never blocks — but spotlights only work for above-the-fold chrome.
import { Role } from './auth';

// Bump to re-show all tours once after a meaningful revision.
// v2: Close Rate corrected to Sales / Sits, Company Health dashboard,
// Team week picker, Production History charts.
// v3: Self-Correction Window (3-day picker + correction mode on the Pulse
// tab, all tiers).
export const TOUR_VERSION = 3;

export type TourAnchorId =
  | 'dash-header'
  | 'dash-period'
  | 'dash-stats'
  | 'dash-wall'
  | 'dash-ticker'
  | 'dash-history'
  | 'pulse-stepper'
  | 'pulse-days'
  | 'pulse-upline'
  | 'shoutouts-nominate'
  | 'team-roster'
  | 'team-weeks'
  | 'team-missing'
  | 'team-nominations'
  | 'noms-header'
  | 'manager-intro'
  | 'audit-intro'
  | 'vault-health'
  | 'vault-weeks'
  | 'more-tools'
  | 'more-walkthrough';

// usePathname() values for the screens the tour can visit.
export type TourScreen =
  | '/'
  | '/pulse'
  | '/shoutouts'
  | '/team'
  | '/more'
  | '/nominations'
  | '/manager'
  | '/audit'
  | '/vault';

export interface TourStep {
  id: string;
  screen: TourScreen;
  // 'tabbar' highlights the whole bottom tab bar via a synthetic rect;
  // null renders a centered card with a full scrim (no spotlight).
  anchor: TourAnchorId | 'tabbar' | null;
  title: string;
  body: string;
  placement?: 'above' | 'below';
}

const welcome = (body: string): TourStep => ({
  id: 'welcome',
  screen: '/',
  anchor: null,
  title: 'WELCOME TO VANTAGELIFE',
  body,
});

const BASICS_FULL: TourStep[] = [
  welcome(
    "AO Premier's live victory scoreboard — your sales day, your wins, and your nightly numbers in one place. This quick tour shows you exactly how to use it. About two minutes.",
  ),
  {
    id: 'sales-day',
    screen: '/',
    anchor: 'dash-header',
    title: 'YOUR DASHBOARD',
    body: 'Your name and producer title live up here. The date pill is the open sales day. Tap the pill anytime to look back at a past day, read-only.',
  },
  {
    id: 'periods',
    screen: '/',
    anchor: 'dash-period',
    title: 'DAILY · WEEKLY · MONTHLY',
    body: 'Flip the scoreboard between today, the rolling week, and the month. The production week closes every Wednesday at 2:00 PM, when totals lock and archive.',
  },
  {
    id: 'live-stats',
    screen: '/',
    anchor: 'dash-stats',
    title: 'LIVE PRODUCTION',
    body: 'Total ALP, Sits, and Sales update live, with the swing versus yesterday. One rule to know everywhere in this app: Close Rate is Sales ÷ Sits. N1 visits (medically unqualified) are tallied separately and already left out of your Sits — they never count against you.',
  },
  {
    id: 'platinum-wall',
    screen: '/',
    anchor: 'dash-wall',
    title: 'THE PLATINUM WALL',
    body: 'Top Vets, top Rookies, and Platinum Rule honorees. Tap any name to open their contact card — call or text them straight from the app.',
  },
  {
    id: 'production-history',
    screen: '/',
    anchor: 'dash-history',
    title: 'PRODUCTION HISTORY',
    body: 'Scroll to the bottom of your dashboard for PRODUCTION HISTORY — your last 13 weeks of ALP, sales, and close rate, charted week by week.',
  },
  {
    id: 'ticker',
    screen: '/',
    anchor: 'dash-ticker',
    title: 'THE LIVE WIRE',
    body: 'Every sale in the agency scrolls across this ticker as it lands. When you close tonight, the whole team sees it here.',
  },
  {
    id: 'tabs',
    screen: '/',
    anchor: 'tabbar',
    title: 'GETTING AROUND',
    body: "Everything lives in these tabs. Next, we'll walk through the ones you'll use every day.",
  },
  {
    id: 'nightly-pulse',
    screen: '/pulse',
    anchor: 'pulse-stepper',
    title: 'YOUR NIGHTLY PULSE',
    body: "The one job you own every night: your 14 nightly numbers, entered one at a time — Sets through Gross ALP. Each step tells you exactly what counts. Hit $10K in a day and you join the Player's Club.",
  },
  {
    id: 'pulse-timing',
    screen: '/pulse',
    anchor: null,
    title: 'WHEN TO SUBMIT',
    body: 'Submit before 9:00 PM — that\'s when the warning banner turns yellow. Miss it? The "Midnight Miracle" window (midnight to 6:00 AM) still posts to the same sales day. Submit on time every night and your streak grows. 🔥',
  },
  {
    id: 'pulse-correct',
    screen: '/pulse',
    anchor: 'pulse-days',
    title: 'FIX A PAST DAY',
    body: "Typo in last night's numbers? These day chips open any of your last 3 sales days. A day that already has entries opens in correction mode — every field pre-fills with that day's totals, you fix what's wrong, and the corrected numbers become the record everywhere, Platinum Wall included.",
  },
  {
    id: 'pulse-upline',
    screen: '/pulse',
    anchor: 'pulse-upline',
    title: 'YOUR UPLINE',
    body: "Can't get your numbers in tonight? Your upline's contact card sits at the bottom of this screen, one tap away — and they can enter your numbers on your behalf.",
  },
  {
    id: 'shoutouts',
    screen: '/shoutouts',
    anchor: 'shoutouts-nominate',
    title: 'PREMIER SHOUTOUTS',
    body: "The victory feed: Player's Club hits, first deals, streaks, and Platinum Rule honors. See someone living the Platinum Rule? Tap NOMINATE and put them up for the wall.",
  },
];

// Compressed basics for tiers that already know the floor — the leadership
// tours spend their steps on leadership tools instead.
const basicsBrief = (welcomeBody: string, includeUpline: boolean): TourStep[] => [
  welcome(welcomeBody),
  {
    id: 'sales-day',
    screen: '/',
    anchor: 'dash-header',
    title: 'THE SALES DAY',
    body: 'The date pill is the open sales day. The production week locks every Wednesday at 2:00 PM. Tap the pill to review past days read-only.',
  },
  {
    id: 'live-stats',
    screen: '/',
    anchor: 'dash-stats',
    title: 'LIVE ROLLUPS',
    body: 'ALP, Sits, and Sales roll up live across everyone visible to you. Close Rate everywhere is Sales ÷ Sits — N1 visits are tallied separately and already left out of Sits, so they never drag a close rate down.',
  },
  {
    id: 'production-history',
    screen: '/',
    anchor: 'dash-history',
    title: 'PRODUCTION HISTORY',
    body: 'At the bottom of the dashboard: PRODUCTION HISTORY — 13 weeks of ALP, sales, and close rate, charted week by week.',
  },
  {
    id: 'nightly-pulse',
    screen: '/pulse',
    anchor: 'pulse-stepper',
    title: 'YOUR NIGHTLY PULSE',
    body: 'Your own 14 nightly numbers still go in here every night — before the 9:00 PM gate, or in the Midnight Miracle window (midnight–6:00 AM) at the latest.',
  },
  {
    id: 'pulse-correct',
    screen: '/pulse',
    anchor: 'pulse-days',
    title: 'FIX A PAST DAY',
    body: "The day chips open any of your last 3 sales days. A day with entries opens in correction mode — fields pre-fill with that day's totals, you restate the true numbers, and the correction flows everywhere, Platinum Wall included.",
  },
  ...(includeUpline
    ? [
        {
          id: 'pulse-upline',
          screen: '/pulse',
          anchor: 'pulse-upline',
          title: 'YOUR UPLINE',
          body: "Your upline's contact card sits at the bottom of the Pulse screen — one tap to call or text.",
        } satisfies TourStep,
      ]
    : []),
  {
    id: 'shoutouts',
    screen: '/shoutouts',
    anchor: 'shoutouts-nominate',
    title: 'PREMIER SHOUTOUTS',
    body: 'The victory feed. Tap NOMINATE to put anyone up for Platinum Rule honors.',
  },
];

const TEAM_STEPS: TourStep[] = [
  {
    id: 'team-roster',
    screen: '/team',
    anchor: 'team-roster',
    title: 'YOUR TEAM, LIVE',
    body: "Your full downline rolls up in the TEAM tab — Gross and Net ALP, sales, close rate, and alert flags per agent. Sort by any column, search by name, office, or title, and tap a row for a contact card with that agent's 13-week production history.",
  },
  {
    id: 'team-weeks',
    screen: '/team',
    anchor: 'team-weeks',
    title: 'REWIND THE WEEK',
    body: 'These chips pin any past reporting week — LIVE is now; tap a date to see the board exactly as that week closed. A pinned week is a static snapshot; tap LIVE to come back.',
  },
  {
    id: 'missing-tonight',
    screen: '/team',
    anchor: 'team-missing',
    title: 'MISSING TONIGHT',
    body: "Agents who haven't submitted their Pulse show up in the MISSING TONIGHT card. Tap ENTER ALL to walk their entries back-to-back — as their upline you can submit for anyone on your team, up to 7 sales days back.",
  },
  {
    id: 'noms-inbox',
    screen: '/team',
    anchor: 'team-nominations',
    title: 'NOMINATIONS INBOX',
    body: 'Platinum Rule nominations from your team land behind this button — the badge counts the ones that have hit the endorsement threshold.',
  },
  {
    id: 'endorse',
    screen: '/nominations',
    anchor: 'noms-header',
    title: 'ENDORSE THE WORTHY',
    body: 'Read each nomination and ENDORSE the ones that deserve the wall. Three leadership endorsements flag a nomination as ready.',
  },
];

const MGA_STEPS: TourStep[] = [
  {
    id: 'post-to-wall',
    screen: '/nominations',
    anchor: 'noms-header',
    title: 'POST TO THE WALL',
    body: 'You close the loop: once a nomination hits the endorsement threshold, POST TO PLATINUM WALL publishes it agency-wide on the Platinum Wall.',
  },
  {
    id: 'downline-history',
    screen: '/team',
    anchor: 'team-roster',
    title: 'COACH FROM THE TREND',
    body: "Open anyone on your roster and read their 13-week production history before the call — ALP, sales, and close rate, charted. History is downline-scoped: you see your whole hierarchy, and nobody above it.",
  },
  {
    id: 'hierarchy-scope',
    screen: '/',
    anchor: 'dash-stats',
    title: 'FULL-HIERARCHY SCOPE',
    body: 'Your dashboard and Team view roll up every leader and agent under you — the numbers here are your whole hierarchy, live.',
  },
];

const RGA_STEPS: TourStep[] = [
  {
    id: 'exec-tools',
    screen: '/more',
    anchor: 'more-tools',
    title: 'EXECUTIVE TOOLS',
    body: 'Your command deck lives in MORE: the Manager Command Panel, the Audit Log, and Company Health.',
  },
  {
    id: 'eraser',
    screen: '/manager',
    anchor: 'manager-intro',
    title: 'NET ALP ERASER',
    body: "Post a Net ALP correction against any agent's sales day — pick the agent, set the new Net ALP, and give a reason of 10+ characters. Gross ALP on the Platinum Wall stays untouched.",
  },
  {
    id: 'audit',
    screen: '/audit',
    anchor: 'audit-intro',
    title: 'THE AUDIT LOG',
    body: 'Nothing here is silent: every adjustment is recorded — original value, new value, delta, reason, who made it, and when.',
  },
  {
    id: 'company-health',
    screen: '/vault',
    anchor: 'vault-health',
    title: 'COMPANY HEALTH',
    body: 'Your per-office pulse: pick an office, pick a window (8 to 26 weeks or all time), and read the KPIs — period ALP, Close Rate (Sales ÷ Sits), ALP per sale — with ALP, sales, and close-rate trends charted below.',
  },
  {
    id: 'vault-snapshots',
    screen: '/vault',
    anchor: 'vault-weeks',
    title: 'ARCHIVED WEEK SNAPSHOTS',
    body: 'Below the charts live the archived week snapshots, created by each Wednesday reset. Tap two to compare them side-by-side with deltas, and EXPORT any week as a WAR-format backup.',
  },
  {
    id: 'wednesday-reset',
    screen: '/vault',
    anchor: null,
    title: 'THE WEDNESDAY RESET',
    body: "Every Wednesday at 2:00 PM Detroit time the production week locks: entries archive into the week snapshots and a fresh week opens. The reset itself is a Chief-Executive-level platform operation — there's no in-app button to trigger it.",
  },
  {
    id: 'replay',
    screen: '/more',
    anchor: 'more-walkthrough',
    title: 'REPLAY ANYTIME',
    body: "That's the full command deck. Replay this walkthrough anytime from right here.",
  },
];

const OUTRO: TourStep = {
  id: 'outro',
  screen: '/',
  anchor: null,
  title: "YOU'RE READY",
  body: 'Log your Pulse tonight, watch the wall, and get on the ticker. Replay this walkthrough anytime from MORE → HELP → App Walkthrough.',
};

export function stepsForRole(role: Role): TourStep[] {
  switch (role) {
    case 'level_1':
      return [...BASICS_FULL, OUTRO];
    case 'level_2':
      return [
        ...basicsBrief(
          "Your team's live victory scoreboard. This tour covers the basics fast, then goes deep on your team tools. About two minutes.",
          true,
        ),
        ...TEAM_STEPS,
        OUTRO,
      ];
    case 'level_3':
      return [
        ...basicsBrief(
          "Your hierarchy's live victory scoreboard. This tour covers the basics fast, then your Executive Producer tools. About two minutes.",
          true,
        ),
        ...TEAM_STEPS,
        ...MGA_STEPS,
        OUTRO,
      ];
    case 'level_4':
      return [
        ...basicsBrief(
          "The agency's live victory scoreboard, global scope. This tour covers the basics fast, then the full executive command deck. About three minutes.",
          false, // an RGA has no upline
        ),
        ...TEAM_STEPS,
        ...MGA_STEPS,
        ...RGA_STEPS,
        OUTRO,
      ];
    case 'pending':
      return [];
    case 'finance_admin':
      // No production identity, no tab bar (see (tabs)/_layout.tsx) — nothing
      // in this walkthrough applies.
      return [];
  }
}
