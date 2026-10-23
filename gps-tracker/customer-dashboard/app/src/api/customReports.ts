import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';

// ── Custom reports (/api/portal/custom-reports) ──

export interface CrEntity { key: string; label: string; kind: 'record' | 'aggregate'; parameters: string[]; default_columns: string[] }
export interface CrParameterDef { key: string; label: string; kind: string }
export interface CrMeta { entities: CrEntity[]; parameters: CrParameterDef[]; operators: { key: string; label: string }[] }
export interface CrColumnDef {
  key: string; label: string; category: string; type: 'text' | 'number' | 'datetime' | 'date' | 'link'; unit: string;
  decimals: number | null; expression?: boolean;
}
export interface CrFormat {
  apply_to: 'row_bg' | 'row_text' | 'cell_bg' | 'cell_text'; compare: 'absolute' | 'percentage'; empty_color?: string | null;
  ranges: { min: number | null; max: number | null; color: string }[];
}
export interface CrColumn { key: string; title?: string | null; sort?: 'asc' | 'desc' | null; decimals?: number | null; show_unit?: boolean; format?: CrFormat | null }
export interface CrParameter { key: string; required: boolean }
export interface CrFilter { column: string; op: string; required: boolean }
export interface CrFile { format: 'xlsx' | 'csv' | 'pdf'; csv_separator?: 'comma' | 'semicolon' | 'tab'; orientation?: 'portrait' | 'landscape'; include_parameters?: boolean }
export interface CrReportDef {
  title: string; description?: string | null; category_id?: string | null; row_entity: string; top_n?: number | null;
  columns: CrColumn[]; parameters: CrParameter[]; column_filters: CrFilter[]; file: CrFile;
}
export interface CrReport extends CrReportDef { id: string; category: string | null; row_entity_label: string; updated_at: string }
export interface CrCategory { id: string; name: string; reports: number }
/** Values a report runs with: the period, parameters and column filter values. */
export interface CrValues {
  date_from: string; date_to: string; vehicle?: string | null; vehicle_group?: string | null; driver?: string | null;
  event_type?: string[] | null; trip_events_only?: boolean | null; place?: string | null; alert_type?: string | null;
  job_status?: string | null; cost_category?: string | null;
  filters?: Record<string, { value?: number | string | null; value2?: number | string | null }>;
}
export interface CrRun {
  id: string; created_at: string; created_by: string | null; schedule: string | null; parameters: string | null;
  status: 'done' | 'failed'; error: string | null; rows: number | null; file_name: string | null; size_bytes: number | null;
}
export interface CrSchedule {
  id: string; name: string | null; is_active: boolean; frequency: 'daily' | 'weekly' | 'monthly'; send_hour: number; timezone: string;
  values: Partial<CrValues>; file_name: string | null; compress: boolean; recipients: string[]; subject: string | null; body: string | null;
  next_run_at: string | null; last_run_at: string | null; last_status: string | null;
}
export interface CrPreview {
  ready: boolean; message?: string; columns: { key: string; title: string; unit: string; type: string }[];
  rows: (string | number)[][]; styles?: { row: [string | null, string | null] | null; cells: Record<string, [string | null, string | null]> }[];
}

const B = '/api/portal/custom-reports';
export const useCrMeta = () => useQuery({ queryKey: ['cr', 'meta'], queryFn: () => api<CrMeta>(`${B}/meta`), staleTime: Infinity });
export const useCrColumns = (entity: string | null) =>
  useQuery({ queryKey: ['cr', 'columns', entity], queryFn: () => api<CrColumnDef[]>(`${B}/columns/${entity}`), enabled: !!entity });
export const useCrCategories = () => useQuery({ queryKey: ['cr', 'categories'], queryFn: () => api<CrCategory[]>(`${B}/categories`) });
export const useCrReports = () => useQuery({ queryKey: ['cr', 'reports'], queryFn: () => api<CrReport[]>(B) });
export const useCrRuns = (id: string | null) =>
  useQuery({ queryKey: ['cr', 'runs', id], queryFn: () => api<CrRun[]>(`${B}/${id}/runs`), enabled: !!id });
export const useCrSchedules = (id: string | null) =>
  useQuery({ queryKey: ['cr', 'schedules', id], queryFn: () => api<CrSchedule[]>(`${B}/${id}/schedules`), enabled: !!id });
export function useCrRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['cr'] });
}
export const CR = B;
