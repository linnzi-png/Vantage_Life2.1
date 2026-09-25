// The states an agent may be licensed to sell in (owner, 2026-09-24). The
// server's LICENSED_STATE_CODES in backend/server.py is the authority and
// rejects anything outside it; this mirror only drives the picker. Keep the
// two lists identical when the agency's real list replaces the 50 + DC seed.
// This is a separate field from the single resident `state` used by the WAR
// export — that field has no picker in the app.
export const LICENSED_STATE_CODES: readonly string[] = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID',
  'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO',
  'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA',
  'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
];

/** "MI, OH, TX" for a card line, or the given fallback when nothing is recorded. */
export function formatLicensedStates(codes: readonly string[] | undefined | null, fallback = 'None recorded'): string {
  return codes && codes.length ? codes.join(', ') : fallback;
}
