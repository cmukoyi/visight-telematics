import { useQuery } from '@tanstack/react-query';
import { api, qs } from './client';
import { getSession, saveAccess } from '../auth/session';
import type {
  Alert, Branding, Category, DataExchangeStatus, DeviceEvent, EventTypes, GroupTheme, Kpis, LivePosition, Me,
  NotificationRule, Permission, Place, PortalUserRow, ReportDef, ReportSchedule, Role, RulesMeta, SecurityGroup, Trip,
  TripDetail, Vehicle, VehicleStatus, PlaceGroup, EventTypeRow, EventTypeGroup, AuditRow, AnalyticsCatalog, AnalyticsPageDef, AnalyticsExpression, AnalyticsResult, Visual, GeofenceRow, NotificationPrefs, FleetStatusRow,
} from './types';
import { cachedLook } from '../utils/look';

export const useBranding = () =>
  useQuery({ queryKey: ['branding'], queryFn: () => api<Branding>('/api/branding'), staleTime: Infinity });

export const useVehicles = () =>
  useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/api/portal/tags'), refetchInterval: 15_000 });

export const useCategories = () =>
  useQuery({ queryKey: ['categories'], queryFn: () => api<Category[]>('/api/portal/categories') });

export const usePlaces = () =>
  useQuery({ queryKey: ['places'], queryFn: () => api<Place[]>('/api/portal/locations') });

export const useKpis = (category: string | null) =>
  useQuery({ queryKey: ['kpis', category], queryFn: () => api<Kpis>(`/api/portal/dashboard/kpis${qs({ category })}`) });

export interface Range { from: Date; to: Date }

const iso = (d: Date) => d.toISOString();

export const useTrips = (range: Range, imei: string | null, enabled = true) =>
  useQuery({
    enabled,
    queryKey: ['trips', iso(range.from), iso(range.to), imei],
    queryFn: () => api<Trip[]>(`/api/portal/trips${qs({ date_from: iso(range.from), date_to: iso(range.to), imei, limit: 1000 })}`),
  });

export const fetchTrip = (id: string) => api<TripDetail>(`/api/portal/trips/${encodeURIComponent(id)}`);

export const useEventTypes = () =>
  useQuery({ queryKey: ['event-types'], queryFn: () => api<EventTypes>('/api/portal/event-types'), staleTime: Infinity });

export const useEvents = (range: Range, imei: string | null, codes: string[], enabled = true) =>
  useQuery({
    enabled,
    queryKey: ['events', iso(range.from), iso(range.to), imei, codes.join(',')],
    queryFn: () => api<{ rows: DeviceEvent[] }>(`/api/portal/events${qs({
      date_from: iso(range.from), date_to: iso(range.to), imei, codes: codes.join(','), limit: 5000,
    })}`).then((r) => r.rows),
  });

export interface InboxFilter { range: Range; status: string | null; type: string | null; imei: string | null; search: string }

export const useInbox = (f: InboxFilter) =>
  useQuery({
    queryKey: ['inbox', iso(f.range.from), iso(f.range.to), f.status, f.type, f.imei, f.search],
    queryFn: () => api<Alert[]>(`/api/portal/inbox${qs({
      date_from: iso(f.range.from), date_to: iso(f.range.to), status: f.status, alert_type: f.type, imei: f.imei, search: f.search,
    })}`),
    refetchInterval: 60_000,
  });

export const useUnreadCount = () =>
  useQuery({
    queryKey: ['unread'],
    queryFn: () => api<{ unread: number }>('/api/portal/alerts/unread-count').then((r) => r.unread),
    refetchInterval: 60_000,
  });

export const useReports = () => useQuery({ queryKey: ['reports'], queryFn: () => api<ReportDef[]>('/api/portal/reports') });

export const useSchedules = () =>
  useQuery({ queryKey: ['schedules'], queryFn: () => api<ReportSchedule[]>('/api/portal/report-schedules') });

export const useDataExchange = () =>
  useQuery({ queryKey: ['data-exchange'], queryFn: () => api<DataExchangeStatus>('/api/portal/data-exchange') });

export const usePortalUsers = (enabled = true) =>
  useQuery({ queryKey: ['portal-users'], queryFn: () => api<PortalUserRow[]>('/api/portal/users'), enabled });

/** The signed-in user's profile and access; refreshed so role changes apply without signing out. */
export const useMe = () =>
  useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const me = await api<Me>('/api/portal/me');
      saveAccess(me.access);
      return me;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    enabled: !!getSession().token,
  });

/** can('places.manage') — from /me, falling back to what login stored. can('admin'): a User Group Administrator. */
export function useCan() {
  const { data } = useMe();
  const access = data?.access ?? getSession().access;
  return (permission: string) => !!access && (access.is_admin || (permission !== 'admin' && access.permissions.includes(permission)));
}

/** The user group's colours, logos and timezone (null until signed in). */
export const useGroupTheme = () =>
  useQuery({
    queryKey: ['theme'],
    queryFn: () => (getSession().token ? api<GroupTheme>('/api/portal/theme') : Promise.resolve(null)),
    staleTime: 5 * 60_000,
  });

