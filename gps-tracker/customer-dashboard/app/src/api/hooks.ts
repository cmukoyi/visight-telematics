import { useQuery } from '@tanstack/react-query';
import { api, qs } from './client';
import { getSession, saveAccess } from '../auth/session';
import type {
  Alert, Branding, Category, DataExchangeStatus, DeviceEvent, EventTypes, GroupTheme, Kpis, Me, Permission, Place,
  PortalUserRow, ReportDef, ReportSchedule, Role, SecurityGroup, Trip, TripDetail, Vehicle,
} from './types';

export const useBranding = () =>
  useQuery({ queryKey: ['branding'], queryFn: () => api<Branding>('/api/branding'), staleTime: Infinity });

export const useVehicles = () =>
  useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/api/portal/tags'), refetchInterval: 30_000 });

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

export const usePortalUsers = () =>
  useQuery({ queryKey: ['portal-users'], queryFn: () => api<PortalUserRow[]>('/api/portal/users') });

/** The signed-in user's profile and access; refreshed so role changes apply without signing out. */
export const useMe = () =>
  useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const me = await api<Me>('/api/portal/me');
      saveAccess(me.access);
      return me;
    },
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

/** can('places.manage') — from /me, falling back to what login stored. */
export function useCan() {
  const { data } = useMe();
  const access = data?.access ?? getSession().access;
  return (permission: string) => !!access && (access.is_admin || access.permissions.includes(permission));
}

/** The user group's colours, logos and timezone (null until signed in). */
export const useGroupTheme = () =>
  useQuery({
    queryKey: ['theme'],
    queryFn: () => (getSession().token ? api<GroupTheme>('/api/portal/theme') : Promise.resolve(null)),
    staleTime: 5 * 60_000,
  });

export const usePermissions = () =>
  useQuery({ queryKey: ['permissions'], queryFn: () => api<Permission[]>('/api/portal/access/permissions'), staleTime: Infinity });

export const useRoles = () => useQuery({ queryKey: ['roles'], queryFn: () => api<Role[]>('/api/portal/roles') });

export const useSecurityGroups = () =>
  useQuery({ queryKey: ['security-groups'], queryFn: () => api<SecurityGroup[]>('/api/portal/security-groups') });
