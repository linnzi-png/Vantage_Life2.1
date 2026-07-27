// Sales-cycle timing and late-night buffer logic.
// Reporting cycle: 6:00 AM to 5:59:59 AM next day.
// Dead zone: midnight to 5:59:59 AM — previous day locked, new day not yet open.

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
 * True between midnight (00:00:00) and 5:59:59 AM local time.
 * Previous sales day is locked; new day has not opened at 6:00 AM.
 */
export function isLateNightBuffer(now: Date = new Date()): boolean {
  return now.getHours() < CYCLE_OPEN_HOUR;
}

/**
 * YYYY-MM-DD of the sales day that opens at 6:00 AM today.
 * Only meaningful when isLateNightBuffer() is true.
 */
export function getUpcomingSalesDay(now: Date = new Date()): string {
  return formatLocalDate(now);
}

/**
 * True once the clock has passed 6:00 AM on the entry's target sales_day.
 * Used to determine when a buffered entry can be flushed to the API.
 */
export function isBufferEntryEligible(salesDay: string, now: Date = new Date()): boolean {
  const today = formatLocalDate(now);
  if (salesDay < today) return true; // past day — submit immediately
  return salesDay === today && now.getHours() >= CYCLE_OPEN_HOUR;
}
