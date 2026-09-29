// Guided-walkthrough state: provider, spotlight-anchor registry, per-user
// completion flags, and the first-session auto-launch. The overlay UI lives in
// src/components/TourOverlay.tsx; the step content in ./tourSteps.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, usePathname } from 'expo-router';
import { Role, useAuth } from './auth';
import { TourAnchorId, TourStep, TOUR_VERSION, stepsForRole } from './tourSteps';

// Once per person, ever (owner, 2026-09-24; batch 2, PR A). The record is
// user.tour_completed_at on the server; the device flag below is only an
// offline / in-flight guard so the tour cannot re-fire between skip() and
// the server acknowledging it, and a migration source for phones that
// finished the tour before the server knew about it. TOUR_VERSION is a
// content version for the More-tab replay and the public /tour page; it no
// longer drives the auto-launch.
//
// Why the old scheme re-launched the tour: the flag was keyed per user AND
// per role and stamped with TOUR_VERSION, so every tour revision, every
// role change (the 9/22 level_sa migration, the VIEW AS TIER switcher), a
// reinstall and a second device all counted as "never seen".
const tourKey = (userId: string, role: Role) => `vl_tour_done_${userId}_${role}`;
const ROLES_EVER: Role[] = ['pending', 'level_1', 'level_sa', 'level_2', 'level_3', 'level_4', 'finance_admin'];

async function hasLocalDoneFlag(userId: string): Promise<boolean> {
  // Any version, any role: the person has been through it once on this
  // device, which is all the server needs to know.
  try {
    const keys = ROLES_EVER.map((r) => tourKey(userId, r));
    const pairs = await AsyncStorage.multiGet(keys);
    return pairs.some(([, v]) => !!v);
  } catch {
    return false;
  }
}

async function markLocalDone(userId: string, role: Role): Promise<void> {
  try {
    await AsyncStorage.setItem(
      tourKey(userId, role),
      JSON.stringify({ v: TOUR_VERSION, completedAt: new Date().toISOString() }),
    );
  } catch {}
}

interface TourCtx {
  active: boolean;
  /** True from the moment the auto-launch effect starts asking whether this
   *  person's tour is done until it either starts the tour or decides not
   *  to. Other first-open overlays (the text-message consent card, What's
   *  New) wait on this so they never flash up and get replaced by the tour
   *  a moment later — the tour goes first on a first sign-in. */
  deciding: boolean;
  steps: TourStep[];
  index: number;
  start: (role: Role) => void; // auto-launch and manual replay; ignores the done flag
  next: () => void;
  back: () => void;
  skip: () => void; // marks done, closes in place
  finish: () => void; // marks done, returns to the dashboard, closes
  cancel: () => void; // closes WITHOUT persisting (role switch / sign-out)
  registerAnchor: (id: TourAnchorId, node: View | null) => void;
  getAnchor: (id: TourAnchorId) => View | null;
}

const TourContext = createContext<TourCtx | undefined>(undefined);

const TAB_PATHS = ['/', '/pulse', '/shoutouts', '/team', '/more'];
// finance_admin has no tab bar and no agent_id (see (tabs)/_layout.tsx) — it
// lands on /admin instead of '/', so its tour auto-launches there.
const FINANCE_ADMIN_HOME = '/admin';

