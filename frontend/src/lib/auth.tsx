// Shared API helper + auth context for VantageLife 2.0
import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { registerForPulseNotifications } from './push';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const SESSION_KEY = 'vl_session_token';

/**
 * A missing EXPO_PUBLIC_BACKEND_URL used to fail silently: every fetch()
 * below just resolved to a bare relative path like "/api/auth/session",
 * which React Native's fetch rejects with "Invalid URL: /api/auth/session" —
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

export type Role = 'level_1' | 'level_2' | 'level_3' | 'level_4' | 'pending' | 'finance_admin';

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
  can_switch_role?: boolean;
}

export interface AppAgent {
  agent_id: string;
  name: string;
  office: string;
  role: Role;
  io_role?: string;
  is_rookie?: boolean;
  ga_id?: string | null;
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
  /** TEMPORARY: see EMERGENT_AUTH_URL in backend/server.py — remove once the
   * OTA rollout to signInAuth0 is confirmed complete on the fleet. */
  signInGoogleSession: (sessionId: string) => Promise<void>;
  signOut: () => Promise<void>;
  deleteAccount: () => Promise<void>;
  switchRole: (role: Role) => Promise<void>;
}

const AuthContext = createContext<AuthCtx | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [agent, setAgent] = useState<AppAgent | null>(null);
  const [roleLabel, setRoleLabel] = useState<string>('');
  const [loading, setLoading] = useState(true);

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
        const r = await api<{ user: AppUser; agent: AppAgent | null; role_label: string }>('/api/auth/me');
        setUser(r.user); setAgent(r.agent); setRoleLabel(r.role_label);
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

  useEffect(() => { reload(); }, []);

  // Register for the 9 PM escalation notifications once there's a real,
  // linked agent — no point asking for permission on a "pending" account
  // that can't submit numbers yet anyway.
  useEffect(() => {
    if (user?.agent_id) registerForPulseNotifications();
  }, [user?.agent_id]);

  const signInDemo = async (level: Role) => {
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string; role_label: string }>('/api/auth/demo-login', {
      method: 'POST', body: JSON.stringify({ level }),
    });
    await setToken(r.session_token);
    setUser(r.user); setRoleLabel(r.role_label);
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

  const signInGoogleSession = async (sessionId: string) => {
    // TEMPORARY: the Emergent portal redirects back to the app with a
    // session_id; exchange it via the temporary /auth/session fallback. Used
    // only while login.tsx's AUTH0_CONFIGURED is false (Auth0 tenant not set
    // up yet, or this exact build predates the migration).
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/session', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
    await setToken(r.session_token);
    setUser(r.user);
    await reload();
  };

  const signOut = async () => {
    try { await api('/api/push/unregister', { method: 'POST' }); } catch {}
    try { await api('/api/auth/logout', { method: 'POST' }); } catch {}
    await setToken(null);
    setUser(null); setAgent(null); setRoleLabel('');
  };

  const deleteAccount = async () => {
    await api('/api/auth/account', { method: 'DELETE' });
    await setToken(null);
    setUser(null); setAgent(null); setRoleLabel('');
  };

  const switchRole = async (role: Role) => {
    // Self-service tier switcher (break-testers with the can_switch_role flag).
    // Reload after: /api/auth/me carries the admin-flag overlay and fresh agent.
    await api('/api/me/role', { method: 'POST', body: JSON.stringify({ role }) });
    await reload();
  };

  return (
    <AuthContext.Provider value={{ user, agent, roleLabel, loading, reload, signInDemo, signInApple, signInAuth0, signInGoogleSession, signOut, deleteAccount, switchRole }}>
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
  return parseInt(role.split('_')[1] || '1', 10);
}

export function isFinanceAdmin(role?: Role | null): boolean {
  return role === 'finance_admin';
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
  level_2: 'CoExecutive Producer',
  level_3: 'Executive Producer',
  level_4: 'Chief Executive Producer',
  pending: 'Pending Approval',
  finance_admin: 'Financial Administrator',
};

export function roleTitle(io_role?: string | null, role?: string | null): string {
  if (io_role && IO_ROLE_TITLES[io_role]) return IO_ROLE_TITLES[io_role];
  if (io_role) return io_role;
  if (role && TIER_TITLES[role]) return TIER_TITLES[role];
  return '';
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
  red: '#FF3B30',
  yellow: '#EAB308',
  text: '#FFFFFF',
  textDim: '#A1A1AA',
  textMuted: '#6B7280',
};
