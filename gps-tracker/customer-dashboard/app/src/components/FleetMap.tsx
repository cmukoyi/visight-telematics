import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import Map, { AttributionControl, Layer, MapRef, Marker, NavigationControl, Popup, ScaleControl, Source } from 'react-map-gl/maplibre';
import type { StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { SegmentedControl } from '@mantine/core';
import { useBranding } from '../api/hooks';
import { STATUS } from '../theme';
import classes from './FleetMap.module.css';

export interface MapVehicle { id: string; name: string; lat: number; lng: number; status: 'active' | 'idle' | 'offline'; heading?: number | null }
export interface MapRoute { id: string; color: string; coords: [number, number][] }
export interface MapPoint { id: string; lat: number; lng: number; color: string; label: string; detail?: string; icon?: string }
export interface MapPlace { id: string; name: string; lat: number; lng: number; radius: number; polygon?: [number, number][] | null }

export interface FleetMapHandle { fit: (points: [number, number][]) => void }

interface Props {
  vehicles?: MapVehicle[];
  routes?: MapRoute[];
  points?: MapPoint[];
  places?: MapPlace[];
  selectedVehicleId?: string | null;
  onVehicleClick?: (id: string) => void;
  /** Called with the clicked position (e.g. to draw a place); the cursor becomes a crosshair. */
  onMapClick?: (lat: number, lng: number) => void;
  /** Extra padding (px) kept clear when fitting, e.g. for a docked panel at the bottom. */
  fitPadding?: { top: number; bottom: number; left: number; right: number };
}

const OSM_FALLBACK: StyleSpecification = {
  version: 8,
  sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256,
    attribution: '© OpenStreetMap contributors' } },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

type BaseMap = 'streets' | 'osm' | 'satellite';
const BASEMAP_KEY = 'vt-basemap';

function savedBaseMap(): BaseMap {
  try {
    const v = localStorage.getItem(BASEMAP_KEY);
    return v === 'osm' || v === 'satellite' ? v : 'streets';
  } catch { return 'streets'; }
}

