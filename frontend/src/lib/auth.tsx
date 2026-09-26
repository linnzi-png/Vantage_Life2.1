// Shared API helper + auth context for VantageLife 2.0
import React, { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { registerForPulseNotifications } from './push';
import { notify } from './dialog';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const SESSION_KEY = 'vl_session_token';

/**
 * A missing EXPO_PUBLIC_BACKEND_URL used to fail silently: every fetch()
 * below just resolved to a bare relative path like "/api/auth/me",
 * which React Native's fetch rejects with "Invalid URL: /api/auth/me" —
 * surfaced to the tester as an opaque "Unable to reach the server" alert
 * with no indication it was a build/config problem, not a network one
 * (vantagelife-feedback-db issues #24, #25). EXPO_PUBLIC_ vars are inlined
 * at bundle-build time, so this can only be caught here, at runtime, not by
 * TypeScript. Fail loudly and specifically instead.
 */
if (!BACKEND) {
  console.error(
    '[auth] EXPO_PUBLIC_BACKEND_URL is empty — this bundle was built or ' +
    'OTA-published without it. Every API call, including sign-in, will fail.'
  );
}

/**
 * Resolves `path` against BACKEND, or throws a clear, user-legible error
 * immediately if BACKEND is empty — instead of letting fetch() reject deep
 * inside with the opaque native "Invalid URL: <path>" message once it tries
 * (and fails) to parse a bare relative path.
 */
function resolveUrl(path: string): string {
  if (!BACKEND) {
    throw new Error(
      'App configuration error: server address is missing from this build. ' +
      'Please reinstall the app, or contact support if this continues.'
    );
  }
  return `${BACKEND}${path}`;
}

// The ladder (owner, 2026-09-22): level_1 (Agent) < level_sa (SA) < level_2 (GA)
// < level_3 (MGA) < level_4 (RGA). SA is its own tier, ranked 1.5, so every
// "strictly below your own tier" rule tells SA and GA apart without renumbering.
export type Role = 'level_1' | 'level_sa' | 'level_2' | 'level_3' | 'level_4' | 'pending' | 'finance_admin';

const ROLE_RANK: Record<string, number> = { level_1: 1, level_sa: 1.5, level_2: 2, level_3: 3, level_4: 4 };
/** Lowest rank that runs a team — SA and above. Use `levelNum(r) >= LEADER_MIN`,
 *  never `>= 2`, for "is this a leader" checks; `>= 2` means GA and above. */
export const LEADER_MIN = ROLE_RANK.level_sa;

/** Short tier badge: L1, SA, L2, L3, L4, FA. */
export function tierShort(role?: string | null): string {
  if (!role) return '—';
  if (role === 'level_sa') return 'SA';
  if (role === 'finance_admin') return 'FA';
  return role.replace('level_', 'L');
}

export interface AppUser {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
  role: Role;
  agent_id?: string | null;
  is_admin?: boolean;
  /** May pull the reconciliation exports. Narrower than is_admin. */
  can_export?: boolean;
  /** Shows the "Morgans Secret Sauce" Easter egg on the More tab. Menu
   *  visibility only — the sheet's route keeps its own gate. */
  secret_sauce?: boolean;
  can_switch_role?: boolean;
  /** The More-tab view switch (owner, 2026-09-19). 'full' is the account's
   *  whole reach; 'own' narrows it: a level_4 admin to their own team, an
   *  admin below level_4 to plain agent duties. Server-normalised. */
  view_mode?: ViewMode;
  /** Whether the switch is offered at all — the server's answer, never a
   *  client guess (admins with a linked producer tier only). */
  can_toggle_view?: boolean;
}

export type ViewMode = 'full' | 'own';

export interface AppAgent {
  agent_id: string;
  name: string;
  office: string;
  role: Role;
  io_role?: string;
  is_rookie?: boolean;
  ga_id?: string | null;
  // Set on team members who are not producing agents (app developer, office
  // support). They keep their RBAC tier and every read path, but the app must
  // not ask them for Nightly Numbers or file them into the production tiers.
  non_producing?: boolean;
  // States they are licensed to sell in (owner, 2026-09-24); set from the
  // More tab (self) or a leader's Team tab card. Absent = never recorded.
  licensed_states?: string[];
}

/**
 * Error carrying the HTTP status, so callers can tell an authorization denial
 * apart from a server or routing failure. Without it a 403 ("not your team")
 * and a 404 ("endpoint not deployed") are indistinguishable, and a UI that
 * hides itself on either one fails silently and unexplainably.
 */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * The exact 401 messages get_current_user() raises for a dead session
 * (backend/server.py) — as opposed to a 401 from a sign-in attempt itself
 * (a bad Apple/Google token), which must NOT bounce the user to /login while
 * they're already sitting on the login screen trying to sign in.
 */
const SESSION_EXPIRED_MESSAGES = new Set([
  'Not authenticated', 'Invalid session', 'Session expired', 'User not found',
]);

export function isSessionExpiredError(e: unknown): boolean {
  return e instanceof ApiError && SESSION_EXPIRED_MESSAGES.has(e.message);
}

// Set by AuthProvider on mount so a session-expiry discovered by any api()
// call — not just reload() — can clear the in-memory user/agent state, not
// only the stored token.
let clearAuthState: (() => void) | null = null;

// A screen far from /login (e.g. Admin Panel) used to show a bare "Not
// authenticated" alert and go nowhere — the token was dead but nothing told
// the user or sent them back to sign in. Any api()/apiUpload()/apiText()/
// apiBlob() call that hits one of the messages above now clears state, tells
// the user once, and returns them to /login — instead of leaving them stuck
// on a screen that can only fail the same way again.
let sessionExpiredShown = false;

function maybeHandleSessionExpired(message: string): void {
  if (!SESSION_EXPIRED_MESSAGES.has(message) || sessionExpiredShown) return;
  sessionExpiredShown = true;
  clearAuthState?.();
  setToken(null);
  notify('Session Expired', 'Please sign in again.');
  router.replace('/login');
  // A fresh sign-in gets a fresh token, so this is one-shot per expiry, not
  // a standing lockout — reset shortly after so a later real expiry can fire.
  setTimeout(() => { sessionExpiredShown = false; }, 3000);
}

/**
 * fetch() throws the same generic "TypeError: Network request failed" for a
 * real connectivity problem AND for failures that have nothing to do with
 * the network — e.g. React Native failing to read a picked file's local URI
 * (a stale iCloud placeholder that hasn't finished downloading, a revoked
 * cache path) before the multipart body is even built. Collapsing all of
 * that into "Unable to reach the server" left a real bug undiagnosable: a
 * WAR-report upload that failed for a local-file reason looked identical to
 * a dead connection (issue #23). This surfaces whatever detail is actually
 * available instead of guessing at connectivity.
 */
function describeFetchFailure(e: unknown, kind: 'request' | 'upload'): string {
  const err = e as { name?: string; message?: string };
  if (err.name === 'AbortError') {
    return kind === 'upload'
      ? 'The upload took too long. Please try again.'
      : 'The server took too long to respond. Please try again.';
  }
  const generic = err.message === 'Network request failed' || !err.message;
  const detail = generic ? '' : ` (${err.message})`;
  return `Unable to reach the server${detail}. Please check your connection and try again.`;
}

export async function getToken(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export async function setToken(t: string | null) {
  if (t) await AsyncStorage.setItem(SESSION_KEY, t);
  else await AsyncStorage.removeItem(SESSION_KEY);
}

/**
 * Multipart upload. Kept separate from api() because that helper hardcodes a
 * JSON content type — setting it on a FormData body strips the multipart
 * boundary and the server rejects the request. The browser/RN runtime must be
 * left to set Content-Type itself here.
 *
 * Uses a longer timeout than api(): parsing a nine-tab WAR workbook server-side
 * takes well over the 20s interactive budget.
 */
export async function apiUpload<T = any>(
  path: string,
  form: FormData,
  timeoutMs = 120000,
): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(resolveUrl(path), {
      method: 'POST',
      body: form,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (e: unknown) {
    throw new Error(describeFetchFailure(e, 'upload'));
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    maybeHandleSessionExpired(msg);
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  let res: Response;
  try {
    res = await fetch(resolveUrl(path), {
      ...opts,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (e: unknown) {
    throw new Error(describeFetchFailure(e, 'request'));
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    maybeHandleSessionExpired(msg);
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

/** Same contract as api(), for endpoints that return a file rather than JSON
 *  (the CSV export). Sends no Content-Type, so the server picks the response
 *  shape from the query string alone. */
export async function apiText(path: string): Promise<string> {
  const token = await getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  let res: Response;
  try {
    res = await fetch(resolveUrl(path), {
      headers, credentials: 'include', signal: controller.signal,
    });
  } catch (e: unknown) {
    throw new Error(describeFetchFailure(e, 'request'));
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    maybeHandleSessionExpired(msg);
    throw new ApiError(res.status, msg);
  }
  return res.text();
}

/** Binary sibling of api(), for the generated .xlsx workbook. */
export async function apiBlob(path: string): Promise<Blob> {
  const token = await getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  let res: Response;
  try {
    res = await fetch(resolveUrl(path), {
      headers, credentials: 'include', signal: controller.signal,
    });
  } catch (e: unknown) {
    throw new Error(describeFetchFailure(e, 'request'));
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    maybeHandleSessionExpired(msg);
    throw new ApiError(res.status, msg);
  }
  return res.blob();
}

interface AuthCtx {
  user: AppUser | null;
  agent: AppAgent | null;
  roleLabel: string;
  loading: boolean;
  reload: () => Promise<void>;
  signInDemo: (level: Role) => Promise<void>;
  signInApple: (identityToken: string, givenName: string | null, familyName: string | null) => Promise<void>;
  signInAuth0: (idToken: string) => Promise<void>;
  signOut: () => Promise<void>;
  deleteAccount: () => Promise<void>;
  switchRole: (role: Role) => Promise<void>;
  setViewMode: (mode: ViewMode) => Promise<void>;
  /** True while a sign-out, account deletion or tier switch is in flight, so
   *  the screens offering them can disable the row instead of firing twice. */
  accountBusy: boolean;
}

const AuthContext = createContext<AuthCtx | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [agent, setAgent] = useState<AppAgent | null>(null);
  const [loading, setLoading] = useState(true);

  // Derived, never stored. The server's `role_label` is tier-only for
  // producing agents and never sees io_role, so a Partner used to read
  // "Partner" on the dashboard and "Executive Producer" on their own profile
  // card. One expression, one title, everywhere.
  const roleLabel = accountTitle(user, agent);

  // Lets maybeHandleSessionExpired() (any api() call, not just reload())
  // clear this provider's state when it discovers a dead session.
  useEffect(() => {
    clearAuthState = () => { setUser(null); setAgent(null); };
    return () => { clearAuthState = null; };
  }, []);

  // A cold start commonly loses the very first request to a not-yet-ready
  // network stack (or a Railway cold spin-up) — that is a transient failure,
  // not proof the session is invalid. One quick retry absorbs it instead of
  // bouncing a legitimately signed-in agent to the login screen.
  const RELOAD_RETRY_DELAYS_MS = [800, 2000];

  const reload = async () => {
    const tok = await getToken();
    if (!tok) { setUser(null); setAgent(null); setLoading(false); return; }

    for (let attempt = 0; ; attempt++) {
      try {
        const r = await api<{ user: AppUser; agent: AppAgent | null }>('/api/auth/me');
        setUser(r.user); setAgent(r.agent);
        setLoading(false);
        return;
      } catch (e: unknown) {
        // Only a genuine 401 ("Not authenticated" / "Invalid session" /
        // "Session expired" — see backend get_current_user) means the stored
        // token is actually bad. Anything else — a network error, a timeout,
        // a 5xx — is transient and must not destroy a valid 7-day session:
        // doing so on every reload() failure was issue #21 (a network hiccup
        // on relaunch silently logged the agent out, and the immediate
        // re-login attempt then raced the same not-yet-ready network and
        // failed too, surfacing as a false "server unreachable" alert).
        const invalidSession = e instanceof ApiError && e.status === 401;
        if (invalidSession) {
          setUser(null); setAgent(null);
          await setToken(null);
          setLoading(false);
          return;
        }
        if (attempt < RELOAD_RETRY_DELAYS_MS.length) {
          await new Promise((res) => setTimeout(res, RELOAD_RETRY_DELAYS_MS[attempt]));
          continue;
        }
        // Retries exhausted: still couldn't reach the server. Leave the
        // token in place — this device just goes back to "not logged in"
        // for now rather than being deauthenticated; the next successful
        // reload() (or a manual sign-in, which reuses the same account)
        // recovers it without losing anything.
        setUser(null); setAgent(null);
        setLoading(false);
        return;
      }
    }
  };

  useEffect(() => {
    // Restoring the session from stored token on mount, not deriving local state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, []);

  // Register for the 9 PM escalation notifications once there's a real,
  // linked agent — no point asking for permission on a "pending" account
  // that can't submit numbers yet anyway.
  useEffect(() => {
    if (user?.agent_id) registerForPulseNotifications();
  }, [user?.agent_id]);

  const signInDemo = async (level: Role) => {
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/demo-login', {
      method: 'POST', body: JSON.stringify({ level }),
    });
    await setToken(r.session_token);
    setUser(r.user);
    await reload();
  };

  const signInApple = async (identityToken: string, givenName: string | null, familyName: string | null) => {
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/apple', {
      method: 'POST',
      body: JSON.stringify({ identity_token: identityToken, given_name: givenName, family_name: familyName }),
    });
    await setToken(r.session_token);
    setUser(r.user);
    await reload();
  };

  const signInAuth0 = async (idToken: string) => {
    // Google flow: Auth0 Universal Login (routed to the Google connection)
    // hands the app an Auth0-issued ID token, which the backend verifies.
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/auth0', {
      method: 'POST',
      body: JSON.stringify({ id_token: idToken }),
    });
    await setToken(r.session_token);
    setUser(r.user);
    await reload();
  };

  // Account-level writes run one at a time. The ref is the guard, not the
  // state: two taps in the same tick both read the same stale state value, so
  // state alone would miss the double-tap this exists for. Without it, two
  // taps on Sign Out fire two logouts, and two on the tier switcher race —
  // last response wins and the app can settle on a tier nobody chose.
  //
  // The ref holds the running promise and the second caller gets that same
  // promise back, rather than one that resolves immediately. Resolving early
  // would be a lie with teeth: `await signOut(); router.replace('/login')`
  // would navigate while the first logout was still unregistering push and
  // clearing storage, and if the person signed straight back in, the original
  // operation's setToken(null) would land on their new session and wipe it.
  const accountOpRef = useRef<Promise<void> | null>(null);
  const [accountBusy, setAccountBusy] = useState(false);
  const runAccountOp = (fn: () => Promise<void>): Promise<void> => {
    if (accountOpRef.current) return accountOpRef.current;
    const running = (async () => {
      try {
        await fn();
      } finally {
        accountOpRef.current = null;
        setAccountBusy(false);
      }
    })();
    accountOpRef.current = running;
    setAccountBusy(true);
    return running;
  };

  const signOut = () => runAccountOp(async () => {
    try { await api('/api/push/unregister', { method: 'POST' }); } catch {}
    try { await api('/api/auth/logout', { method: 'POST' }); } catch {}
    await setToken(null);
    setUser(null); setAgent(null);
  });

  const deleteAccount = () => runAccountOp(async () => {
    await api('/api/auth/account', { method: 'DELETE' });
    await setToken(null);
    setUser(null); setAgent(null);
  });

  const switchRole = (role: Role) => runAccountOp(async () => {
    // Self-service tier switcher (break-testers with the can_switch_role flag).
    // Reload after: /api/auth/me carries the admin-flag overlay and fresh agent.
    await api('/api/me/role', { method: 'POST', body: JSON.stringify({ role }) });
    await reload();
  });

  const setViewMode = (mode: ViewMode) => runAccountOp(async () => {
    // Same shape as switchRole: the server owns the value, and every screen
    // reads it from the reloaded session rather than from local state, so
    // the dashboard, the Team tab and the More tab can never disagree.
    await api('/api/me/view-mode', { method: 'POST', body: JSON.stringify({ view_mode: mode }) });
    await reload();
  });

  return (
    <AuthContext.Provider value={{ user, agent, roleLabel, loading, reload, signInDemo, signInApple, signInAuth0, signOut, deleteAccount, switchRole, setViewMode, accountBusy }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthCtx {
  const v = useContext(AuthContext);
  if (!v) throw new Error('useAuth must be inside AuthProvider');
  return v;
}

export function levelNum(role?: Role | null): number {
  if (!role) return 0;
  // finance_admin sits outside the level_1..level_4 ladder entirely — it must
  // never satisfy a level-N gate (that's what require_agent/require_level
  // enforce server-side too; see FINANCE_ADMIN_ROLE in backend/server.py).
  if (role === 'finance_admin') return 0;
  return ROLE_RANK[role] ?? 1;
}

export function isFinanceAdmin(role?: Role | null): boolean {
  return role === 'finance_admin';
}

// Client-side twins of the backend's access predicates, so a screen gate can
// never be stricter than the route it fronts. Both mirror backend/server.py
// exactly — change them together.

/** has_full_control(): level_4 OR the is_admin flag. Per owner (2026-09-01)
 *  the is_admin account holds every capability the top tier has. `is_admin` on
 *  the session payload is the server's own answer (it already folds in the
 *  ADMIN_EMAILS list), not a client guess. Use this instead of
 *  `levelNum(role) >= 4` for any screen fronting require_level4_or_admin —
 *  levelNum('finance_admin') is 0 by design, and a bare level check also locks
 *  out an is_admin account below level_4 that the server would admit. */
export function hasFullControl(user?: AppUser | null): boolean {
  return user?.is_admin === true || levelNum(user?.role) >= 4;
}

/** user_admin_active(): the admin grant as the READ surfaces should treat it.
 *  A level_4 admin keeps it in either view (their switch picks a team, not a
 *  job); an admin below level_4 who has switched to the 'own' view is, for
 *  what the app shows and offers, the agent they are. Menu visibility and
 *  action hints only — every admin route keeps honouring is_admin, so a deep
 *  link still works, and the server re-checks every write regardless. */
export function adminActive(user?: AppUser | null): boolean {
  if (user?.is_admin !== true) return false;
  if (levelNum(user.role) >= 4) return true;
  return user.view_mode !== 'own';
}

/** require_level4_or_finance_admin(): the read-only Historical Vault views
 *  additionally admit finance_admin, which sits outside the level ladder.
 *  Write paths there stay on hasFullControl alone — finance_admin never gets
 *  restore or delete. */
export function canViewVault(user?: AppUser | null): boolean {
  return hasFullControl(user) || isFinanceAdmin(user?.role);
}

// Producer-track display titles for io_role codes. Titles are display-only:
// Partner / Senior Partner holders keep their MGA- or RGA-tier access, and
// RBAC is always enforced by `role` (level_1..4), never by title.
const IO_ROLE_TITLES: Record<string, string> = {
  SA: 'Regional Producer',
  GA: 'CoExecutive Producer',
  MGA: 'Executive Producer',
  RGA: 'Chief Executive Producer',
  Partner: 'Partner',
  SeniorPartner: 'Senior Partner',
  'Senior Partner': 'Senior Partner',
  Agent: 'Agent',
  Builder: 'Builder',
  inTraining: 'In Training',
};

const TIER_TITLES: Record<string, string> = {
  level_1: 'Agent',
  level_sa: 'Regional Producer',
  level_2: 'CoExecutive Producer',
  level_3: 'Executive Producer',
  level_4: 'Chief Executive Producer',
  pending: 'Pending Approval',
  finance_admin: 'Financial Administrator',
};

// Total by construction: every call returns something renderable, so no caller
// needs a `|| role.replace(...)` fallback — those only ever fired on a null or
// unmapped role, where `.replace` on undefined threw and blanked the screen.
export function roleTitle(io_role?: string | null, role?: string | null): string {
  if (io_role && IO_ROLE_TITLES[io_role]) return IO_ROLE_TITLES[io_role];
  if (io_role) return io_role;
  if (role && TIER_TITLES[role]) return TIER_TITLES[role];
  if (role) return role.replace('level_', 'L');
  return '—';
}

/**
 * The signed-in person's own title. Mirrors how /api/auth/me builds
 * `role_label` — non-producing staff are titled by io_role, a finance admin by
 * their tier — but unlike the server it also lets a producing agent's io_role
 * win, so a Partner reads "Partner" here and not "Executive Producer".
 */
export function accountTitle(user?: AppUser | null, agent?: AppAgent | null): string {
  if (isFinanceAdmin(user?.role) && !agent?.non_producing) return TIER_TITLES.finance_admin;
  return roleTitle(agent?.io_role, user?.role);
}

export const COLORS = {
  bg: '#0D0D0D',
  surface: '#141414',
  surface2: '#1B1B1B',
  border: 'rgba(255,255,255,0.08)',
  primary: '#319842',
  secondary: '#00558C',
  gold: '#FFD700',
  orange: '#FF8C00',
  teal: '#2BB3A3',      // the SA tier, between Agent (orange) and GA (navy)
  red: '#FF3B30',
  yellow: '#EAB308',
  text: '#FFFFFF',
  textDim: '#A1A1AA',
  textMuted: '#6B7280',
};
