import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Group, MultiSelect, NumberInput, Paper, ScrollArea,
  SegmentedControl, Slider, Stack, Text, TextInput, Textarea, Title, Tooltip, UnstyledButton,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconArrowBackUp, IconInfoCircle, IconMapPin, IconPencil, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCan, usePlaces, useVehicles } from '../api/hooks';
import type { Place } from '../api/types';
import { FleetMap, type FleetMapHandle, type MapPlace, type MapPoint, type MapRoute } from '../components/FleetMap';
import { vehicleName } from '../utils/format';
import { placeOutline, toMapPlace } from '../utils/places';
import classes from './PlacesPage.module.css';

type Shape = 'circle' | 'polygon';
interface Draft {
  id: string | null;
  name: string;
  description: string;
  shape: Shape;
  center: [number, number] | null;
  radius: number;
  vertices: [number, number][];
  armed: string[];      // vehicle (tag) ids
}

const DRAFT_COLOR = '#f59e0b';
const emptyDraft = (): Draft => ({ id: null, name: '', description: '', shape: 'circle', center: null, radius: 200, vertices: [], armed: [] });

function distanceM([lat1, lng1]: [number, number], [lat2, lng2]: [number, number]) {
  const r = (d: number) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lng2 - lng1) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(a));
}

function fromPlace(p: Place): Draft {
  const outline = placeOutline(p);
  return {
    id: p.id, name: p.name, description: p.description ?? '', shape: outline ? 'polygon' : 'circle',
    center: [p.latitude, p.longitude], radius: Math.round(p.radius), vertices: outline ?? [],
    armed: p.tags_armed.map((t) => t.id),
  };
}

