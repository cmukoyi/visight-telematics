import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import Map, { AttributionControl, Layer, MapRef, Marker, NavigationControl, Popup, ScaleControl, Source } from 'react-map-gl/maplibre';
import type { StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { SegmentedControl, useComputedColorScheme } from '@mantine/core';
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
  /** Extra padding (px) kept clear when fitting, e.g. for a docked panel at the bottom. */
  fitPadding?: { top: number; bottom: number; left: number; right: number };
}

const OSM_FALLBACK: StyleSpecification = {
  version: 8,
  sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256,
    attribution: '© OpenStreetMap contributors' } },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

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
  { vehicles = [], routes = [], points = [], places = [], selectedVehicleId, onVehicleClick, fitPadding }, ref,
) {
  const mapRef = useRef<MapRef>(null);
  const scheme = useComputedColorScheme('dark');
  const { data: branding } = useBranding();
  const [style, setStyle] = useState<'streets' | 'satellite'>('streets');
  const [popup, setPopup] = useState<MapPoint | null>(null);

  const mapStyle = useMemo(() => {
    const key = branding?.maptilerKey;
    if (!key) return OSM_FALLBACK;
    const name = style === 'satellite' ? 'hybrid' : scheme === 'dark' ? 'streets-v2-dark' : 'streets-v2';
    return `https://api.maptiler.com/maps/${name}/style.json?key=${key}`;
  }, [branding?.maptilerKey, style, scheme]);

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
        coordinates: [p.polygon && p.polygon.length > 2 ? p.polygon.map(([lat, lng]) => [lng, lat]) : circlePolygon(p.lat, p.lng, p.radius)] },
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
                          onChange={(v) => setStyle(v as 'streets' | 'satellite')}
                          data={[{ label: 'Map', value: 'streets' }, { label: 'Satellite', value: 'satellite' }]} />
      )}
    </div>
  );
});
