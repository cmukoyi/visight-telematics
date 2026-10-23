import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, qs } from './client';
import type { Range } from './hooks';

// ── Vehicle Maintenance (/api/portal/maintenance) ──

export type LookupKind = 'vehicle_type' | 'workshop_chain' | 'workshop_type' | 'cost_centre';
export type JobStatus = 'Overdue' | 'Due' | 'Recommended' | 'Booked' | 'In Progress' | 'Completed';

export interface Named { id: string; name: string }
export interface LookupRow extends Named { used: number }
export interface ItemRow extends Named { types: number; is_system: boolean }
export interface MaintenanceTypeRow extends Named {
  duration_days: number; duration_hours: number; item_ids: string[]; schedules: number;
}
export interface ScheduleRow extends Named {
  type_id: string; type: string | null; starts_on: string; is_active: boolean;
  at_km: number | null; at_months: number | null; at_hours: number | null; recurring: boolean;
  every_km: number | null; every_months: number | null; every_hours: number | null;
  until_km: number | null; until_months: number | null; until_hours: number | null;
  remind_km: number; remind_days: number; remind_hours: number;
  vehicle_type_ids: string[]; imeis: string[]; vehicle_count: number;
  at: string; every: string; until: string;
}
export interface WorkshopRow extends Named {
  poi_id: string | null; place: string | null; chain_id: string | null; chain: string | null; phone: string | null;
  working_hours: string | null; image_data: string | null;
  type_ids: string[]; jobs: number;
}
export interface MaintenanceCatalog {
  vehicle_type: Named[]; workshop_chain: Named[]; workshop_type: Named[]; cost_centre: Named[];
  items: Named[]; types: MaintenanceTypeRow[]; workshops: Named[]; schedules: (Named & { type_id: string })[];
  statuses: JobStatus[];
  cost_categories: Named[];
  vehicles: { imei: string; name: string; group: string | null; type_id: string | null }[];
}
/** A saved job, or one projected from a schedule (projected: true, id "p:<schedule>:<imei>"). */
export interface JobRow {
  id: string; projected: boolean; imei: string; vehicle: string; description: string; reference: string | null;
  type_id: string | null; type: string | null; schedule_id: string | null; schedule: string | null; status: JobStatus;
  planned_start: string | null; planned_end: string | null; actual_start: string | null; actual_end: string | null;
  odometer_km: number | null; engine_hours: number | null; workshop_id: string | null; workshop: string | null;
  cost: number | null; notes?: string | null;
  due: { km: number | null; hours: number | null; date: string | null } | null;
  left: { km: number | null; hours: number | null; days: number | null } | null;
}
export interface SummaryRow {
  imei: string; vehicle: string; group: string | null; type_id: string | null;
  odometer_km: number | null; engine_hours: number | null; next: JobRow | null; previous: JobRow | null;
}
export interface OverviewRow { name: string; vehicles: number; in_workshop: number; cost: number; trend: number[] }
export interface Overview { rows: OverviewRow[]; trend_days: string[]; overdue: number; due: number; in_workshop_now: number; cost: number }
export interface CostRow {
  id: string; imei: string; vehicle: string; vehicle_type: string | null; cost_date: string;
  maintenance_id: string | null; maintenance: string | null; item_id: string | null; item: string | null;
  cost_centre_id: string | null; cost_centre: string | null; description: string | null; amount: number;
  category: string; category_label: string | null;
  amortise_from: string | null; amortise_to: string | null;
}
export interface DtcRow { code: string; description: string; category: string; recorded_at: string }

const B = '/api/portal/maintenance';
const iso = (d: Date) => d.toISOString();
const day = (d: Date) => d.toISOString().slice(0, 10);

export const useMaintenanceCatalog = (enabled = true) =>
  useQuery({ queryKey: ['mnt', 'catalog'], queryFn: () => api<MaintenanceCatalog>(`${B}/catalog`), enabled });
export const useLookups = (kind: LookupKind) =>
  useQuery({ queryKey: ['mnt', 'lookups', kind], queryFn: () => api<LookupRow[]>(`${B}/lookups/${kind}`) });