/** The platform name: the group's own (white label), else the last one seen in this browser, else the tenant's. */
export function usePlatformName() {
  const { data: branding } = useBranding();
  const { data: group } = useGroupTheme();
  return group?.theme_settings?.brand_name ?? (group ? null : cachedLook()?.theme_settings?.brand_name)
    ?? branding?.name ?? 'ViSight Track';
}

export const usePermissions = () =>
  useQuery({ queryKey: ['permissions'], queryFn: () => api<Permission[]>('/api/portal/access/permissions'), staleTime: Infinity });

export const useRoles = () => useQuery({ queryKey: ['roles'], queryFn: () => api<Role[]>('/api/portal/roles') });

export interface AuditFilters { date_from?: string; date_to?: string; user_id?: string | null; area?: string | null; outcome?: string | null; search?: string }
/** Configuration → Security → Audit Trail. */
export const useAudit = (f: AuditFilters, enabled = true) =>
  useQuery({ queryKey: ['audit', f], queryFn: () => api<{ rows: AuditRow[]; areas: string[] }>(`/api/portal/audit${qs({ ...f, limit: 2000 })}`), enabled });

export const useSecurityGroups = () =>
  useQuery({ queryKey: ['security-groups'], queryFn: () => api<SecurityGroup[]>('/api/portal/security-groups') });

export const useRules = (enabled = true) =>
  useQuery({ queryKey: ['notification-rules'], queryFn: () => api<NotificationRule[]>('/api/portal/notification-rules'), enabled });

export const useRulesMeta = () =>
  useQuery({ queryKey: ['notification-rules-meta'], queryFn: () => api<RulesMeta>('/api/portal/notification-rules/meta'), staleTime: Infinity });

/** One vehicle's live position and trail, polled every 5 s while `imei` is set. */
export const useLive = (imei: string | null) =>
  useQuery({
    queryKey: ['live', imei],
    queryFn: () => api<LivePosition>(`/api/portal/live${qs({ imei })}`),
    enabled: !!imei,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });

/** The Workspace details panel's data for one vehicle, refreshed every 15 s while open. */
export const useVehicleStatus = (imei: string | null) =>
  useQuery({
    queryKey: ['vehicle-status', imei],
    queryFn: () => api<VehicleStatus>(`/api/portal/vehicle-status${qs({ imei })}`),
    enabled: !!imei,
    refetchInterval: 15_000,
  });

export const usePlaceGroups = () => useQuery({ queryKey: ['place-groups'], queryFn: () => api<PlaceGroup[]>('/api/portal/place-groups') });
export const useEventTypeList = () => useQuery({ queryKey: ['event-type-list'], queryFn: () => api<EventTypeRow[]>('/api/portal/event-type-list') });
export const useEventTypeGroups = () => useQuery({ queryKey: ['event-type-groups'], queryFn: () => api<EventTypeGroup[]>('/api/portal/event-type-groups') });
export const useGeofences = () => useQuery({ queryKey: ['geofences'], queryFn: () => api<GeofenceRow[]>('/api/portal/geofences'), refetchInterval: 30_000 });
export const useNotificationPrefs = () => useQuery({ queryKey: ['notification-prefs'], queryFn: () => api<NotificationPrefs>('/api/portal/notifications') });

/** Latest event, speed, odometer and address per vehicle (Workspace vehicle grid), every 15 s while shown. */
export const useFleetStatus = (enabled: boolean) =>
  useQuery({ queryKey: ['fleet-status'], queryFn: () => api<FleetStatusRow[]>('/api/portal/fleet-status'), enabled, refetchInterval: 15_000 });

// ── Analytics ──
export const useAnalyticsCatalog = () =>
  useQuery({ queryKey: ['analytics-catalog'], queryFn: () => api<AnalyticsCatalog>('/api/portal/analytics/catalog'), staleTime: 60_000 });
export const useAnalyticsPages = () =>
  useQuery({ queryKey: ['analytics-pages'], queryFn: () => api<AnalyticsPageDef[]>('/api/portal/analytics/pages') });
export const useExpressions = () =>
  useQuery({ queryKey: ['analytics-expressions'], queryFn: () => api<AnalyticsExpression[]>('/api/portal/analytics/expressions') });

/** One visual's data for a period (and the page's vehicle group, unless the visual sets its own). */
export const useAnalyticsQuery = (v: Visual | null, range: Range, category: string | null) => {
  const body = v && v.type !== 'text' && v.measures.length ? {
    date_from: range.from.toISOString(), date_to: range.to.toISOString(), dimension: v.dimension, measures: v.measures,
    category: v.category || category || null, imei: v.imei || null, sort: v.sort || null, descending: v.descending ?? true,
    limit: v.limit || null,
  } : null;
  return useQuery({
    queryKey: ['analytics-query', body],
    queryFn: () => api<AnalyticsResult>('/api/portal/analytics/query', { method: 'POST', json: body }),
    enabled: !!body, staleTime: 60_000, placeholderData: (prev) => prev,
  });
};

/** Languages added (and active) in the admin portal. */
export const useLanguages = () =>
  useQuery({ queryKey: ['languages'], queryFn: async () => {
    const res = await fetch('/api/languages');
    return res.ok ? ((await res.json()) as { code: string; name: string }[]) : [];
  }, staleTime: 10 * 60_000 });
