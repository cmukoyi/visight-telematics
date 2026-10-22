import { useEffect, useState } from 'react';
import {
  Alert, Button, Combobox, Group, Loader, MultiSelect, NumberInput, ScrollArea, SegmentedControl, Select, Slider, Stack,
  Text, TextInput, Textarea, useCombobox,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconArrowBackUp, IconCar, IconInfoCircle, IconSearch, IconSquare } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api, qs } from '../api/client';
import { useCan, usePlaceGroups } from '../api/hooks';
import type { GeocodeResult, Place, Vehicle } from '../api/types';
import { vehicleName } from '../utils/format';
import { placeOutline } from '../utils/places';
import type { MapPlace, MapPoint, MapRoute } from './FleetMap';

export type Shape = 'circle' | 'polygon';
export interface PlaceDraft {
  id: string | null;
  name: string;
  description: string;
  shape: Shape;
  center: [number, number] | null;
  radius: number;
  vertices: [number, number][];
  armed: string[];      // vehicle (tag) ids
  groupId?: string | null;
}

const DRAFT_COLOR = '#f59e0b';

export const newDraft = (center: [number, number] | null = null, armed: string[] = [], name = ''): PlaceDraft =>
  ({ id: null, name, description: '', shape: 'circle', center, radius: 200, vertices: [], armed });

export function draftFromPlace(p: Place): PlaceDraft {
  const outline = placeOutline(p);
  return {
    id: p.id, name: p.name, description: p.description ?? '', shape: outline ? 'polygon' : 'circle',
    center: [p.latitude, p.longitude], radius: Math.round(p.radius), vertices: outline ?? [],
    armed: p.tags_armed.map((t) => t.id), groupId: p.place_group_id,
  };
}

function distanceM([lat1, lng1]: [number, number], [lat2, lng2]: [number, number]) {
  const r = (d: number) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lng2 - lng1) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(a));
}

/** Four corners of a square of half-width `radius` metres around a point. */
export function squareAround([lat, lng]: [number, number], radius: number): [number, number][] {
  const dLat = radius / 111320;
  const dLng = radius / (111320 * Math.cos((lat * Math.PI) / 180));
  return [[lat + dLat, lng - dLng], [lat + dLat, lng + dLng], [lat - dLat, lng + dLng], [lat - dLat, lng - dLng]];
}

/** A map click while editing: move a circle's centre, or add a polygon corner. */
export const clickDraft = (d: PlaceDraft, lat: number, lng: number): PlaceDraft =>
  d.shape === 'circle' ? { ...d, center: [lat, lng] } : { ...d, vertices: [...d.vertices, [lat, lng]] };

/** Map layers showing the draft (the shape, polygon corners, and a line while there are only two). */
export function draftLayers(d: PlaceDraft | null): { place: MapPlace | null; points: MapPoint[]; routes: MapRoute[] } {
  if (!d) return { place: null, points: [], routes: [] };
  const name = d.name || 'New place';
  if (d.shape === 'circle') {
    return {
      place: d.center ? { id: 'draft', name, lat: d.center[0], lng: d.center[1], radius: d.radius } : null,
      points: d.center ? [{ id: 'centre', lat: d.center[0], lng: d.center[1], color: DRAFT_COLOR, label: 'Centre', icon: '+' }] : [],
      routes: [],
    };
  }
  return {
    place: d.vertices.length >= 3 ? { id: 'draft', name, lat: d.vertices[0][0], lng: d.vertices[0][1], radius: 0, polygon: d.vertices } : null,
    points: d.vertices.map(([lat, lng], i) => ({ id: `v${i}`, lat, lng, color: DRAFT_COLOR, label: `Corner ${i + 1}`, icon: String(i + 1) })),
    routes: d.vertices.length === 2 ? [{ id: 'draft-line', color: DRAFT_COLOR, coords: d.vertices }] : [],
  };
}

/** Points to fit the map to for the draft. */
export function draftExtent(d: PlaceDraft): [number, number][] {
  if (d.shape === 'polygon' && d.vertices.length) return d.vertices;
  return d.center ? squareAround(d.center, d.radius * 1.6) : [];
}

const isValid = (d: PlaceDraft) => d.name.trim() !== '' &&
  (d.shape === 'circle' ? !!d.center && d.radius >= 50 : d.vertices.length >= 3);