export const useMaintenanceItems = () => useQuery({ queryKey: ['mnt', 'items'], queryFn: () => api<ItemRow[]>(`${B}/items`) });
export const useMaintenanceTypes = () =>
  useQuery({ queryKey: ['mnt', 'types'], queryFn: () => api<MaintenanceTypeRow[]>(`${B}/types`) });
export const useSchedules = () => useQuery({ queryKey: ['mnt', 'schedules'], queryFn: () => api<ScheduleRow[]>(`${B}/schedules`) });
export const useWorkshops = () => useQuery({ queryKey: ['mnt', 'workshops'], queryFn: () => api<WorkshopRow[]>(`${B}/workshops`) });

export interface JobFilter {
  range: Range; status: string | null; type_id: string | null; workshop_id: string | null;
  vehicle_group: string | null; vehicle_type_id: string | null;
}
export const useJobs = (f: JobFilter) =>
  useQuery({
    queryKey: ['mnt', 'jobs', iso(f.range.from), iso(f.range.to), f.status, f.type_id, f.workshop_id, f.vehicle_group, f.vehicle_type_id],
    queryFn: () => api<JobRow[]>(`${B}/jobs${qs({ date_from: iso(f.range.from), date_to: iso(f.range.to), status: f.status,
      type_id: f.type_id, workshop_id: f.workshop_id, vehicle_group: f.vehicle_group, vehicle_type_id: f.vehicle_type_id })}`),
  });
export const useMaintenanceSummary = () =>
  useQuery({ queryKey: ['mnt', 'summary'], queryFn: () => api<SummaryRow[]>(`${B}/summary`) });
export const useOverview = (range: Range, by: 'vehicle_group' | 'vehicle_type') =>
  useQuery({ queryKey: ['mnt', 'overview', iso(range.from), iso(range.to), by],
             queryFn: () => api<Overview>(`${B}/overview${qs({ date_from: iso(range.from), date_to: iso(range.to), by })}`) });

export interface CostFilter {
  range: Range | null; vehicle_group: string | null; vehicle_type_id: string | null; type_id: string | null;
  item_id: string | null; cost_centre_id: string | null;
}
export const useCosts = (f: CostFilter) =>
  useQuery({
    queryKey: ['mnt', 'costs', f.range ? day(f.range.from) : null, f.range ? day(f.range.to) : null, f.vehicle_group,
               f.vehicle_type_id, f.type_id, f.item_id, f.cost_centre_id],
    queryFn: () => api<CostRow[]>(`${B}/costs${qs({ date_from: f.range ? day(f.range.from) : null, date_to: f.range ? day(f.range.to) : null,
      vehicle_group: f.vehicle_group, vehicle_type_id: f.vehicle_type_id, type_id: f.type_id, item_id: f.item_id,
      cost_centre_id: f.cost_centre_id })}`),
  });
export const useDtc = (imei: string | null, range: Range) =>
  useQuery({ queryKey: ['mnt', 'dtc', imei, iso(range.from), iso(range.to)], enabled: !!imei,
             queryFn: () => api<DtcRow[]>(`${B}/dtc${qs({ imei, date_from: iso(range.from), date_to: iso(range.to) })}`) });

/** Refresh everything maintenance after a change (lists, catalog, summary, overview). */
export function useMaintenanceRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['mnt'] });
}

export const STATUS_COLOR: Record<JobStatus, string> = {
  Overdue: 'red', Due: 'orange', Recommended: 'gray', Booked: 'blue', 'In Progress': 'violet', Completed: 'green',
};

export const mntApi = {
  save: <T,>(path: string, id: string | null, body: unknown) =>
    api<T>(`${B}/${path}${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', json: body }),
  remove: (path: string, id: string) => api(`${B}/${path}/${id}`, { method: 'DELETE' }),
  post: <T,>(path: string) => api<T>(`${B}/${path}`, { method: 'POST' }),
  meters: (imei: string) => api<{ odometer_km: number | null; engine_hours: number | null }>(`${B}/meters/${imei}`),
};
