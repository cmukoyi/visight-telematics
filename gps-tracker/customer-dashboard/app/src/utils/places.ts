import type { Place } from '../api/types';
import type { MapPlace } from '../components/FleetMap';

/** A polygon place's outline as [[lat, lng], ...], or null for circles / unreadable data. */
export function placeOutline(p: Pick<Place, 'shape_type' | 'coordinates'>): [number, number][] | null {
  if (p.shape_type === 'circle' || !p.coordinates) return null;
  try {
    const pts = JSON.parse(p.coordinates) as [number, number][];
    return Array.isArray(pts) && pts.length >= 3 ? pts.map(([lat, lng]) => [Number(lat), Number(lng)]) : null;
  } catch {
    return null;
  }
}

export const toMapPlace = (p: Place): MapPlace =>
  ({ id: p.id, name: p.name, lat: p.latitude, lng: p.longitude, radius: p.radius, polygon: placeOutline(p) });
