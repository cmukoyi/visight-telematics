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
}

export interface Category {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  is_active: boolean;
}

export interface Trip {
  id: string;
  imei: string;
  device_name: string | null;
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
  coordinates: [number, number][] | null;
  armed_count: number;
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
}
