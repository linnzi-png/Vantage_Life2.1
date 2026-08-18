// Shared API helper + auth context for VantageLife 2.0
import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { registerForPulseNotifications } from './push';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const SESSION_KEY = 'vl_session_token';

export type Role = 'level_1' | 'level_2' | 'level_3' | 'level_4' | 'pending';

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
    res = await fetch(`${BACKEND}${path}`, {
      method: 'POST',
      body: form,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (e: unknown) {
    const aborted = (e as { name?: string }).name === 'AbortError';
    throw new Error(aborted ? 'The upload took too long. Please try again.' : 'Unable to reach the server. Please check your connection and try again.');
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
    res = await fetch(`${BACKEND}${path}`, {
      ...opts,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (e: unknown) {
    // Surface a human-readable message instead of "TypeError: Network request failed".
    const aborted = (e as { name?: string }).name === 'AbortError';
    throw new Error(aborted ? 'The server took too long to respond. Please try again.' : 'Unable to reach the server. Please check your connection and try again.');
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
    res = await fetch(`${BACKEND}${path}`, {
      headers, credentials: 'include', signal: controller.signal,
    });
  } catch (e: unknown) {
    const aborted = (e as { name?: string }).name === 'AbortError';
    throw new Error(aborted
      ? 'The server took too long to respond. Please try again.'
      : 'Unable to reach the server. Please check your connection and try again.');
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
    res = await fetch(`${BACKEND}${path}`, {
      headers, credentials: 'include', signal: controller.signal,
    });
  } catch (e: unknown) {
    const aborted = (e as { name?: string }).name === 'AbortError';
    throw new Error(aborted
      ? 'The server took too long to respond. Please try again.'
      : 'Unable to reach the server. Please check your connection and try again.');
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
  signInGoogleSession: (sessionId: string) => Promise<void>;
  signInGoogleIdToken: (idToken: string) => Promise<void>;
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

  const reload = async () => {
    try {
      const tok = await getToken();
      if (!tok) { setUser(null); setAgent(null); setLoading(false); return; }
      const r = await api<{ user: AppUser; agent: AppAgent | null; role_label: string }>('/api/auth/me');
      setUser(r.user); setAgent(r.agent); setRoleLabel(r.role_label);
    } catch {
      setUser(null); setAgent(null);
      await setToken(null);
    } finally {
      setLoading(false);
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

  const signInGoogleSession = async (sessionId: string) => {
    // Native Google flow: the Emergent portal redirects back to the app with a
    // session_id; exchange it exactly like the web path does.
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/session', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
    await setToken(r.session_token);
    setUser(r.user);
    await reload();
  };

  const signInGoogleIdToken = async (idToken: string) => {
    // Direct Google flow: the app got an ID token from Google itself and the
    // backend verifies it — no Emergent proxy in the path.
    setLoading(true);
    const r = await api<{ user: AppUser; session_token: string }>('/api/auth/google', {
      method: 'POST',
      body: JSON.stringify({ id_token: idToken }),
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
    <AuthContext.Provider value={{ user, agent, roleLabel, loading, reload, signInDemo, signInApple, signInGoogleSession, signInGoogleIdToken, signOut, deleteAccount, switchRole }}>
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
  return parseInt(role.split('_')[1] || '1', 10);
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