/** Address / place search (OpenStreetMap), typed with a short debounce. */
function AddressSearch({ onPick }: { onPick: (r: GeocodeResult) => void }) {
  const combobox = useCombobox();
  const [q, setQ] = useState('');
  const [debounced] = useDebouncedValue(q, 450);
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (debounced.trim().length < 3) { setResults([]); return; }
    let cancelled = false;
    setLoading(true);
    api<GeocodeResult[]>(`/api/portal/geocode${qs({ q: debounced.trim() })}`)
      .then((r) => { if (!cancelled) { setResults(r); combobox.openDropdown(); } })
      .catch((e) => !cancelled && notifications.show({ color: 'red', message: (e as Error).message }))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Combobox store={combobox} onOptionSubmit={(i) => { const r = results[Number(i)]; if (r) { onPick(r); setQ(r.label.split(',')[0]); } combobox.closeDropdown(); }}>
      <Combobox.Target>
        <TextInput label="Find an address or place" placeholder="e.g. 12 Main Road, Sandton" value={q}
                   leftSection={<IconSearch size={14} />} rightSection={loading ? <Loader size={14} /> : null}
                   onChange={(e) => { setQ(e.currentTarget.value); combobox.openDropdown(); }}
                   onFocus={() => results.length && combobox.openDropdown()} onBlur={() => combobox.closeDropdown()} />
      </Combobox.Target>
      <Combobox.Dropdown hidden={!results.length && !(debounced.length >= 3 && !loading)}>
        <Combobox.Options>
          <ScrollArea.Autosize mah={240} type="auto">
            {results.length === 0
              ? <Combobox.Empty>No matches</Combobox.Empty>
              : results.map((r, i) => <Combobox.Option key={i} value={String(i)}><Text size="sm">{r.label}</Text></Combobox.Option>)}
          </ScrollArea.Autosize>
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}

interface Props {
  draft: PlaceDraft;
  setDraft: (fn: (d: PlaceDraft | null) => PlaceDraft | null) => void;
  places: Place[];
  vehicles: Vehicle[];
  onLocate: (extent: [number, number][]) => void;
  onCancel: () => void;
  onSaved: (place: Place) => void;
}

