// Rewrites incoming native deep links before Expo Router tries to match them
// to a screen. Needed for the Auth0 redirect: on Android, expo-auth-session's
// openAuthSessionAsync is implemented with the same Linking APIs Router uses
// for its own navigation (see expo-web-browser docs — iOS gets a native
// ASWebAuthenticationSession intercept, Android does not), so the
// "frontend://callback?code=...&state=..." redirect reaches Router as well
// as expo-auth-session's own listener. Router has no /callback screen (that
// path only exists to satisfy Auth0's requirement for a non-bare redirect
// URI — see the comment on `redirectUri` in login.tsx) and previously showed
// "Unmatched Route" instead of the login screen. expo-auth-session's
// listener still resolves the pending sign-in regardless of where Router
// navigates, so rewriting this to the login route (rather than a screen
// that exists to display something) is enough — no auth state is read or
// needed here.
export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  try {
    if (path.includes('callback') && (path.includes('code=') || path.includes('error='))) {
      return '/login';
    }
    return path;
  } catch {
    return '/login';
  }
}
