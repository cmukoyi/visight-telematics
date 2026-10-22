import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Anchor, Badge, Breadcrumbs, Button, Group, Paper, ScrollArea, Stack, Text, TextInput, Title, Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconMapPin, IconPencil, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCan, usePlaces, useVehicles } from '../api/hooks';
import type { Place } from '../api/types';
import { FleetMap, type FleetMapHandle, type MapPlace } from '../components/FleetMap';
import { PlaceEditor, clickDraft, draftFromPlace, draftLayers, newDraft, type PlaceDraft } from '../components/PlaceEditor';
import { placeOutline, toMapPlace } from '../utils/places';
import classes from './PlacesPage.module.css';

export function PlacesPage() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('places.manage');
  const mapRef = useRef<FleetMapHandle>(null);
  const { data: places = [] } = usePlaces();
  const { data: vehicles = [] } = useVehicles();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<PlaceDraft | null>(null);

  const listed = places.filter((p) => !search || `${p.name} ${p.address ?? ''}`.toLowerCase().includes(search.toLowerCase()));

  // Map: every place, with the one being edited replaced by the draft
  const layers = draftLayers(draft);
  const mapPlaces: MapPlace[] = useMemo(() => {
    const out = places.filter((p) => p.id !== draft?.id).map(toMapPlace);
    return layers.place ? [...out, layers.place] : out;
  }, [places, draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const focus = (p: Place) => {
    setSelected(p.id);
    const outline = placeOutline(p);
    if (outline) mapRef.current?.fit(outline);
    else {
      const d = p.radius / 111320;
      mapRef.current?.fit([[p.latitude - d, p.longitude - d], [p.latitude + d, p.longitude + d]]);
    }
  };
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    const wanted = places.find((p) => p.id === params.get('place'));
    if (wanted) { focus(wanted); setParams({}, { replace: true }); }
    else if (places.length && !draft) mapRef.current?.fit(places.map((p) => [p.latitude, p.longitude]));
  }, [places.length, params]); // eslint-disable-line react-hooks/exhaustive-deps

  const onMapClick = (lat: number, lng: number) => setDraft((d) => d && clickDraft(d, lat, lng));

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
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setDraft(newDraft())}>Add place</Button>
          )}
        </Group>
      </Stack>

      <div className={classes.body}>
        <Paper withBorder className={classes.side}>
          {draft ? (
            <ScrollArea className={classes.scroll} type="auto">
              <Stack p="md" gap="sm">
                <Text fw={650}>{draft.id ? 'Edit place' : 'New place'}</Text>
                <PlaceEditor draft={draft} setDraft={setDraft} places={places} vehicles={vehicles}
                             onLocate={(pts) => pts.length && mapRef.current?.fit(pts)}
                             onCancel={() => setDraft(null)} onSaved={(p) => { setSelected(p.id); setDraft(null); }} />
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
                            onClick={(e) => { e.stopPropagation(); focus(p); setDraft(draftFromPlace(p)); }}><IconPencil size={15} /></ActionIcon></Tooltip>
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
          <FleetMap ref={mapRef} places={mapPlaces} points={layers.points} routes={layers.routes}
                    onMapClick={draft ? onMapClick : undefined} />
        </Paper>
      </div>
    </div>
  );
}
