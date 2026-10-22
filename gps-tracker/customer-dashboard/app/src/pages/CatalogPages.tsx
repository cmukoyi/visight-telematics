import { useMemo, useState } from 'react';
import {
  ActionIcon, Badge, Button, ColorInput, Group, Paper, Stack, Text, TextInput, Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconMapPinOff, IconPencil, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useEventTypeGroups, useEventTypeList, useGeofences, usePlaceGroups, usePlaces } from '../api/hooks';
import type { EventTypeGroup, EventTypeRow, GeofenceRow, PlaceGroup } from '../api/types';
import { ConfigHeader } from '../components/ConfigHeader';
import { DataGrid } from '../components/DataGrid';
import { EditorShell, firstError } from '../components/EditorShell';
import { CheckList } from '../components/FeaturePicker';
import { ago, dateTime } from '../utils/format';
import classes from './CatalogPages.module.css';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const confirmDelete = (title: string, body: string, run: () => Promise<void>) => modals.openConfirmModal({
  title, children: <Text size="sm">{body}</Text>, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
  onConfirm: () => run().catch(fail),
});

function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <TextInput size="xs" w={260} placeholder="Search" leftSection={<IconSearch size={14} />} value={value}
                    onChange={(e) => onChange(e.currentTarget.value)} />;
}

// ── Place groups ──
export function PlaceGroupsPage() {
  const qc = useQueryClient();
  const manage = useCan()('places.manage');
  const { data: groups = [], isFetching } = usePlaceGroups();
  const [editing, setEditing] = useState<PlaceGroup | 'new' | null>(null);
  const form = useForm({ initialValues: { name: '', color: '#7c3aed' }, validate: { name: (v) => (v.trim() ? null : 'Enter a name') } });
  const open = (g: PlaceGroup | 'new') => { form.setValues(g === 'new' ? { name: '', color: '#7c3aed' } : { name: g.name, color: g.color ?? '#7c3aed' }); setEditing(g); };
  const refresh = () => { qc.invalidateQueries({ queryKey: ['place-groups'] }); qc.invalidateQueries({ queryKey: ['places'] }); };
  const { data: places = [] } = usePlaces();
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      if (editing === 'new') await api('/api/portal/place-groups', { method: 'POST', json: v });
      else if (editing) await api(`/api/portal/place-groups/${editing.id}`, { method: 'PUT', json: v });
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const cols: ColDef<PlaceGroup>[] = [
    { colId: 'swatch', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false,
      cellRenderer: (p: ICellRendererParams<PlaceGroup>) => p.data && <span className={classes.swatch} style={{ background: p.data.color ?? '#7c3aed' }} /> },
    { headerName: 'Name', field: 'name', flex: 1, sort: 'asc' },
    { headerName: 'Places', field: 'place_count', width: 120, type: 'numericColumn' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<PlaceGroup>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit place group"><IconPencil size={15} /></ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" aria-label="Delete place group"
                      onClick={() => confirmDelete(`Delete “${p.data!.name}”?`, 'Its places stay, without a group.', async () => {
                        await api(`/api/portal/place-groups/${p.data!.id}`, { method: 'DELETE' }); refresh();
                      })}><IconTrash size={15} /></ActionIcon>
        </Group>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Places" title="Place Groups" description="Group places (depots, customer sites…) to organise them and to use in notification rules.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add place group</Button>}
      </ConfigHeader>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={groups} columnDefs={cols} loading={isFetching && !groups.length} getRowId={(p) => p.data.id}
                  overlayNoRowsTemplate='<span style="opacity:.7">No place groups yet.</span>' />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Place Group' : 'Edit Place Group'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name colour color',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" withAsterisk placeholder="e.g. Depots" {...form.getInputProps('name')} data-autofocus />
              <ColorInput label="Colour" format="hex" {...form.getInputProps('color')} />
            </Stack>
          ) },
        { id: 'places', label: 'Places', keywords: 'places members',
          content: (() => {
            const inGroup = editing && editing !== 'new' ? places.filter((p) => p.place_group_id === editing.id) : [];
            return (
              <Stack maw={760} gap={6}>
                <Text size="sm" c="dimmed">Choose a place's group when you add or edit it under Places.
                  {editing !== 'new' && ` ${inGroup.length} place${inGroup.length === 1 ? '' : 's'} in this group.`}</Text>
                {inGroup.map((p) => <Text key={p.id} size="sm">{p.name}{p.address ? <Text span c="dimmed"> · {p.address}</Text> : null}</Text>)}
              </Stack>
            );
          })() },
      ]} />
    </Stack>
  );
}

