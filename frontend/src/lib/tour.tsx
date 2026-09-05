// Guided-walkthrough state: provider, spotlight-anchor registry, per-user
// completion flags, and the first-session auto-launch. The overlay UI lives in
// src/components/TourOverlay.tsx; the step content in ./tourSteps.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, usePathname } from 'expo-router';
import { Role, useAuth } from './auth';
import { TourAnchorId, TourStep, TOUR_VERSION, stepsForRole } from './tourSteps';

// Keyed per user AND per role: signOut() leaves non-session keys behind on a
// shared device, and a promotion (or the VIEW AS TIER switcher) should
// re-trigger the higher tier's tour.
const tourKey = (userId: string, role: Role) => `vl_tour_done_${userId}_${role}`;

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null;
}

async function isTourDone(userId: string, role: Role): Promise<boolean> {
  try {
    const raw = await AsyncStorage.getItem(tourKey(userId, role));
    if (!raw) return false;
    const parsed: unknown = JSON.parse(raw);
    // A flag from an older TOUR_VERSION counts as not-done so revised tours
    // re-show once.
    return isRecord(parsed) && typeof parsed.v === 'number' && parsed.v >= TOUR_VERSION;
  } catch {
    return false;
  }
}

async function markTourDone(userId: string, role: Role): Promise<void> {
  try {
    await AsyncStorage.setItem(
      tourKey(userId, role),
      JSON.stringify({ v: TOUR_VERSION, completedAt: new Date().toISOString() }),
    );
  } catch {}
}

interface TourCtx {
  active: boolean;
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

export function TourProvider({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();

  const [active, setActive] = useState(false);
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
      const s = stepsForRole(role);
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
    doneCache.current.add(tourKey(owner.userId, owner.role));
    markTourDone(owner.userId, owner.role);
  }, []);

  const skip = useCallback(() => {
    persistDone();
    setActive(false);
  }, [persistDone]);

  const finish = useCallback(() => {
    persistDone();
    setActive(false);
    router.navigate('/');
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

  // First-session auto-launch. Guards: a linked, non-pending agent (never
  // levelNum alone — levelNum('pending') is 1) sitting on a tab route.
  useEffect(() => {
    if (loading || active) return;
    if (!user || user.role === 'pending' || !user.agent_id) return;
    if (!TAB_PATHS.includes(pathname)) return;
    const { user_id, role } = user;
    if (doneCache.current.has(tourKey(user_id, role))) return;
    let stale = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    isTourDone(user_id, role).then((done) => {
      if (stale || done) return;
      // Let the dashboard paint before the overlay fades in.
      timer = setTimeout(() => start(role), 600);
    });
    return () => {
      stale = true;
      if (timer) clearTimeout(timer);
    };
  }, [loading, active, user, pathname, start]);

  return (
    <TourContext.Provider
      value={{ active, steps, index, start, next, back, skip, finish, cancel, registerAnchor, getAnchor }}
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
