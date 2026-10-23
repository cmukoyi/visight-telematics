import { useState } from 'react';
import { ActionIcon, Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Switch, Table, Text, TextInput, Tooltip } from '@mantine/core';
import { TimeInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconKey, IconPencil, IconPlus, IconSearch, IconStar, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useDrivers, useTimeProfiles } from '../api/hooks';
import type { Driver, TimeProfile } from '../api/types';
import { ConfigHeader } from '../components/ConfigHeader';
import { DataGrid } from '../components/DataGrid';
import { EditorShell, firstError } from '../components/EditorShell';
import classes from './CatalogPages.module.css';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const confirmDelete = (title: string, body: string, run: () => Promise<unknown>) => modals.openConfirmModal({
  title, children: <Text size="sm">{body}</Text>, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
  onConfirm: () => { run().catch(fail); },
});

// ── Drivers ──
export function DriversPage() {
  const qc = useQueryClient();
  const manage = useCan()('vehicles.manage');
  const { data: rows = [], isFetching } = useDrivers();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Driver | 'new' | null>(null);
  const blank = { first_name: '', last_name: '', employee_number: '', key_code: '', phone: '', is_active: true };
  const form = useForm({ initialValues: blank, validate: { first_name: (v) => (v.trim() ? null : 'Enter the driver’s name') } });
  const open = (d: Driver | 'new') => {
    form.setValues(d === 'new' ? blank : { first_name: d.first_name, last_name: d.last_name ?? '', employee_number: d.employee_number ?? '',
                                           key_code: d.key_code ?? '', phone: d.phone ?? '', is_active: d.is_active });
    setEditing(d);
  };
  const refresh = () => { qc.invalidateQueries({ queryKey: ['drivers'] }); qc.invalidateQueries({ queryKey: ['vehicles'] }); };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      await api(`/api/portal/drivers${editing === 'new' ? '' : `/${editing!.id}`}`, { method: editing === 'new' ? 'POST' : 'PUT', json: v });
      refresh();
      notifications.show({ color: 'green', message: `${v.first_name} ${v.last_name} saved`.trim() });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const shown = rows.filter((r) => !search || `${r.name} ${r.employee_number ?? ''} ${r.key_code ?? ''} ${r.vehicles.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<Driver>[] = [
    { headerName: 'Name', field: 'first_name', flex: 1, minWidth: 130, sort: 'asc' },
    { headerName: 'Surname', field: 'last_name', flex: 1, minWidth: 130, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Employee Number', field: 'employee_number', width: 160, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Driver Key', field: 'key_code', width: 190, valueFormatter: (p) => p.value || '—',
      cellRenderer: (p: ICellRendererParams<Driver>) => p.data && (p.data.key_code
        ? <Group gap={6} wrap="nowrap"><IconKey size={14} opacity={0.6} /><Text size="sm" ff="monospace">{p.data.key_code}</Text></Group> : '—') },
    { headerName: 'Assigned Vehicles', flex: 1, minWidth: 160, valueGetter: (p) => p.data?.vehicles.join(', ') || '—' },
    { headerName: 'Trips (by key)', field: 'trips', width: 130, type: 'numericColumn' },
    { headerName: 'Active', field: 'is_active', width: 100,
      cellRenderer: (p: ICellRendererParams<Driver>) => p.data && <Badge size="sm" variant="light" color={p.data.is_active ? 'green' : 'gray'}>{p.data.is_active ? 'Yes' : 'No'}</Badge> },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<Driver>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit driver"><IconPencil size={15} /></ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" aria-label="Delete driver"
                      onClick={() => confirmDelete(`Delete ${p.data!.name}?`, 'Their vehicles lose the assignment; trips keep their history without a driver.', async () => {
                        await api(`/api/portal/drivers/${p.data!.id}`, { method: 'DELETE' }); refresh();
                      })}><IconTrash size={15} /></ActionIcon>
        </Group>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Users" title="Drivers"
                    description="Who drives your vehicles. Assign a driver to a vehicle in its editor; when a driver presents their key (one-wire tag), that trip is theirs.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add driver</Button>}
      </ConfigHeader>
      <Group mb="sm"><TextInput size="xs" w={260} placeholder="Search" leftSection={<IconSearch size={14} />} value={search}
                                onChange={(e) => setSearch(e.currentTarget.value)} /><Text size="sm" c="dimmed">{shown.length} drivers</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} stateKey="drivers"
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No drivers yet.</span>' />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Driver' : 'Edit Driver'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name surname employee number phone active',
          content: (
            <Stack maw={680}>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextInput label="Name" withAsterisk {...form.getInputProps('first_name')} data-autofocus />
                <TextInput label="Surname" {...form.getInputProps('last_name')} />
                <TextInput label="Employee number" placeholder="e.g. E1024" {...form.getInputProps('employee_number')} />
                <TextInput label="Phone" {...form.getInputProps('phone')} />
              </SimpleGrid>
              <Switch label="Active" description="Inactive drivers stay on old trips but their key no longer identifies them"
                      checked={form.values.is_active} onChange={(e) => form.setFieldValue('is_active', e.currentTarget.checked)} />
            </Stack>
          ) },
        { id: 'key', label: 'Driver Key', keywords: 'key ibutton tag one wire fob code',
          content: (
            <Stack maw={680}>
              <TextInput label="Key code" leftSection={<IconKey size={15} />} placeholder="e.g. 01A2B3C4D5E6F701" ff="monospace"
                         description="The ID printed on the driver's one-wire tag (iButton), or the number the tracker reports for it. Trips where this key is presented are credited to this driver."
                         {...form.getInputProps('key_code')} />
              <Text size="xs" c="dimmed">Without a key, trips show the driver assigned to the vehicle (Configuration → Vehicles → General).</Text>
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}

// ── Time profiles ──
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
type DayRow = { on: boolean; start: string; end: string };
const toRows = (w: TimeProfile['windows']): DayRow[] => DAYS.map((_, d) => {
  const span = w[String(d)]?.[0];
  return span ? { on: true, start: span[0], end: span[1] } : { on: false, start: '07:00', end: '17:00' };
});
const fromRows = (rows: DayRow[]) => Object.fromEntries(rows.flatMap((r, d) => (r.on ? [[String(d), [[r.start, r.end]]]] : [])));

export function TimeProfilesPage() {
  const qc = useQueryClient();
  const manage = useCan()('settings.manage');
  const { data: rows = [], isFetching } = useTimeProfiles();
  const [editing, setEditing] = useState<TimeProfile | 'new' | null>(null);
  const weekdays = (): DayRow[] => DAYS.map((_, d) => ({ on: d < 5, start: '07:00', end: '17:00' }));
  const form = useForm({ initialValues: { name: '', is_default: false, days: weekdays() },
                         validate: { name: (v) => (v.trim() ? null : 'Enter a name') } });
  const open = (p: TimeProfile | 'new') => {
    form.setValues(p === 'new' ? { name: '', is_default: rows.length === 0, days: weekdays() }
      : { name: p.name, is_default: p.is_default, days: toRows(p.windows) });
    setEditing(p);
  };
  const refresh = () => qc.invalidateQueries({ queryKey: ['time-profiles'] });
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    const bad = v.days.findIndex((d) => d.on && (!d.start || !d.end || d.end <= d.start));
    if (bad >= 0) { notifications.show({ color: 'orange', message: `${DAYS[bad]}: the end time must be after the start` }); return; }
    try {
      await api(`/api/portal/time-profiles${editing === 'new' ? '' : `/${editing!.id}`}`, {
        method: editing === 'new' ? 'POST' : 'PUT', json: { name: v.name, is_default: v.is_default, windows: fromRows(v.days) } });
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const hours = form.values.days.reduce((a, d) => {
    if (!d.on || d.end <= d.start) return a;
    const [h1, m1] = d.start.split(':').map(Number), [h2, m2] = d.end.split(':').map(Number);
    return a + (h2 * 60 + m2 - h1 * 60 - m1) / 60;
  }, 0);
  const cols: ColDef<TimeProfile>[] = [
    { headerName: 'Name', field: 'name', flex: 1, minWidth: 160,
      cellRenderer: (p: ICellRendererParams<TimeProfile>) => p.data && (
        <Group gap={6} wrap="nowrap">{p.data.name}{p.data.is_default && <Badge size="xs" variant="light" leftSection={<IconStar size={10} />}>Default</Badge>}</Group>) },
    { headerName: 'Working Hours', field: 'summary', flex: 2, minWidth: 260 },
    { headerName: 'Vehicles', field: 'vehicles', width: 120, type: 'numericColumn',
      headerTooltip: 'Vehicles set to this profile; the default covers all the others' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<TimeProfile>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit time profile"><IconPencil size={15} /></ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" aria-label="Delete time profile"
                      onClick={() => confirmDelete(`Delete “${p.data!.name}”?`, 'Vehicles using it must be changed first.', async () => {
                        await api(`/api/portal/time-profiles/${p.data!.id}`, { method: 'DELETE' }); refresh();
                      })}><IconTrash size={15} /></ActionIcon>
        </Group>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Misc" title="Time Profiles"
                    description="Working hours, so reports can split usage into inside and after hours. The default profile applies to every vehicle without its own (set in the vehicle editor).">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add time profile</Button>}
      </ConfigHeader>
      {!rows.length && !isFetching && (
        <Text size="sm" c="dimmed" mb="sm">No profiles yet — until you add one, Monday to Friday 07:00–17:00 counts as working hours.</Text>
      )}
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No time profiles yet.</span>' />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Time Profile' : 'Edit Time Profile'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name default',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" withAsterisk placeholder="e.g. Office hours" {...form.getInputProps('name')} data-autofocus />
              <Switch label="Default profile" description="Used for every vehicle that doesn't have its own"
                      checked={form.values.is_default} onChange={(e) => form.setFieldValue('is_default', e.currentTarget.checked)} />
            </Stack>
          ) },
        { id: 'hours', label: 'Working Hours', keywords: 'days hours monday friday weekend start end',
          content: (
            <Stack maw={620} gap="xs">
              <Table verticalSpacing={6}>
                <Table.Thead><Table.Tr><Table.Th>Day</Table.Th><Table.Th>From</Table.Th><Table.Th>To</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {form.values.days.map((d, i) => (
                    <Table.Tr key={DAYS[i]}>
                      <Table.Td><Checkbox label={DAYS[i]} checked={d.on} onChange={(e) => form.setFieldValue(`days.${i}.on`, e.currentTarget.checked)} /></Table.Td>
                      <Table.Td><TimeInput size="xs" w={110} disabled={!d.on} value={d.start} aria-label={`${DAYS[i]} from`}
                                           onChange={(e) => form.setFieldValue(`days.${i}.start`, e.currentTarget.value)} /></Table.Td>
                      <Table.Td><TimeInput size="xs" w={110} disabled={!d.on} value={d.end} aria-label={`${DAYS[i]} to`}
                                           onChange={(e) => form.setFieldValue(`days.${i}.end`, e.currentTarget.value)} /></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              <Group gap="xs">
                <Tooltip label="Monday–Friday 07:00–17:00"><Button size="xs" variant="default" onClick={() => form.setFieldValue('days', weekdays())}>Weekdays 07–17</Button></Tooltip>
                <Button size="xs" variant="default" onClick={() => form.setFieldValue('days', DAYS.map(() => ({ on: true, start: '00:00', end: '23:59' })))}>All day, every day</Button>
              </Group>
              <Text size="sm" c="dimmed">{hours.toFixed(1)} working hours a week; unticked days and the time outside these hours count as after hours.</Text>
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}