// ── Geofences: armed vehicles per place and whether they're inside ──
export function GeofencesPage() {
  const qc = useQueryClient();
  const manage = useCan()('places.manage');
  const { data: rows = [], isFetching } = useGeofences();
  const [search, setSearch] = useState('');
  const shown = rows.filter((r) => !search || `${r.place} ${r.vehicle} ${r.imei}`.toLowerCase().includes(search.toLowerCase()));
  const disarm = (r: GeofenceRow) => confirmDelete(`Disarm ${r.vehicle} from ${r.place}?`, 'It stops raising entry and exit alerts for this place (notification rules still apply).', async () => {
    await api(`/api/portal/locations/${r.poi_id}/arm/${r.tag_id}`, { method: 'DELETE' });
    qc.invalidateQueries({ queryKey: ['geofences'] });
    qc.invalidateQueries({ queryKey: ['places'] });
  });
  const cols: ColDef<GeofenceRow>[] = [
    { colId: 'state', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false,
      cellRenderer: (p: ICellRendererParams<GeofenceRow>) => p.data &&
        <span className={classes.dot} data-state={p.data.inside == null ? 'unknown' : p.data.inside ? 'in' : 'out'} /> },
    { headerName: 'Place', field: 'place', flex: 1, minWidth: 160 },
    { headerName: 'Vehicle', field: 'vehicle', flex: 1, minWidth: 160 },
    { headerName: 'Status', width: 140, valueGetter: (p) => (p.data?.inside == null ? 'Not checked yet' : p.data.inside ? 'Inside' : 'Outside'),
      cellRenderer: (p: ICellRendererParams<GeofenceRow>) => p.data && (
        <Badge size="sm" variant="light" color={p.data.inside == null ? 'gray' : p.data.inside ? 'green' : 'blue'}>{p.value}</Badge>) },
    { headerName: 'Last checked', field: 'checked_at', width: 170, valueFormatter: (p) => (p.value ? `${dateTime(p.value)}` : '—'),
      tooltipValueGetter: (p) => (p.value ? ago(p.value) : null) },
    { headerName: 'Armed', field: 'armed_at', width: 170, valueFormatter: (p) => dateTime(p.value) },
    ...(manage ? [{ headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<GeofenceRow>) => p.data && (
        <Tooltip label="Disarm" withinPortal><ActionIcon size="sm" variant="subtle" color="red" onClick={() => disarm(p.data!)} aria-label="Disarm">
          <IconMapPinOff size={15} /></ActionIcon></Tooltip>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Places" title="Geofences" description="Vehicles armed to places, and whether each is inside right now. Arm vehicles when you add or edit a place." />
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} assignments</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} tooltipShowDelay={300} stateKey="geofences"
                  getRowId={(p) => `${p.data.poi_id}-${p.data.tag_id}`}
                  overlayNoRowsTemplate='<span style="opacity:.7">No vehicles are armed to places yet.</span>' />
      </Paper>
    </Stack>
  );
}

// ── Event types: our dictionary, with the group's own names and marker colours ──
export function EventTypesPage() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('events.manage');
  const { data: rows = [], isFetching } = useEventTypeList();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<EventTypeRow | null>(null);
  const form = useForm({ initialValues: { label: '', color: '' } });
  const shown = rows.filter((r) => !search || `${r.default_label} ${r.label} ${r.category_label}`.toLowerCase().includes(search.toLowerCase()));
  const open = (r: EventTypeRow) => { form.setValues({ label: r.custom_label ?? '', color: r.color ?? '' }); setEditing(r); };
  const save = form.onSubmit(async (v) => {
    try {
      await api(`/api/portal/event-type-list/${editing!.code}`, { method: 'PUT', json: { label: v.label || null, color: v.color || null } });
      qc.invalidateQueries({ queryKey: ['event-type-list'] });
      qc.invalidateQueries({ queryKey: ['event-types'] });
      setEditing(null);
    } catch (e) { fail(e); }
  });
  const cols: ColDef<EventTypeRow>[] = [
    { headerName: 'Id', field: 'id', width: 80, type: 'numericColumn' },
    { headerName: 'Default Description', field: 'default_label', flex: 1, minWidth: 200 },
    { headerName: 'Optional Description', field: 'label', flex: 1, minWidth: 200, sort: 'asc',
      cellRenderer: (p: ICellRendererParams<EventTypeRow>) => p.data && (
        <Text size="sm" fw={p.data.custom_label ? 600 : undefined}>{p.data.label}</Text>) },
    { headerName: 'Category', field: 'category_label', width: 200 },
    { headerName: 'Map Marker', field: 'color', width: 120, sortable: false, filter: false,
      cellRenderer: (p: ICellRendererParams<EventTypeRow>) => p.data && (
        <svg width="18" height="22" viewBox="0 0 18 22" aria-label="Marker colour">
          <path d="M9 21s7-7.2 7-12.2A7 7 0 0 0 2 8.8C2 13.8 9 21 9 21z" fill={p.data.color ?? '#ffffff'} stroke="#64748b" strokeWidth="1.2" />
        </svg>) },
    ...(manage ? [{ headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<EventTypeRow>) => p.data && (
        <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit event type"><IconPencil size={15} /></ActionIcon>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Events" title="Event Types" description="The events we decode from your devices. Give any of them your own name and map colour." />
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} event types</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.code}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)} />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing ? `Edit “${editing.default_label}”` : ''}
                   onSave={() => save()} sections={editing ? [
        { id: 'general', label: 'General', keywords: 'name description category',
          content: (
            <Stack maw={620}>
              <TextInput label="Default description" value={editing.default_label} readOnly />
              <TextInput label="Optional description" placeholder={editing.default_label} description="Your own name for this event, used everywhere on the platform. Leave empty for the default."
                         {...form.getInputProps('label')} data-autofocus />
              <TextInput label="Category" value={editing.category_label} readOnly />
            </Stack>
          ) },
        { id: 'marker', label: 'Map marker', keywords: 'colour color marker map',
          content: (
            <Stack maw={620}>
              <ColorInput label="Map marker colour" placeholder="Default (leave empty)" format="hex" {...form.getInputProps('color')} />
              <Group gap="sm"><Text size="sm" c="dimmed">Preview</Text>
                <svg width="22" height="27" viewBox="0 0 18 22" aria-hidden="true">
                  <path d="M9 21s7-7.2 7-12.2A7 7 0 0 0 2 8.8C2 13.8 9 21 9 21z" fill={form.values.color || '#ffffff'} stroke="#64748b" strokeWidth="1.2" />
                </svg></Group>
            </Stack>
          ) },
      ] : []} />
    </Stack>
  );
}