export function PlacesPage() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('places.manage');
  const mapRef = useRef<FleetMapHandle>(null);
  const { data: places = [] } = usePlaces();
  const { data: vehicles = [] } = useVehicles();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);

  const listed = places.filter((p) => !search || `${p.name} ${p.address ?? ''}`.toLowerCase().includes(search.toLowerCase()));

  // Map: every place, with the one being edited replaced by the draft
  const mapPlaces: MapPlace[] = useMemo(() => {
    const out = places.filter((p) => p.id !== draft?.id).map(toMapPlace);
    if (draft?.shape === 'circle' && draft.center) {
      out.push({ id: 'draft', name: draft.name || 'New place', lat: draft.center[0], lng: draft.center[1], radius: draft.radius });
    } else if (draft?.shape === 'polygon' && draft.vertices.length >= 3) {
      const [lat, lng] = draft.vertices[0];
      out.push({ id: 'draft', name: draft.name || 'New place', lat, lng, radius: 0, polygon: draft.vertices });
    }
    return out;
  }, [places, draft]);
  const draftPoints: MapPoint[] = draft?.shape === 'polygon'
    ? draft.vertices.map(([lat, lng], i) => ({ id: `v${i}`, lat, lng, color: DRAFT_COLOR, label: `Point ${i + 1}`, icon: String(i + 1) }))
    : [];
  const draftLine: MapRoute[] = draft?.shape === 'polygon' && draft.vertices.length === 2
    ? [{ id: 'draft-line', color: DRAFT_COLOR, coords: draft.vertices }] : [];

  const focus = (p: Place) => {
    setSelected(p.id);
    const outline = placeOutline(p);
    if (outline) mapRef.current?.fit(outline);
    else {
      const d = p.radius / 111320;
      mapRef.current?.fit([[p.latitude - d, p.longitude - d], [p.latitude + d, p.longitude + d]]);
    }
  };
  useEffect(() => {
    if (places.length && !draft) mapRef.current?.fit(places.map((p) => [p.latitude, p.longitude]));
  }, [places.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const onMapClick = (lat: number, lng: number) => {
    if (!draft) return;
    setDraft((d) => d && (d.shape === 'circle' ? { ...d, center: [lat, lng] } : { ...d, vertices: [...d.vertices, [lat, lng]] }));
  };

  const valid = !!draft && draft.name.trim() !== '' &&
    (draft.shape === 'circle' ? !!draft.center && draft.radius >= 50 : draft.vertices.length >= 3);

  const save = async () => {
    if (!draft || !valid) return;
    let body: Record<string, unknown>;
    if (draft.shape === 'circle') {
      body = { latitude: draft.center![0], longitude: draft.center![1], radius: draft.radius, shape_type: 'circle', coordinates: '' };
    } else {
      const lat = draft.vertices.reduce((s, v) => s + v[0], 0) / draft.vertices.length;
      const lng = draft.vertices.reduce((s, v) => s + v[1], 0) / draft.vertices.length;
      const radius = Math.max(50, ...draft.vertices.map((v) => distanceM([lat, lng], v)));
      body = { latitude: lat, longitude: lng, radius: Math.round(radius), shape_type: 'polygon', coordinates: JSON.stringify(draft.vertices) };
    }
    body = { ...body, name: draft.name.trim(), description: draft.description.trim() || null };
    setSaving(true);
    try {
      const saved = draft.id
        ? await api<Place>(`/api/portal/locations/${draft.id}`, { method: 'PUT', json: body })
        : await api<Place>('/api/portal/locations', { method: 'POST', json: body });
      const before = new Set(draft.id ? places.find((p) => p.id === draft.id)?.tags_armed.map((t) => t.id) : []);
      const after = new Set(draft.armed);
      for (const id of after) if (!before.has(id)) await api(`/api/portal/locations/${saved.id}/arm/${id}`, { method: 'POST' });
      for (const id of before) if (!after.has(id)) await api(`/api/portal/locations/${saved.id}/arm/${id}`, { method: 'DELETE' });
      await qc.invalidateQueries({ queryKey: ['places'] });
      notifications.show({ color: 'green', message: `${draft.name.trim()} saved` });
      setSelected(saved.id);
      setDraft(null);
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not save the place', message: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const remove = (p: Place) => modals.openConfirmModal({
    title: `Delete “${p.name}”?`,
    children: <Text size="sm">Vehicles armed to this place will stop raising entry and exit alerts for it.</Text>,
    labels: { confirm: 'Delete place', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => {
      try {
        await api(`/api/portal/locations/${p.id}`, { method: 'DELETE' });
        qc.invalidateQueries({ queryKey: ['places'] });
        if (draft?.id === p.id) setDraft(null);
      } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
    },
  });

  return (
    <div className={classes.root}>
      <Stack gap={4} mb="md">
        <Breadcrumbs>
          <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
          <Text size="sm">Places</Text>
        </Breadcrumbs>
        <Group justify="space-between">
          <Title order={2}>Places</Title>
          {manage && !draft && (
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setDraft(emptyDraft())}>Add place</Button>
          )}
        </Group>
      </Stack>

      <div className={classes.body}>
        <Paper withBorder className={classes.side}>
          {draft ? (
            <ScrollArea className={classes.scroll} type="auto">
              <Stack p="md" gap="sm">
                <Text fw={650}>{draft.id ? 'Edit place' : 'New place'}</Text>
                <TextInput label="Name" placeholder="e.g. Head office depot" value={draft.name} required data-autofocus
                           onChange={(e) => { const v = e.currentTarget.value; setDraft((d) => d && { ...d, name: v }); }} />
                <Textarea label="Description" autosize minRows={2} value={draft.description}
                          onChange={(e) => { const v = e.currentTarget.value; setDraft((d) => d && { ...d, description: v }); }} />
                <SegmentedControl fullWidth value={draft.shape}
                                  onChange={(v) => setDraft((d) => d && { ...d, shape: v as Shape })}
                                  data={[{ value: 'circle', label: 'Circle' }, { value: 'polygon', label: 'Polygon' }]} />
                <Alert variant="light" color="blue" icon={<IconInfoCircle size={16} />} p="xs">
                  {draft.shape === 'circle'
                    ? (draft.center ? 'Click the map to move the centre.' : 'Click the map to place the centre.')
                    : `Click the map to add corners (${draft.vertices.length} so far, at least 3).`}
                </Alert>
                {draft.shape === 'circle' ? (
                  <>
                    <NumberInput label="Radius (metres)" min={50} max={50000} step={25} value={draft.radius} clampBehavior="blur"
                                 onChange={(v) => setDraft((d) => d && { ...d, radius: Number(v) || 50 })} />
                    <Slider min={50} max={2000} step={10} value={Math.min(draft.radius, 2000)} label={(v) => `${v} m`}
                            onChange={(v) => setDraft((d) => d && { ...d, radius: v })} aria-label="Radius" />
                  </>
                ) : (
                  <Group gap="xs">
                    <Button size="xs" variant="default" leftSection={<IconArrowBackUp size={14} />} disabled={!draft.vertices.length}
                            onClick={() => setDraft((d) => d && { ...d, vertices: d.vertices.slice(0, -1) })}>Undo point</Button>
                    <Button size="xs" variant="subtle" color="gray" disabled={!draft.vertices.length}
                            onClick={() => setDraft((d) => d && { ...d, vertices: [] })}>Clear</Button>
                  </Group>
                )}
                <MultiSelect label="Armed vehicles" description="These vehicles raise an alert when they enter or leave this place"
                             placeholder={draft.armed.length ? '' : 'Choose vehicles'} searchable clearable
                             data={vehicles.map((v) => ({ value: v.id, label: vehicleName(v) }))}
                             value={draft.armed} onChange={(v) => setDraft((d) => d && { ...d, armed: v })} />
                <Group justify="flex-end" mt="xs">
                  <Button variant="default" onClick={() => setDraft(null)}>Cancel</Button>
                  <Button onClick={save} disabled={!valid} loading={saving}>Save place</Button>
                </Group>
              </Stack>
            </ScrollArea>
          ) : (
            <>
              <div className={classes.searchBar}>
                <TextInput size="xs" placeholder="Search places" leftSection={<IconSearch size={14} />} value={search}
                           onChange={(e) => setSearch(e.currentTarget.value)} />
              </div>
              <ScrollArea className={classes.scroll} type="auto">
                {listed.length === 0 && (
                  <Stack align="center" gap={4} p="xl">
                    <IconMapPin size={32} opacity={0.4} />
                    <Text size="sm" c="dimmed" ta="center">
                      {places.length ? 'No places match.' : manage ? 'No places yet. Add one to start geofencing.' : 'No places yet.'}
                    </Text>
                  </Stack>
                )}
                {listed.map((p) => (
                  <UnstyledButton key={p.id} className={`${classes.row} ${selected === p.id ? classes.active : ''}`} onClick={() => focus(p)}>
                    <Group justify="space-between" wrap="nowrap" align="flex-start">
                      <div style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} truncate>{p.name}</Text>
                        <Text size="xs" c="dimmed" truncate>
                          {placeOutline(p) ? 'Polygon' : `Circle · ${Math.round(p.radius)} m`}{p.address ? ` · ${p.address}` : ''}
                        </Text>
                        <Group gap={4} mt={6}>
                          {p.tags_armed.length === 0
                            ? <Badge size="xs" variant="outline" color="gray">No vehicles armed</Badge>
                            : p.tags_armed.slice(0, 3).map((t) => <Badge key={t.id} size="xs" variant="light">{t.label}</Badge>)}
                          {p.tags_armed.length > 3 && <Badge size="xs" variant="light" color="gray">+{p.tags_armed.length - 3}</Badge>}
                        </Group>
                      </div>
                      {manage && (
                        <Group gap={2} wrap="nowrap">
                          <Tooltip label="Edit"><ActionIcon size="sm" variant="subtle" aria-label="Edit place"
                            onClick={(e) => { e.stopPropagation(); focus(p); setDraft(fromPlace(p)); }}><IconPencil size={15} /></ActionIcon></Tooltip>
                          <Tooltip label="Delete"><ActionIcon size="sm" variant="subtle" color="red" aria-label="Delete place"
                            onClick={(e) => { e.stopPropagation(); remove(p); }}><IconTrash size={15} /></ActionIcon></Tooltip>
                        </Group>
                      )}
                    </Group>
                  </UnstyledButton>
                ))}
              </ScrollArea>
            </>
          )}
        </Paper>
        <Paper withBorder className={classes.map}>
          <FleetMap ref={mapRef} places={mapPlaces} points={draftPoints} routes={draftLine}
                    onMapClick={draft ? onMapClick : undefined} />
        </Paper>
      </div>
    </div>
  );
}