/** The place form: name, where (address / vehicle / map click), shape and size, armed vehicles. */
export function PlaceEditor({ draft, setDraft, places, vehicles, onLocate, onCancel, onSaved }: Props) {
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const { data: placeGroups = [] } = usePlaceGroups();
  const canArm = useCan()('places.arm');
  const set = (patch: Partial<PlaceDraft>) => setDraft((d) => d && { ...d, ...patch });
  const located = vehicles.filter((v) => v.latitude && v.longitude);

  const moveTo = (lat: number, lng: number, name?: string) => {
    const next: PlaceDraft = draft.shape === 'polygon'
      ? { ...draft, center: [lat, lng], vertices: squareAround([lat, lng], draft.radius) }
      : { ...draft, center: [lat, lng] };
    if (name && !draft.name) next.name = name;
    setDraft(() => next);
    onLocate(draftExtent(next));
  };

  const save = async () => {
    if (!isValid(draft)) return;
    let body: Record<string, unknown>;
    if (draft.shape === 'circle') {
      body = { latitude: draft.center![0], longitude: draft.center![1], radius: draft.radius, shape_type: 'circle', coordinates: '' };
    } else {
      const lat = draft.vertices.reduce((s, v) => s + v[0], 0) / draft.vertices.length;
      const lng = draft.vertices.reduce((s, v) => s + v[1], 0) / draft.vertices.length;
      const radius = Math.max(50, ...draft.vertices.map((v) => distanceM([lat, lng], v)));
      body = { latitude: lat, longitude: lng, radius: Math.round(radius), shape_type: 'polygon', coordinates: JSON.stringify(draft.vertices) };
    }
    body = { ...body, name: draft.name.trim(), description: draft.description.trim() || null, place_group_id: draft.groupId ?? '' };
    setSaving(true);
    try {
      const saved = draft.id
        ? await api<Place>(`/api/portal/locations/${draft.id}`, { method: 'PUT', json: body })
        : await api<Place>('/api/portal/locations', { method: 'POST', json: body });
      const before = new Set(draft.id ? places.find((p) => p.id === draft.id)?.tags_armed.map((t) => t.id) : []);
      const after = new Set(draft.armed);
      if (canArm) for (const id of after) if (!before.has(id)) await api(`/api/portal/locations/${saved.id}/arm/${id}`, { method: 'POST' });
      if (canArm) for (const id of before) if (!after.has(id)) await api(`/api/portal/locations/${saved.id}/arm/${id}`, { method: 'DELETE' });
      await qc.invalidateQueries({ queryKey: ['places'] });
      notifications.show({ color: 'green', message: `${draft.name.trim()} saved` });
      onSaved(saved);
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not save the place', message: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="sm">
      <TextInput label="Name" placeholder="e.g. Head office depot" value={draft.name} required data-autofocus
                 onChange={(e) => set({ name: e.currentTarget.value })} />
      <AddressSearch onPick={(r) => moveTo(r.latitude, r.longitude, r.label.split(',')[0])} />
      <Select label="…or at a vehicle's position" placeholder="Choose a vehicle" searchable clearable leftSection={<IconCar size={14} />}
              data={located.map((v) => ({ value: v.id, label: vehicleName(v) }))} value={null}
              onChange={(id) => {
                const v = located.find((x) => x.id === id);
                if (v) {
                  moveTo(parseFloat(v.latitude!), parseFloat(v.longitude!));
                  if (!draft.armed.includes(v.id)) setDraft((d) => d && { ...d, armed: [...d.armed, v.id] });
                }
              }} />
      <SegmentedControl fullWidth value={draft.shape}
                        onChange={(v) => {
                          const shape = v as Shape;
                          setDraft((d) => d && ({ ...d, shape, vertices: shape === 'polygon' && !d.vertices.length && d.center ? squareAround(d.center, d.radius) : d.vertices }));
                        }}
                        data={[{ value: 'circle', label: 'Circle' }, { value: 'polygon', label: 'Polygon' }]} />
      <Alert variant="light" color="blue" icon={<IconInfoCircle size={16} />} p="xs">
        {draft.shape === 'circle'
          ? (draft.center ? 'Adjust the radius, or click the map to move the centre.' : 'Search an address, pick a vehicle, or click the map.')
          : draft.vertices.length >= 3
            ? `${draft.vertices.length} corners. Click the map to add more, or undo/clear to redraw.`
            : 'Click the map to add corners (at least 3), or start from a square around a point.'}
      </Alert>
      {draft.shape === 'circle' ? (
        <>
          <NumberInput label="Radius (metres)" min={50} max={50000} step={25} value={draft.radius} clampBehavior="blur"
                       onChange={(v) => set({ radius: Number(v) || 50 })} />
          <Slider min={50} max={2000} step={10} value={Math.min(draft.radius, 2000)} label={(v) => `${v} m`}
                  onChange={(v) => set({ radius: v })} aria-label="Radius" />
        </>
      ) : (
        <Group gap="xs">
          <Button size="xs" variant="default" leftSection={<IconSquare size={14} />} disabled={!draft.center}
                  onClick={() => set({ vertices: squareAround(draft.center!, draft.radius) })}>Square around point</Button>
          <Button size="xs" variant="default" leftSection={<IconArrowBackUp size={14} />} disabled={!draft.vertices.length}
                  onClick={() => set({ vertices: draft.vertices.slice(0, -1) })}>Undo</Button>
          <Button size="xs" variant="subtle" color="gray" disabled={!draft.vertices.length} onClick={() => set({ vertices: [] })}>Clear</Button>
        </Group>
      )}
      {placeGroups.length > 0 && (
        <Select label="Place group" placeholder="No group" clearable data={placeGroups.map((g) => ({ value: g.id, label: g.name }))}
                value={draft.groupId ?? null} onChange={(v) => set({ groupId: v })} />
      )}
      <Textarea label="Description" autosize minRows={1} value={draft.description}
                onChange={(e) => set({ description: e.currentTarget.value })} />
      <MultiSelect label="Armed vehicles" disabled={!canArm}
                   description={canArm ? 'These vehicles raise an alert when they enter or leave' : 'Your roles don’t include arming geofences'}
                   placeholder={draft.armed.length ? '' : 'Choose vehicles'} searchable clearable
                   data={vehicles.map((v) => ({ value: v.id, label: vehicleName(v) }))}
                   value={draft.armed} onChange={(v) => set({ armed: v })} />
      <Group justify="flex-end" mt="xs">
        <Button variant="default" onClick={onCancel}>Cancel</Button>
        <Button onClick={save} disabled={!isValid(draft)} loading={saving}>Save place</Button>
      </Group>
    </Stack>
  );
}
