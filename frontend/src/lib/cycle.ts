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