function circlePolygon(lat: number, lng: number, radiusM: number, steps = 48): [number, number][] {
  const out: [number, number][] = [];
  const dLat = radiusM / 111320;
  const dLng = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    out.push([lng + dLng * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return out;
}

export const FleetMap = forwardRef<FleetMapHandle, Props>(function FleetMap(
  { vehicles = [], routes = [], points = [], places = [], selectedVehicleId, onVehicleClick, onMapClick, fitPadding }, ref,
) {
  const mapRef = useRef<MapRef>(null);
  const { data: branding } = useBranding();
  const [style, setStyle] = useState<BaseMap>(savedBaseMap);
  const chooseStyle = (v: BaseMap) => {
    setStyle(v);
    try { localStorage.setItem(BASEMAP_KEY, v); } catch { /* storage blocked */ }
  };
  const [popup, setPopup] = useState<MapPoint | null>(null);

  const mapStyle = useMemo(() => {
    const key = branding?.maptilerKey;
    // The map stays light in both app themes so roads and routes stand out.
    if (!key || style === 'osm') return OSM_FALLBACK;
    return `https://api.maptiler.com/maps/${style === 'satellite' ? 'hybrid' : 'streets-v2'}/style.json?key=${key}`;
  }, [branding?.maptilerKey, style]);

  const pad = fitPadding ?? { top: 60, bottom: 60, left: 60, right: 60 };
  useImperativeHandle(ref, () => ({
    fit(pts) {
      const map = mapRef.current;
      if (!map || !pts.length) return;
      if (pts.length === 1) {
        map.flyTo({ center: [pts[0][1], pts[0][0]], zoom: 14, duration: 600 });
        return;
      }
      const lats = pts.map((p) => p[0]);
      const lngs = pts.map((p) => p[1]);
      map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
        { padding: pad, maxZoom: 16, duration: 600 });
    },
  }), [pad]);

  const routeData = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: routes.filter((r) => r.coords.length > 1).map((r) => ({
      type: 'Feature' as const, properties: { color: r.color },
      geometry: { type: 'LineString' as const, coordinates: r.coords.map(([lat, lng]) => [lng, lat]) },
    })),
  }), [routes]);

  const placeData = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: places.map((p) => ({
      type: 'Feature' as const, properties: { name: p.name },
      geometry: { type: 'Polygon' as const,
        coordinates: [p.polygon && p.polygon.length > 2
          ? [...p.polygon, p.polygon[0]].map(([lat, lng]) => [lng, lat])   // GeoJSON rings are closed
          : circlePolygon(p.lat, p.lng, p.radius)] },
    })),
  }), [places]);

  useEffect(() => { setPopup(null); }, [points]);

  return (
    <div className={classes.wrap}>
      <Map
        ref={mapRef}
        initialViewState={{ latitude: -26.2, longitude: 28.05, zoom: 9 }}
        mapStyle={mapStyle}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        cursor={onMapClick ? 'crosshair' : undefined}
        onClick={onMapClick ? (e) => onMapClick(e.lngLat.lat, e.lngLat.lng) : undefined}
      >
        <NavigationControl position="top-right" />
        <ScaleControl position="bottom-right" />
        <AttributionControl compact position="bottom-left" />

        <Source id="places" type="geojson" data={placeData}>
          <Layer id="places-fill" type="fill" paint={{ 'fill-color': '#7c3aed', 'fill-opacity': 0.12 }} />
          <Layer id="places-line" type="line" paint={{ 'line-color': '#7c3aed', 'line-width': 2 }} />
        </Source>

        <Source id="routes" type="geojson" data={routeData}>
          <Layer id="routes-casing" type="line" layout={{ 'line-join': 'round', 'line-cap': 'round' }}
                 paint={{ 'line-color': '#ffffff', 'line-width': 7, 'line-opacity': 0.85 }} />
          <Layer id="routes-line" type="line" layout={{ 'line-join': 'round', 'line-cap': 'round' }}
                 paint={{ 'line-color': ['get', 'color'], 'line-width': 4 }} />
        </Source>

        {places.map((p) => (
          <Marker key={`pl-${p.id}`} latitude={p.lat} longitude={p.lng} anchor="center">
            <div className={classes.placeLabel}>{p.name}</div>
          </Marker>
        ))}

        {points.map((pt) => (
          <Marker key={pt.id} latitude={pt.lat} longitude={pt.lng} anchor="center"
                  onClick={(e) => { e.originalEvent.stopPropagation(); setPopup(pt); }}>
            <div className={classes.point} style={{ background: pt.color }} title={pt.label}>{pt.icon ?? ''}</div>
          </Marker>
        ))}

        {vehicles.map((v) => (
          <Marker key={v.id} latitude={v.lat} longitude={v.lng} anchor="bottom"
                  onClick={(e) => { e.originalEvent.stopPropagation(); onVehicleClick?.(v.id); }}>
            <div className={`${classes.vehicle} ${v.id === selectedVehicleId ? classes.selected : ''}`}>
              <span className={classes.dot} style={{ background: STATUS[v.status] }} />
              <span className={classes.vehicleName}>{v.name}</span>
            </div>
          </Marker>
        ))}

        {popup && (
          <Popup latitude={popup.lat} longitude={popup.lng} onClose={() => setPopup(null)} closeOnClick={false}
                 offset={14} maxWidth="280px" className={classes.popup}>
            <strong>{popup.label}</strong>
            {popup.detail && <div className={classes.popupDetail}>{popup.detail}</div>}
          </Popup>
        )}
      </Map>
      {branding?.maptilerKey && (
        <SegmentedControl className={classes.styleSwitch} size="xs" value={style}
                          onChange={(v) => chooseStyle(v as BaseMap)}
                          data={[{ label: 'Map', value: 'streets' }, { label: 'OpenStreetMap', value: 'osm' }, { label: 'Satellite', value: 'satellite' }]} />
      )}
    </div>
  );
});
