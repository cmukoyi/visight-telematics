import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon, Badge, Button, Checkbox, CloseButton, Group, MultiSelect, Paper, ScrollArea, Select, Stack, Text,
  TextInput, Tooltip, UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconAlertTriangle, IconCar, IconEraser, IconEye, IconEyeOff, IconMapPin, IconMaximize, IconMinimize, IconRoute,
  IconInfoCircle, IconMapPinPlus, IconSearch, IconTimeline,
} from '@tabler/icons-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { fetchTrip, useCan, useCategories, useEvents, useEventTypes, usePlaces, useTrips, useVehicles, type Range } from '../api/hooks';
import { detail, type DeviceEvent, type Trip, type TripDetail } from '../api/types';
import { DataGrid } from '../components/DataGrid';
import { VehiclePanel } from '../components/VehiclePanel';
import { FleetMap, type FleetMapHandle, type MapAction, type MapPoint, type MapTarget, type MapRoute, type MapVehicle } from '../components/FleetMap';
import { PlaceEditor, clickDraft, draftExtent, draftLayers, newDraft, type PlaceDraft } from '../components/PlaceEditor';
import { RangePicker, defaultRange } from '../components/RangePicker';
import { STATUS } from '../theme';
import { dateTime, duration, km, vehicleName } from '../utils/format';
import { toMapPlace } from '../utils/places';
import { ALL_VEHICLES, inGroup, toMapVehicle } from './vehicles';
import classes from './WorkspacePage.module.css';

type Panel = 'vehicles' | 'trips' | 'events' | 'places';

// Categorical colours for plotted trips (assigned in order, never cycled per redraw)
const TRIP_COLORS = ['#2563eb', '#ea580c', '#16a34a', '#9333ea', '#db2777', '#0891b2', '#ca8a04', '#4f46e5'];

const EVENT_COLORS: Record<string, string> = {
  trip_start: '#16a34a', trip_end: '#dc2626', overspeed: '#ea580c', harsh_braking: '#b91c1c',
  harsh_acceleration: '#b91c1c', harsh_cornering: '#b91c1c', idling_start: '#ca8a04', crash: '#7f1d1d',
};
const eventColor = (code: string | null, kind: string) =>
  (code && EVENT_COLORS[code]) || (kind === 'alert' ? '#ef4444' : kind === 'position' ? '#64748b' : '#0ea5e9');

const RIBBON: { key: Panel; label: string; icon: typeof IconCar; permission: string }[] = [
  { key: 'vehicles', label: 'Vehicles', icon: IconCar, permission: 'map.view' },
  { key: 'trips', label: 'Trips', icon: IconRoute, permission: 'history.view' },
  { key: 'events', label: 'Events', icon: IconTimeline, permission: 'history.view' },
  { key: 'places', label: 'Places', icon: IconMapPin, permission: 'places.view' },
];