// ── Event type groups ──
export function EventTypeGroupsPage() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('events.manage');
  const { data: groups = [], isFetching } = useEventTypeGroups();
  const { data: types = [] } = useEventTypeList();
  const [editing, setEditing] = useState<EventTypeGroup | 'new' | null>(null);
  const label = useMemo(() => new Map(types.map((t) => [t.code, t.label])), [types]);
  const form = useForm<{ name: string; codes: string[] }>({
    initialValues: { name: '', codes: [] },
    validate: { name: (v) => (v.trim() ? null : 'Enter a name'), codes: (v) => (v.length ? null : 'Choose at least one event type') },
  });
  const open = (g: EventTypeGroup | 'new') => { form.setValues(g === 'new' ? { name: '', codes: [] } : { name: g.name, codes: g.codes }); setEditing(g); };
  const refresh = () => qc.invalidateQueries({ queryKey: ['event-type-groups'] });
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      if (editing === 'new') await api('/api/portal/event-type-groups', { method: 'POST', json: v });
      else if (editing) await api(`/api/portal/event-type-groups/${editing.id}`, { method: 'PUT', json: v });
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  return (
    <Stack p="lg" gap={0} className={classes.narrow}>
      <ConfigHeader section="Events" title="Event Type Groups" description="Group event types, then use a group in a notification rule to alert on any event in it.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add event type group</Button>}
      </ConfigHeader>
      <Paper withBorder>
        {!isFetching && groups.length === 0 && <Text c="dimmed" size="sm" p="md">No event type groups yet — e.g. “Harsh driving” with harsh braking, acceleration and cornering.</Text>}
        {groups.map((g) => (
          <Group key={g.id} className={classes.row} wrap="nowrap" align="flex-start">
            <div style={{ flex: 1, minWidth: 0 }}>
              <Group gap="xs"><Text fw={600}>{g.name}</Text>
                {g.rule_count > 0 && <Badge size="xs" variant="outline">{g.rule_count} rule{g.rule_count === 1 ? '' : 's'}</Badge>}</Group>
              <Group gap={4} mt={6}>{g.codes.map((c) => <Badge key={c} size="sm" variant="light">{label.get(c) ?? c}</Badge>)}</Group>
            </div>
            {manage && (
              <Group gap={2} wrap="nowrap">
                <ActionIcon variant="subtle" onClick={() => open(g)} aria-label="Edit event type group"><IconPencil size={16} /></ActionIcon>
                <ActionIcon variant="subtle" color="red" aria-label="Delete event type group"
                            onClick={() => confirmDelete(`Delete “${g.name}”?`, 'Groups used by a notification rule can’t be deleted.', async () => {
                              await api(`/api/portal/event-type-groups/${g.id}`, { method: 'DELETE' }); refresh();
                            })}><IconTrash size={16} /></ActionIcon>
              </Group>
            )}
          </Group>
        ))}
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Event Type Group' : 'Edit Event Type Group'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" withAsterisk placeholder="e.g. Harsh driving" {...form.getInputProps('name')} data-autofocus />
              {editing && editing !== 'new' && editing.rule_count > 0 &&
                <Text size="sm" c="dimmed">Used by {editing.rule_count} notification rule{editing.rule_count === 1 ? '' : 's'}.</Text>}
            </Stack>
          ) },
        { id: 'events', label: 'Event types', keywords: 'events types codes',
          content: (
            <Stack maw={820}>
              <Text size="sm" c="dimmed">A notification rule using this group alerts on any of these events.</Text>
              {form.errors.codes && <Text size="sm" c="red">{form.errors.codes}</Text>}
              <CheckList value={form.values.codes} onChange={(v) => form.setFieldValue('codes', v)} height={460}
                         items={types.map((t) => ({ value: t.code, label: t.label, description: t.custom_label ? t.default_label : undefined,
                                                    extra: <Badge size="xs" variant="default">{t.category_label}</Badge> }))} />
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}
