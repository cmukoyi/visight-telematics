import type { Vehicle } from '../api/types';
import type { MapVehicle } from '../components/FleetMap';
import { vehicleName } from '../utils/format';

export const ALL_VEHICLES = '__all__';

export function inGroup(v: Vehicle, group: string) {
  return group === ALL_VEHICLES || v.category_name === group;
}

export function toMapVehicle(v: Vehicle): MapVehicle | null {
  const lat = v.latitude ? parseFloat(v.latitude) : NaN;
  const lng = v.longitude ? parseFloat(v.longitude) : NaN;
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
  return { id: v.imei, name: vehicleName(v), lat, lng, status: v.activity_status };
}
