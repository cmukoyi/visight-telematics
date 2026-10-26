import { useQuery } from '@tanstack/react-query';
import { api, qs } from './client';
import type { Range } from './hooks';

// ── Breakdowns logged in the mobile app (/api/portal/breakdowns) ──

export interface BreakdownFlag { level: 'warn' | 'info'; text: string }
export interface BreakdownEvidence {
  verdict: 'consistent' | 'check' | 'unconfirmed'; flags: BreakdownFlag[];
  moved_km: number | null; furthest_m: number | null; ignition_on_s: number; trips: number; trip_km: number; max_speed: number;
  phone_gap_m: number | null; vehicle_position: [number, number] | null; reports: number; last_report: string | null;
  track?: [number, number][];
}
export interface BreakdownPhase { phase: string; at: string; lat: number | null; lng: number | null }
export interface Breakdown {
  id: string; imei: string; vehicle: string; job_id: string | null; reported_by: string | null; driver: string | null; cause: string | null;
  started_at: string; ended_at: string | null; downtime_s: number; status: 'active' | 'resolved';
  latitude: number | null; longitude: number | null; accuracy: number | null; location: string | null;
  end_latitude: number | null; end_longitude: number | null;
  phases: BreakdownPhase[]; notes: string | null; review: 'accepted' | 'disputed' | null; review_note: string | null; reviewed_by: string | null;
  evidence: BreakdownEvidence;
}

const B = '/api/portal/breakdowns';
export const useBreakdowns = (range: Range, imei: string | null) =>
  useQuery({ queryKey: ['mnt', 'breakdowns', range.from.toISOString(), range.to.toISOString(), imei], refetchInterval: 30_000,
             queryFn: () => api<Breakdown[]>(`${B}${qs({ date_from: range.from.toISOString(), date_to: range.to.toISOString(), imei })}`) });
export const useBreakdown = (id: string | null) =>
  useQuery({ queryKey: ['mnt', 'breakdown', id], enabled: !!id, queryFn: () => api<Breakdown>(`${B}/${id}`) });
export const reviewBreakdown = (id: string, review: Breakdown['review'], note: string) =>
  api<Breakdown>(`${B}/${id}/review`, { method: 'PUT', json: { review, note } });
