import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);
dayjs.extend(timezone);

// Times are shown in the user group's timezone (Configuration → User Group) when set.
let displayTz: string | null = null;
export function setDisplayTimezone(tz: string | null | undefined) {
  displayTz = tz || null;
}
const local = (v: string) => (displayTz ? dayjs(v).tz(displayTz) : dayjs(v));

/** "1 vehicle", "3 vehicles" */
export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
export const km = (m: number | null | undefined) => `${((m || 0) / 1000).toFixed(1)} km`;

export function duration(s: number | null | undefined) {
  const t = Math.max(0, Math.round(s || 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(t % 60).padStart(2, '0')}s`;
}

export const dateTime = (v: string | null | undefined) => (v ? local(v).format('DD MMM YYYY HH:mm') : '—');
export const time = (v: string | null | undefined) => (v ? local(v).format('HH:mm') : '—');

export function ago(v: string | null | undefined) {
  if (!v) return 'never';
  const s = (Date.now() - new Date(v).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const vehicleName = (v: { description?: string | null; device_name?: string | null; imei: string }) =>
  v.description || v.device_name || v.imei;

export function startOfDay(d: Date) {
  return dayjs(d).startOf('day').toDate();
}
export function endOfDay(d: Date) {
  return dayjs(d).endOf('day').toDate();
}
