export interface Branding {
  name: string;
  product: string;
  domain: string;
  supportEmail: string;
  primaryColor: string;
  tagline: string;
  maptilerKey: string | null;
}

export interface Vehicle {
  id: string;
  imei: string;
  device_name: string | null;
  device_model: string | null;
  description: string | null;
  tag_type: string | null;
  is_active: boolean;
  last_seen: string | null;
  latitude: string | null;
  longitude: string | null;
  battery_level: number | null;
  package_id: string | null;
  package_name: string | null;
  expiry_date: string | null;
  days_remaining: number | null;
  activation_date: string | null;
  category_id: string | null;
  category_name: string | null;
  activity_status: 'active' | 'idle' | 'offline';
  attributes: Record<string, unknown> | null;
}

export const VEHICLE_DETAILS = ['registration', 'make', 'model', 'year', 'driver'] as const;
export type VehicleDetail = typeof VEHICLE_DETAILS[number];

/** make / model / year / registration / driver from the vehicle's attributes. */
export function detail(v: Pick<Vehicle, 'attributes'>, key: VehicleDetail): string {
  const a = v.attributes?.[key] as { value?: unknown } | undefined;
  return a && a.value != null ? String(a.value) : '';
}

export interface Category {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  is_active: boolean;
  security_group_id: string | null;
}

export interface Trip {
  id: string;
  imei: string;
  device_name: string | null;
  driver: string | null;
  start_address: string | null;
  end_address: string | null;
  status: 'open' | 'closed';
  start_reason: string;
  close_reason: string | null;
  started_at: string;
  ended_at: string | null;
  start: [number, number] | null;
  end: [number, number] | null;
  distance_m: number;
  duration_s: number;
  max_speed: number;
  avg_speed: number | null;
  point_count: number;
  speeding_count: number;
  harsh_acceleration_count: number;
  harsh_braking_count: number;
  harsh_cornering_count: number;
  idling_count: number;
}

export interface IoValue {
  id: number;
  name: string;
  display: string;
}

export interface TripEvent {
  id: number;
  code: string | null;
  label: string;
  kind: 'trip' | 'position' | 'alert' | 'info';
  recorded_at: string;
  latitude: number | null;
  longitude: number | null;
  speed: number | null;
  io: IoValue[];
}

export interface TripDetail extends Trip {
  points: [number, number, number, string][];
  events: TripEvent[];
}

export interface DeviceEvent extends TripEvent {
  imei: string;
  device_name: string;
  trip_id: string | null;
  odometer_km: number | null;
}

export interface EventTypes {
  categories: { key: string; label: string }[];
  events: { code: string; label: string; category: string; kind: string }[];
}

export interface Place {
  id: string;
  name: string;
  description: string | null;
  address: string | null;
  latitude: number;
  longitude: number;
  radius: number;
  shape_type: 'circle' | 'polygon' | string;
  coordinates: string | null;    // JSON [[lat, lng], ...] for polygons
  armed_count: number;
  tags_armed: { id: string; imei: string; label: string }[];
  place_group_id: string | null;
  notes?: string | null;
}

export interface Alert {
  id: string;
  alert_type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
  tag_id: string | null;
  tag_label: string | null;
  tag_imei: string | null;
  meta_data: Record<string, unknown>;
}

export interface WeekStats {
  trips: number;
  distance_km: number;
  driving_hours: number;
  avg_trip_km: number;
}

export interface Kpis {
  vehicles: number;
  current_week: WeekStats;
  previous_week: WeekStats;
}

export interface ReportDef {
  key: string;
  title: string;
  category: string;
  description: string;
}

export interface ReportResult {
  columns: string[];
  rows: (string | number | null)[][];
}

export interface ReportSchedule {
  id: string;
  report_key: string;
  report_title: string;
  name: string | null;
  frequency: 'daily' | 'weekly' | 'monthly';
  file_format: 'xlsx' | 'csv';
  recipients: string[];
  imei: string | null;
  category: string | null;
  timezone: string;
  send_hour: number;
  is_active: boolean;
  next_run_at: string;
  last_run_at: string | null;
  last_status: string | null;
}

export interface DataExchangeStatus {
  linked: boolean;
  exchange_key?: string;
  reseller_name?: string;
  linked_at?: string;
  devices_routed?: number;
  devices_pending?: number;
}

export interface PortalUserRow {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  is_active: boolean;
  is_group_admin: boolean;
  role_id: string | null;
  security_group_id: string | null;
  expires_at: string | null;
  created_at: string | null;
  last_login_at: string | null;
  last_active_at: string | null;
}

export interface Me {
  portal_user: PortalUserRow;
  usergroup: { id: string; name: string } | null;
  effective_features: string[];
  access: import('../auth/session').Access;
}

export interface Permission {
  key: string;
  label: string;
  section: string;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_admin: boolean;
  is_system: boolean;
  user_count: number;
}

export interface SecurityGroup {
  id: string;
  name: string;
  description: string | null;
  vehicle_groups: string[];
  user_count: number;
}

export interface GroupTheme {
  name: string | null;
  logo_data: string | null;
  logo_dark_data: string | null;
  report_logo_data: string | null;
  theme_primary: string | null;
  theme_accent: string | null;
  timezone: string | null;
  history_retention_days?: number | null;
}

export interface NotificationRule {
  id: string;
  name: string;
  rule_type: string;
  rule_type_label: string;
  category: string | null;
  place_ids: string[];
  place_group_ids: string[];
  event_group_id: string | null;
  on_entry: boolean;
  on_exit: boolean;
  email_enabled: boolean;
  email_recipients: string[];
  email_message: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface RulesMeta {
  rule_types: { value: string; label: string }[];
  placeholders: { key: string; label: string }[];
  default_message: string;
}

export interface LivePosition {
  imei: string;
  position: {
    latitude: number; longitude: number; speed: number; heading: number | null; recorded_at: string;
    received_at: string | null; ignition: boolean | null; event: string;
  } | null;
  trip: { id: string; started_at: string; distance_km: number; max_speed: number; duration_s: number } | null;
  trail: [number, number][];
}

export interface GeocodeResult {
  label: string;
  latitude: number;
  longitude: number;
}

export interface VehicleStatus {
  imei: string;
  last_report: string | null;
  last_event: string | null;
  position: {
    latitude: number; longitude: number; speed: number; heading: number | null; satellites: number | null;
    recorded_at: string; address: string | null;
  } | null;
  readings: { id: number; key: string; name: string; value: unknown; display: string }[];
  iccid: string | null;
  today: { trips: number; distance_km: number; driving_s: number };
}

export interface PlaceGroup { id: string; name: string; color: string | null; place_count: number }

export interface EventTypeRow {
  id: number; code: string; default_label: string; label: string; custom_label: string | null; color: string | null;
  category: string; category_label: string; kind: string;
}

export interface EventTypeGroup { id: string; name: string; codes: string[]; rule_count: number }

export interface GeofenceRow {
  poi_id: string; place: string; tag_id: string; imei: string; vehicle: string;
  armed_at: string | null; inside: boolean | null; checked_at: string | null;
}

export interface NotificationPrefs {
  alerts_enabled: boolean; notify_geofence_exit: boolean; notify_battery_low: boolean; notify_offline: boolean;
  notify_via_email: boolean; notification_emails: string[] | null;
}