export function TourProvider({ children }: { children: ReactNode }) {
  const { user, loading, markTourCompleted } = useAuth();
  const pathname = usePathname();

  const [active, setActive] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [index, setIndex] = useState(0);
  // Who the running tour belongs to — skip/finish persist against these even
  // if the auth role changed a frame earlier.
  const tourOwner = useRef<{ userId: string; role: Role } | null>(null);
  // markTourDone is async; this cache makes completion visible to the
  // auto-launch effect synchronously so it can't re-fire during the write.
  const doneCache = useRef<Set<string>>(new Set());

  const anchors = useRef<Map<TourAnchorId, View>>(new Map());
  const registerAnchor = useCallback((id: TourAnchorId, node: View | null) => {
    if (node) anchors.current.set(id, node);
    else anchors.current.delete(id);
  }, []);
  const getAnchor = useCallback((id: TourAnchorId): View | null => anchors.current.get(id) ?? null, []);

  const start = useCallback(
    (role: Role) => {
      // Defensive against the tier list on the server running ahead of this
      // bundle: an unknown role must mean "no tour", never a throw — this
      // runs from a setTimeout, where nothing above it can catch an error.
      let s: TourStep[];
      try {
        s = stepsForRole(role) ?? [];
      } catch {
        s = [];
      }
      if (s.length === 0 || !user) return;
      tourOwner.current = { userId: user.user_id, role };
      setSteps(s);
      setIndex(0);
      setActive(true);
    },
    [user],
  );

  const next = useCallback(() => setIndex((i) => Math.min(i + 1, Math.max(steps.length - 1, 0))), [steps.length]);
  const back = useCallback(() => setIndex((i) => Math.max(i - 1, 0)), []);

  const persistDone = useCallback(() => {
    const owner = tourOwner.current;
    if (!owner) return;
    doneCache.current.add(owner.userId);
    markLocalDone(owner.userId, owner.role);
    markTourCompleted().catch(() => {
      // Offline or the server is down: the local flag above keeps the tour
      // from re-firing on this device, and the next successful sign-in
      // replays the migration below and stamps the server then.
    });
  }, [markTourCompleted]);

  const skip = useCallback(() => {
    persistDone();
    setActive(false);
  }, [persistDone]);

  const finish = useCallback(() => {
    persistDone();
    setActive(false);
    // finance_admin has no dashboard to return to — (tabs)/_layout.tsx
    // bounces it straight back to /admin, so land there directly.
    router.navigate(tourOwner.current?.role === 'finance_admin' ? '/admin' : '/');
  }, [persistDone]);

  const cancel = useCallback(() => setActive(false), []);

  // Cancel (without persisting) when the signed-in identity or tier changes
  // mid-tour; the auto-launch effect below then re-evaluates for the new role.
  const identity = user ? `${user.user_id}:${user.role}` : null;
  const prevIdentity = useRef<string | null>(identity);
  useEffect(() => {
    if (identity !== prevIdentity.current) {
      prevIdentity.current = identity;
      // Reacting to the signed-in identity changing mid-tour, not deriving local state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (active) cancel();
    }
  }, [identity, active, cancel]);

  // First-sign-in auto-launch: the one condition is that the server has no
  // tour_completed_at for this person. Guards: a linked, non-pending agent
  // (never levelNum alone — levelNum('pending') is 1) sitting on a tab
  // route. finance_admin is the one exception: it carries no agent_id (no
  // production identity) and its "home" is /admin, not a tab route.
  //
  // Migration (one-time, per device): a phone that completed the tour under
  // the old device-only scheme has a local flag but no server stamp. Rather
  // than show those people the tour again after this update, the flag is
  // reported to the server and the launch skipped.
  useEffect(() => {
    if (loading || active) return;
    if (!user || user.role === 'pending') return;
    if (user.tour_completed_at) return;
    const isFinanceAdmin = user.role === 'finance_admin';
    if (!isFinanceAdmin && !user.agent_id) return;
    const onHome = isFinanceAdmin ? pathname === FINANCE_ADMIN_HOME : TAB_PATHS.includes(pathname);
    if (!onHome) return;
    const { user_id, role } = user;
    if (doneCache.current.has(user_id)) return;
    let stale = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    // Flagging the decision as in progress for the other overlays.
    setDeciding(true);
    hasLocalDoneFlag(user_id).then((seenBefore) => {
      if (stale) return;
      if (seenBefore) {
        doneCache.current.add(user_id);
        markTourCompleted().catch(() => {});
        setDeciding(false);
        return;
      }
      // Let the dashboard paint before the overlay fades in.
      timer = setTimeout(() => { start(role); setDeciding(false); }, 600);
    });
    return () => {
      stale = true;
      if (timer) clearTimeout(timer);
    };
  }, [loading, active, user, pathname, start, markTourCompleted]);

  return (
    <TourContext.Provider
      value={{ active, deciding, steps, index, start, next, back, skip, finish, cancel, registerAnchor, getAnchor }}
    >
      {children}
    </TourContext.Provider>
  );
}

export function useTour(): TourCtx {
  const v = useContext(TourContext);
  if (!v) throw new Error('useTour must be inside TourProvider');
  return v;
}
