import dayjs from 'dayjs';
import type { Range } from '../api/hooks';

/** Named periods for Analytics pages (in the display timezone set by setDisplayTimezone). */
export const PERIODS: { value: string; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'this_week', label: 'This week' },
  { value: 'last_week', label: 'Last week' },
  { value: 'last_7_days', label: 'Last 7 days' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_30_days', label: 'Last 30 days' },
  { value: 'last_90_days', label: 'Last 90 days' },
  { value: 'this_year', label: 'This year' },
];

export function periodRange(preset: string): Range {
  const now = dayjs();
  const day = now.startOf('day');
  const week = day.subtract((day.day() + 6) % 7, 'day');   // Monday
  switch (preset) {
    case 'today': return { from: day.toDate(), to: now.toDate() };
    case 'yesterday': return { from: day.subtract(1, 'day').toDate(), to: day.toDate() };
    case 'this_week': return { from: week.toDate(), to: now.toDate() };
    case 'last_week': return { from: week.subtract(7, 'day').toDate(), to: week.toDate() };
    case 'last_7_days': return { from: day.subtract(6, 'day').toDate(), to: now.toDate() };
    case 'last_month': return { from: now.startOf('month').subtract(1, 'month').toDate(), to: now.startOf('month').toDate() };
    case 'last_30_days': return { from: day.subtract(29, 'day').toDate(), to: now.toDate() };
    case 'last_90_days': return { from: day.subtract(89, 'day').toDate(), to: now.toDate() };
    case 'this_year': return { from: now.startOf('year').toDate(), to: now.toDate() };
    default: return { from: now.startOf('month').toDate(), to: now.toDate() };
  }
}

export const periodLabel = (preset: string, r: Range) =>
  `${PERIODS.find((p) => p.value === preset)?.label ?? 'Custom'} (${dayjs(r.from).format('D MMM YYYY')} – ${dayjs(r.to).subtract(1, 'second').format('D MMM YYYY')})`;
