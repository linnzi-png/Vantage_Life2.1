// Sales-cycle timing.
// Reporting cycle: 6:00 AM to 5:59:59 AM next day.
// Late-night window: midnight to 5:59:59 AM. Entries in this window are the
// "Midnight Miracle" grace period for the still-open sales day and post
// immediately, exactly like a daytime entry — there is no local buffering.

export const CYCLE_OPEN_HOUR = 6; // local time

function formatLocalDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export interface PulsePayload {
  sets: number;
  sits: number;
  sales: number;
  ots_sits: number;
  ots_sales: number;
  n1: number;
  refs_obtained: number;
  ref_sits: number;
  ref_sales: number;
  pos_sits: number;
  pos_sales: number;
  vet_sits: number;
  vet_sales: number;
  gross_alp: number;
}

export interface BufferedPulse {
  payload: PulsePayload;
  sales_day: string;
  queued_at: string; // ISO 8601 timestamp
  client_entry_id?: string; // absent on entries buffered before the idempotency key existed
}

/**
 * Idempotency key for a single pulse submission. The server dedupes on it, so
 * a retry after a timeout (where the write may have committed) can't
 * double-count sales or ALP.
 */
export function makeClientEntryId(): string {
  return `ce_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

// Single source of truth for the 14 Nightly Numbers fields — shared by the
// full stepper (pulse.tsx) and the condensed quick-entry form (proxy entry),
// so labels/hints never drift between the two.
export const PULSE_FIELDS: { key: keyof PulsePayload; label: string; hint: string; type: 'int' | 'money' }[] = [
  { key: 'sets', label: 'Total Appointments (Sets)', hint: 'Total appointments booked.', type: 'int' },
  { key: 'sits', label: 'Total Sits', hint: 'Total appointments you actually ran (excludes N1).', type: 'int' },
  { key: 'sales', label: 'Total Sales', hint: 'Total closed deals today.', type: 'int' },
  { key: 'ots_sits', label: 'On Spot Sits', hint: 'Sits run on the spot (walk-ins / same-day).', type: 'int' },
  { key: 'ots_sales', label: 'On Spot Sales', hint: 'Sales closed on the spot.', type: 'int' },
  { key: 'n1', label: 'Uninsurables (N1)', hint: 'Tracked but excluded from Sits totals.', type: 'int' },
  { key: 'refs_obtained', label: 'Referrals Collected', hint: 'Referrals you collected today.', type: 'int' },
  { key: 'ref_sits', label: 'Referral Sits', hint: 'Sits run from referrals.', type: 'int' },
  { key: 'ref_sales', label: 'Referral Sales', hint: 'Sales closed from referrals.', type: 'int' },
  { key: 'pos_sits', label: 'POS Sits', hint: 'Policy Owner Service sits.', type: 'int' },
  { key: 'pos_sales', label: 'POS Sales', hint: 'Policy Owner Service sales.', type: 'int' },
  { key: 'vet_sits', label: 'Response Card / Veteran Sits', hint: 'Sits from response cards or Veteran leads.', type: 'int' },
  { key: 'vet_sales', label: 'Response Card / Veteran Sales', hint: 'Sales from response cards or Veteran leads.', type: 'int' },
  { key: 'gross_alp', label: 'Total ALP for the Day (Gross ALP)', hint: 'Annual Life Premium for the day.', type: 'money' },
];

/**
 * YYYY-MM-DD of the sales day currently open. Before 6:00 AM the previous
 * day's cycle label still applies (6 AM–5:59 AM cycle).
 */
export function currentSalesDay(now: Date = new Date()): string {
  const d = new Date(now);
  if (d.getHours() < CYCLE_OPEN_HOUR) d.setDate(d.getDate() - 1);
  return formatLocalDate(d);
}

/**
 * The last `count` sales days, newest first, starting from the currently
 * open sales day. Used by the upline quick-entry day picker — the backend
 * accepts proxy entries up to 7 sales days back (MAX_UPLINE_BUFFER_DAYS).
 */
// Matches MAX_SELF_BUFFER_DAYS on the backend: an agent may enter or correct
// their OWN numbers up to 3 sales days back. Uplines get 7 (see
// QuickEntryForm's UPLINE_WINDOW_DAYS / MAX_UPLINE_BUFFER_DAYS).
export const SELF_WINDOW_DAYS = 3;

export function recentSalesDays(count: number, now: Date = new Date()): string[] {
  const base = new Date(now);
  if (base.getHours() < CYCLE_OPEN_HOUR) base.setDate(base.getDate() - 1);
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() - i);
    out.push(formatLocalDate(d));
  }
  return out;
}

/**
 * True between midnight (00:00:00) and 5:59:59 AM local time — the Midnight
 * Miracle grace window for the still-open sales day. Used only to show an
 * urgency prompt; entries submitted in this window post immediately.
 */
export function isLateNightWindow(now: Date = new Date()): boolean {
  return now.getHours() < CYCLE_OPEN_HOUR;
}

/**
 * True once the clock has passed 6:00 AM on the entry's target sales_day.
 * Retained only to drain entries queued by older builds that used the
 * (now-removed) late-night buffer; new entries are never queued.
 */
export function isBufferEntryEligible(salesDay: string, now: Date = new Date()): boolean {
  const today = formatLocalDate(now);
  if (salesDay < today) return true; // past day — submit immediately
  return salesDay === today && now.getHours() >= CYCLE_OPEN_HOUR;
}