export function WorkspacePage() {
  const mapRef = useRef<FleetMapHandle>(null);
  const can = useCan();
  const ribbon = RIBBON.filter((r) => can(r.permission));
  const [panel, setPanel] = useState<Panel | null>(() => ribbon.find((r) => r.key === 'trips')?.key ?? ribbon[0]?.key ?? null);
  const canHistory = can('history.view');
  const [maximized, setMaximized] = useState(false);
  const [range, setRange] = useState<Range>(defaultRange);
  const [group, setGroup] = useState(ALL_VEHICLES);
  const [search, setSearch] = useState('');
  const [focus, setFocus] = useState<string | null>(null);   // imei filtering trips/events
  const [eventCodes, setEventCodes] = useState<string[]>([]);

  const [plottedVehicles, setPlottedVehicles] = useState<Set<string>>(new Set());
  const [plottedTrips, setPlottedTrips] = useState<Map<string, TripDetail & { color: string }>>(new Map());
  const [plottedEvents, setPlottedEvents] = useState<Map<number, DeviceEvent>>(new Map());
  const [plottedPlaces, setPlottedPlaces] = useState<Set<string>>(new Set());
  const colorIndex = useRef(0);

  const { data: vehicles = [] } = useVehicles();
  const { data: categories = [] } = useCategories();
  const { data: places = [] } = usePlaces();
  const { data: eventTypes } = useEventTypes();
  const trips = useTrips(range, focus, canHistory);
  const events = useEvents(range, focus, eventCodes, canHistory);

  const listed = useMemo(() => vehicles.filter((v) => inGroup(v, group) &&
    (!search || `${vehicleName(v)} ${v.imei}`.toLowerCase().includes(search.toLowerCase()))), [vehicles, group, search]);

  // ── map layers from plotted state ──
  const mapVehicles = useMemo(() => vehicles.filter((v) => plottedVehicles.has(v.imei)).map(toMapVehicle)
    .filter(Boolean) as MapVehicle[], [vehicles, plottedVehicles]);
  const routes: MapRoute[] = useMemo(() => [...plottedTrips.values()].map((t) => ({
    id: t.id, color: t.color, coords: t.points.map((p) => [p[0], p[1]] as [number, number]),
  })), [plottedTrips]);
  const points: MapPoint[] = useMemo(() => {
    const out: MapPoint[] = [];
    for (const t of plottedTrips.values()) {
      for (const e of t.events) {
        if (e.latitude == null || e.longitude == null) continue;
        out.push({ id: `te-${t.id}-${e.id}`, lat: e.latitude, lng: e.longitude, color: eventColor(e.code, e.kind),
          label: e.label, detail: `${dateTime(e.recorded_at)} · ${e.speed ?? 0} km/h` });
      }
    }
    for (const e of plottedEvents.values()) {
      if (e.latitude == null || e.longitude == null) continue;
      out.push({ id: `ev-${e.id}`, lat: e.latitude, lng: e.longitude, color: eventColor(e.code, e.kind), label: `${e.label} — ${e.device_name}`,
        detail: `${dateTime(e.recorded_at)} · ${e.speed ?? 0} km/h\n${e.io.filter((x) => ['Ignition', 'External voltage', 'Over speeding', 'Green driving value'].includes(x.name)).map((x) => `${x.name}: ${x.display}`).join('\n')}` });
    }
    return out;
  }, [plottedTrips, plottedEvents]);
  // Place being drawn from a plotted vehicle or event (Create place here)
  const [placeDraft, setPlaceDraft] = useState<PlaceDraft | null>(null);
  const draft = draftLayers(placeDraft);
  const canPlaces = can('places.manage');
  // Vehicle details panel (right): opened from a vehicle's popup or the list
  const [detailsImei, setDetailsImei] = useState<string | null>(null);
  const [detailsCollapsed, setDetailsCollapsed] = useState(false);
  const detailsVehicle = vehicles.find((v) => v.imei === detailsImei) ?? null;
  const openDetails = (imei: string) => { setDetailsImei(imei); setDetailsCollapsed(false); setPlaceDraft(null); };
  const panelRight = detailsVehicle ? (detailsCollapsed ? 68 : 404) : 12;

  const startPlace = (lat: number, lng: number, imei: string | null, name: string) => {
    setDetailsImei(null);
    const tagId = vehicles.find((v) => v.imei === imei)?.id;
    const d = newDraft([lat, lng], tagId ? [tagId] : [], name);
    setPlaceDraft(d);
    mapRef.current?.fit(draftExtent(d));
  };
  const eventFor = (t: { kind: string; id: string }) => (t.kind === 'point' ? [...plottedEvents.values()].find((e) => `ev-${e.id}` === t.id) : null);
  const mapActions: MapAction[] = placeDraft ? [] : [
    ...(canPlaces ? [{
      label: 'Draw place',
      onClick: (t: MapTarget) => startPlace(t.lat, t.lng, t.kind === 'vehicle' ? t.id : eventFor(t)?.imei ?? null,
                                            t.kind === 'vehicle' ? `${t.label} location` : ''),
    }] : []),
    {
      label: 'Details',
      onClick: (t: MapTarget) => { const imei = t.kind === 'vehicle' ? t.id : eventFor(t)?.imei; if (imei) openDetails(imei); },
    },
  ];

  const mapPlaces = useMemo(() => {
    const out = places.filter((p) => plottedPlaces.has(p.id)).map(toMapPlace);
    return draft.place ? [...out, draft.place] : out;
  }, [places, plottedPlaces, placeDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const fitAll = (extra: [number, number][] = []) => {
    const pts: [number, number][] = [...extra, ...mapVehicles.map((v) => [v.lat, v.lng] as [number, number])];
    routes.forEach((r) => pts.push(...r.coords));
    points.forEach((p) => pts.push([p.lat, p.lng]));
    mapPlaces.forEach((p) => pts.push([p.lat, p.lng]));
    if (pts.length) mapRef.current?.fit(pts);
  };
  useEffect(() => { fitAll(); }, [plottedTrips.size, plottedEvents.size, plottedVehicles.size, plottedPlaces.size]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── plot / unplot ──
  const toggleVehicle = (imei: string) => setPlottedVehicles((s) => { const n = new Set(s); n.has(imei) ? n.delete(imei) : n.add(imei); return n; });
  const toggleTrip = async (trip: Trip) => {
    if (plottedTrips.has(trip.id)) {
      setPlottedTrips((m) => { const n = new Map(m); n.delete(trip.id); return n; });
      return;
    }
    try {
      const detail = await fetchTrip(trip.id);
      const color = TRIP_COLORS[colorIndex.current++ % TRIP_COLORS.length];
      setPlottedTrips((m) => new Map(m).set(trip.id, { ...detail, color }));
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not plot trip', message: (e as Error).message });
    }
  };
  const toggleEvent = (e: DeviceEvent) => setPlottedEvents((m) => { const n = new Map(m); n.has(e.id) ? n.delete(e.id) : n.set(e.id, e); return n; });
  const togglePlace = (id: string) => setPlottedPlaces((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const clearMap = () => { setPlottedVehicles(new Set()); setPlottedTrips(new Map()); setPlottedEvents(new Map()); setPlottedPlaces(new Set()); };
  const plotted = plottedVehicles.size + plottedTrips.size + plottedEvents.size + plottedPlaces.size;

  // ── grids ──
  const PlotCell = (on: boolean, onClick: () => void, label: string) => (
    <Tooltip label={on ? `Unplot ${label}` : `Plot ${label}`} withinPortal>
      <ActionIcon size="sm" variant={on ? 'filled' : 'subtle'} color={on ? 'brand' : 'gray'} onClick={onClick} aria-label={on ? 'Unplot' : 'Plot'}>
        {on ? <IconEye size={15} /> : <IconEyeOff size={15} />}
      </ActionIcon>
    </Tooltip>
  );

  // Columns as in the Journeys view; the gear (top-left) shows/hides them and headers can be dragged to reorder
  const tripCols: ColDef<Trip>[] = [
    { colId: 'plot', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', suppressMovable: true,
      lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<Trip>) => p.data && PlotCell(plottedTrips.has(p.data.id), () => toggleTrip(p.data!), 'trip') },
    { colId: 'vehicle', headerName: 'Vehicle', valueGetter: (p) => p.data?.device_name ?? p.data?.imei, flex: 1, minWidth: 150 },
    { colId: 'duration', headerName: 'Duration', field: 'duration_s', valueFormatter: (p) => duration(p.value), width: 110, type: 'numericColumn' },
    { colId: 'distance', headerName: 'Distance', field: 'distance_m', valueFormatter: (p) => km(p.value), width: 110, type: 'numericColumn' },
    { colId: 'start_location', headerName: 'Start Location', valueGetter: (p) => p.data?.start_address ?? (p.data?.start ? 'Looking up address…' : '—'),
      flex: 1.4, minWidth: 200, tooltipValueGetter: (p) => p.data?.start_address },
    { colId: 'start_time', headerName: 'Start Time', field: 'started_at', valueFormatter: (p) => dateTime(p.value), sort: 'desc', width: 165 },
    { colId: 'end_location', headerName: 'End Location', flex: 1.4, minWidth: 200, tooltipValueGetter: (p) => p.data?.end_address,
      valueGetter: (p) => (p.data?.status === 'open' ? 'In progress' : p.data?.end_address ?? (p.data?.end ? 'Looking up address…' : '—')) },
    { colId: 'end_time', headerName: 'End Time', field: 'ended_at', valueFormatter: (p) => (p.data?.status === 'open' ? 'In progress' : dateTime(p.value)), width: 165 },
    { colId: 'driver', headerName: 'Driver', field: 'driver', valueFormatter: (p) => p.value || '—', width: 150 },
    { colId: 'max_speed', headerName: 'Max speed', field: 'max_speed', valueFormatter: (p) => `${p.value} km/h`, width: 115, type: 'numericColumn' },
    { colId: 'driving_events', headerName: 'Driving events', width: 190, filter: false,
      valueGetter: (p) => (p.data ? p.data.speeding_count + p.data.harsh_braking_count + p.data.harsh_acceleration_count + p.data.harsh_cornering_count : 0),
      cellRenderer: (p: ICellRendererParams<Trip>) => p.data && (
        <Group gap={4} h="100%" wrap="nowrap">
          {p.data.speeding_count > 0 && <Badge size="sm" color="orange" variant="light">{p.data.speeding_count} speeding</Badge>}
          {p.data.harsh_braking_count + p.data.harsh_acceleration_count + p.data.harsh_cornering_count > 0 &&
            <Badge size="sm" color="red" variant="light">{p.data.harsh_braking_count + p.data.harsh_acceleration_count + p.data.harsh_cornering_count} harsh</Badge>}
          {p.value === 0 && <Text size="xs" c="dimmed">—</Text>}
        </Group>) },
  ];

  const eventCols: ColDef<DeviceEvent>[] = [
    { colId: 'plot', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<DeviceEvent>) => p.data && PlotCell(plottedEvents.has(p.data.id), () => toggleEvent(p.data!), 'event') },
    { headerName: 'Vehicle', field: 'device_name', flex: 1, minWidth: 140 },
    { headerName: 'Event', field: 'label', flex: 1, minWidth: 160,
      cellRenderer: (p: ICellRendererParams<DeviceEvent>) => p.data && (
        <Group gap={6} h="100%" wrap="nowrap"><span className={classes.dot} style={{ background: eventColor(p.data.code, p.data.kind) }} />{p.data.label}</Group>) },
    { headerName: 'Time', field: 'recorded_at', valueFormatter: (p) => dateTime(p.value), sort: 'desc', flex: 1, minWidth: 165 },
    { headerName: 'Latitude', field: 'latitude', width: 110, valueFormatter: (p) => (p.value != null ? p.value.toFixed(5) : '—') },
    { headerName: 'Longitude', field: 'longitude', width: 110, valueFormatter: (p) => (p.value != null ? p.value.toFixed(5) : '—') },
    { headerName: 'Speed', field: 'speed', width: 100, valueFormatter: (p) => `${p.value ?? 0} km/h`, type: 'numericColumn' },
    { headerName: 'Odometer', field: 'odometer_km', width: 115, valueFormatter: (p) => (p.value != null ? `${p.value} km` : '—'), type: 'numericColumn' },
    ...(canPlaces ? [{ headerName: '', width: 56, minWidth: 56, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<DeviceEvent>) => p.data && p.data.latitude != null && (
        <Tooltip label="Draw place at this event" withinPortal>
          <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Draw place at this event"
                      onClick={() => startPlace(p.data!.latitude!, p.data!.longitude!, p.data!.imei, `${p.data!.label} — ${p.data!.device_name}`)}>
            <IconMapPinPlus size={15} />
          </ActionIcon>
        </Tooltip>) }] : []),
  ];

  const focusName = focus ? vehicleName(vehicles.find((v) => v.imei === focus) ?? { imei: focus }) : null;

  return (
    <div className={classes.root}>
      <FleetMap ref={mapRef} vehicles={mapVehicles} routes={[...routes, ...draft.routes]} points={[...points, ...draft.points]}
                places={mapPlaces} actions={mapActions}
                onMapClick={placeDraft ? (lat, lng) => setPlaceDraft((d) => d && clickDraft(d, lat, lng)) : undefined}
                fitPadding={{ top: 80, left: 60, right: placeDraft ? 400 : panelRight + 48, bottom: panel ? (maximized ? 60 : 380) : 60 }} />

      {detailsVehicle && (
        <VehiclePanel vehicle={detailsVehicle} collapsed={detailsCollapsed} onCollapse={setDetailsCollapsed}
                      onClose={() => setDetailsImei(null)}
                      plotted={plottedVehicles.has(detailsVehicle.imei)} onTogglePlot={() => toggleVehicle(detailsVehicle.imei)}
                      plottedTrips={new Set(plottedTrips.keys())} onToggleTrip={toggleTrip} />
      )}

      {placeDraft && (
        <Paper className={classes.placePanel} shadow="xl" withBorder>
          <ScrollArea h="100%" type="auto">
            <Stack p="md" gap="sm">
              <Group justify="space-between"><Text fw={650}>New place</Text>
                <CloseButton onClick={() => setPlaceDraft(null)} aria-label="Cancel new place" /></Group>
              <PlaceEditor draft={placeDraft} setDraft={setPlaceDraft} places={places} vehicles={vehicles}
                           onLocate={(pts) => pts.length && mapRef.current?.fit(pts)} onCancel={() => setPlaceDraft(null)}
                           onSaved={(p) => { setPlaceDraft(null); setPlottedPlaces((s) => new Set(s).add(p.id)); }} />
            </Stack>
          </ScrollArea>
        </Paper>
      )}

      <Paper className={classes.ribbon} shadow="md" p={4}>
        <Group gap={4} wrap="nowrap">
          {ribbon.map((r) => (
            <Button key={r.key} size="xs" variant={panel === r.key ? 'filled' : 'subtle'} color={panel === r.key ? 'brand' : 'gray'}
                    leftSection={<r.icon size={16} />} onClick={() => setPanel(panel === r.key ? null : r.key)}>
              {r.label}
            </Button>
          ))}
          <div className={classes.sep} />
          <Tooltip label="Remove everything from the map">
            <Button size="xs" variant="subtle" color="gray" leftSection={<IconEraser size={16} />} onClick={clearMap} disabled={!plotted}>
              Clear map{plotted ? ` (${plotted})` : ''}
            </Button>
          </Tooltip>
        </Group>
      </Paper>

      {panel && (
        <Paper className={`${classes.dock} ${maximized ? classes.dockMax : ''}`} shadow="xl" style={{ right: panelRight }}>
          <div className={classes.vehicles}>
            <Group justify="space-between" mb="xs">
              <Group gap={6}><IconCar size={18} /><Text fw={650}>Vehicles</Text></Group>
              <Text size="xs" c="dimmed">{listed.length}</Text>
            </Group>
            <TextInput size="xs" placeholder="Search name or IMEI" leftSection={<IconSearch size={14} />} value={search}
                       onChange={(e) => setSearch(e.currentTarget.value)} mb={6} />
            <Select size="xs" value={group} onChange={(v) => setGroup(v ?? ALL_VEHICLES)} allowDeselect={false} mb="xs" aria-label="Vehicle group"
                    data={[{ value: ALL_VEHICLES, label: `All vehicles (${vehicles.length})` }, ...categories.map((c) => ({ value: c.name, label: c.name }))]} />
            <ScrollArea className={classes.vehicleList} type="auto">
              <UnstyledButton className={`${classes.vehicleRow} ${!focus ? classes.focused : ''}`} onClick={() => setFocus(null)}>
                <Text size="sm" fw={500}>All vehicles</Text>
              </UnstyledButton>
              {listed.map((v) => (
                <div key={v.imei} className={`${classes.vehicleRow} ${focus === v.imei ? classes.focused : ''}`}
                     onClick={() => setFocus(focus === v.imei ? null : v.imei)} role="button" tabIndex={0}
                     onKeyDown={(e) => e.key === 'Enter' && setFocus(v.imei)}>
                  <Checkbox size="xs" checked={plottedVehicles.has(v.imei)} aria-label="Plot vehicle"
                            onClick={(e) => e.stopPropagation()} onChange={() => toggleVehicle(v.imei)} />
                  <span className={classes.dot} style={{ background: STATUS[v.activity_status] }} title={v.activity_status} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Text size="sm" fw={500} truncate>{vehicleName(v)}</Text>
                    <Text size="xs" c="dimmed" truncate>{detail(v, 'registration') || v.imei}</Text>
                  </div>
                  <Tooltip label="Details" withinPortal>
                    <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Vehicle details"
                                onClick={(e) => { e.stopPropagation(); openDetails(v.imei); }}>
                      <IconInfoCircle size={15} />
                    </ActionIcon>
                  </Tooltip>
                  {canPlaces && v.latitude && v.longitude && (
                    <Tooltip label="Draw place at this vehicle" withinPortal>
                      <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Draw place at this vehicle"
                                  onClick={(e) => { e.stopPropagation(); startPlace(parseFloat(v.latitude!), parseFloat(v.longitude!), v.imei, `${vehicleName(v)} location`); }}>
                        <IconMapPinPlus size={15} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </div>
              ))}
            </ScrollArea>
          </div>

          <div className={classes.content}>
            <Group justify="space-between" mb="sm" wrap="nowrap">
              <Group gap="sm" wrap="nowrap">
                <Text fw={650} size="lg">{RIBBON.find((r) => r.key === panel)?.label}</Text>
                {focusName && panel !== 'places' && panel !== 'vehicles' &&
                  <Badge variant="light" rightSection={<CloseButton size="xs" onClick={() => setFocus(null)} aria-label="Clear vehicle filter" />}>{focusName}</Badge>}
              </Group>
              <Group gap="xs" wrap="nowrap">
                {(panel === 'trips' || panel === 'events') && <RangePicker value={range} onChange={setRange} />}
                {panel === 'events' && (
                  <MultiSelect size="sm" placeholder={eventCodes.length ? '' : 'All event types'} w={260} clearable searchable maxValues={12}
                               value={eventCodes} onChange={setEventCodes} aria-label="Event types"
                               data={(eventTypes?.events ?? []).map((e) => ({ value: e.code, label: e.label }))} />
                )}
                <ActionIcon variant="subtle" color="gray" onClick={() => setMaximized((m) => !m)} aria-label={maximized ? 'Restore panel' : 'Maximise panel'}>
                  {maximized ? <IconMinimize size={18} /> : <IconMaximize size={18} />}
                </ActionIcon>
                <CloseButton onClick={() => setPanel(null)} aria-label="Close panel" />
              </Group>
            </Group>

            {panel === 'trips' && (
              <DataGrid rowData={trips.data ?? []} columnDefs={tripCols} loading={trips.isFetching} stateKey="workspace-trips" tooltipShowDelay={400}
                        getRowId={(p) => p.data.id} onRowDoubleClicked={(e) => e.data && toggleTrip(e.data)} />
            )}
            {panel === 'events' && (
              <DataGrid rowData={events.data ?? []} columnDefs={eventCols} loading={events.isFetching} stateKey="workspace-events"
                        getRowId={(p) => String(p.data.id)} onRowDoubleClicked={(e) => e.data && toggleEvent(e.data)} />
            )}
            {panel === 'vehicles' && (
              <Stack gap="xs">
                <Text size="sm" c="dimmed">Tick vehicles on the left to plot their live position; click a vehicle to filter Trips and Events.</Text>
                <Group>
                  <Button size="xs" variant="light" onClick={() => setPlottedVehicles(new Set(listed.map((v) => v.imei)))}>Plot all listed</Button>
                  <Button size="xs" variant="subtle" color="gray" onClick={() => setPlottedVehicles(new Set())}>Unplot vehicles</Button>
                </Group>
              </Stack>
            )}
            {panel === 'places' && (
              <ScrollArea h="100%">
                {places.length === 0 && <Text c="dimmed" size="sm">No places yet — add them under Configuration → Places.</Text>}
                {places.map((p) => (
                  <Group key={p.id} className={classes.placeRow} wrap="nowrap">
                    <Checkbox size="xs" checked={plottedPlaces.has(p.id)} onChange={() => togglePlace(p.id)} aria-label="Plot place" />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Text size="sm" fw={500} truncate>{p.name}</Text>
                      <Text size="xs" c="dimmed" truncate>{p.address || `${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)}`}</Text>
                    </div>
                    <Badge size="sm" variant="light" color="violet">{p.shape_type === 'polygon' ? 'Polygon' : `${Math.round(p.radius)} m`}</Badge>
                    {p.armed_count > 0 && <Badge size="sm" variant="light" leftSection={<IconAlertTriangle size={12} />}>{p.armed_count} armed</Badge>}
                  </Group>
                ))}
              </ScrollArea>
            )}
          </div>
        </Paper>
      )}
    </div>
  );
}
