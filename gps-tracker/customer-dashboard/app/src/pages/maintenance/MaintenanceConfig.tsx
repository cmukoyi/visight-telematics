import { useMemo, useState } from 'react';
import {
  ActionIcon, Badge, Button, FileButton, Group, Image, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Text, TextInput, Tooltip,
} from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconCopy, IconLock, IconPencil, IconPhoto, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import dayjs from 'dayjs';
import { useCan, useCategories, usePlaces } from '../../api/hooks';
import {
  mntApi, useLookups, useMaintenanceCatalog, useMaintenanceItems, useMaintenanceRefresh, useMaintenanceTypes, useSchedules,
  useWorkshops, type ItemRow, type LookupKind, type LookupRow, type MaintenanceTypeRow, type Named, type ScheduleRow,
  type WorkshopRow,
} from '../../api/maintenance';
import { ConfigHeader } from '../../components/ConfigHeader';
import { DataGrid } from '../../components/DataGrid';
import { EditorShell, firstError } from '../../components/EditorShell';
import { CheckList } from '../../components/FeaturePicker';
import { TransferList } from '../../components/TransferList';
import { plural } from '../../utils/format';
import classes from '../CatalogPages.module.css';

const SECTION = 'Vehicle Maintenance';
const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const confirmDelete = (title: string, body: string, run: () => Promise<unknown>) => modals.openConfirmModal({
  title, children: <Text size="sm">{body}</Text>, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
  onConfirm: () => { run().catch(fail); },
});

function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <TextInput size="xs" w={260} placeholder="Search" leftSection={<IconSearch size={14} />} value={value}
                    onChange={(e) => onChange(e.currentTarget.value)} />;
}

function RowActions({ onEdit, onDelete, label }: { onEdit: () => void; onDelete: () => void; label: string }) {
  return (
    <Group gap={2} wrap="nowrap">
      <ActionIcon size="sm" variant="subtle" onClick={onEdit} aria-label={`Edit ${label}`}><IconPencil size={15} /></ActionIcon>
      <ActionIcon size="sm" variant="subtle" color="red" onClick={onDelete} aria-label={`Delete ${label}`}><IconTrash size={15} /></ActionIcon>
    </Group>
  );
}

/** A name typed in place, added to a list straight away (an inline "+ Add" in a form). */
function InlineAdd({ placeholder, onAdd }: { placeholder: string; onAdd: (name: string) => Promise<unknown> }) {
  const [name, setName] = useState('');
  const add = async () => {
    if (!name.trim()) return;
    try { await onAdd(name.trim()); setName(''); } catch (e) { fail(e); }
  };
  return (
    <Group gap={6} wrap="nowrap">
      <TextInput size="xs" style={{ flex: 1 }} placeholder={placeholder} value={name} onChange={(e) => setName(e.currentTarget.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} />
      <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={add} disabled={!name.trim()}>Add</Button>
    </Group>
  );
}

// ── Simple lists: vehicle types, workshop chains, workshop types, cost centres ──
const LOOKUPS: Record<LookupKind, { title: string; one: string; description: string; usedBy: string; example: string }> = {
  vehicle_type: { title: 'Vehicle Types', one: 'vehicle type', usedBy: 'Vehicles', example: 'e.g. Light vehicle',
                  description: 'Kinds of vehicle that share maintenance schedules (e.g. every light vehicle: oil change every 10 000 km). Set a vehicle’s type in Configuration → Vehicles.' },
  workshop_chain: { title: 'Workshop Chains', one: 'workshop chain', usedBy: 'Workshops', example: 'e.g. Supa Quick',
                    description: 'Brands or groups that workshops belong to.' },
  workshop_type: { title: 'Workshop Types', one: 'workshop type', usedBy: 'Workshops', example: 'e.g. Tyres',
                   description: 'What workshops do (tyres, electrical, panel beating…).' },
  cost_centre: { title: 'Cost Centres', one: 'cost centre', usedBy: 'Cost items', example: 'e.g. Operations',
                 description: 'Where maintenance costs are charged.' },
};

export function LookupPage({ kind }: { kind: LookupKind }) {
  const meta = LOOKUPS[kind];
  const manage = useCan()('maintenance.configure');
  const refresh = useMaintenanceRefresh();
  const { data: rows = [], isFetching } = useLookups(kind);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<LookupRow | 'new' | null>(null);
  const form = useForm({ initialValues: { name: '' }, validate: { name: (v) => (v.trim() ? null : 'Enter a name') } });
  const open = (r: LookupRow | 'new') => { form.setValues({ name: r === 'new' ? '' : r.name }); setEditing(r); };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      await mntApi.save(`lookups/${kind}`, editing === 'new' ? null : editing!.id, v);
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const shown = rows.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<LookupRow>[] = [
    { headerName: 'Description', field: 'name', flex: 1, sort: 'asc' },
    { headerName: meta.usedBy, field: 'used', width: 140, type: 'numericColumn' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<LookupRow>) => p.data && (
        <RowActions label={meta.one} onEdit={() => open(p.data!)}
                    onDelete={() => confirmDelete(`Delete “${p.data!.name}”?`, `This ${meta.one} is removed.`, async () => {
                      await mntApi.remove(`lookups/${kind}`, p.data!.id); refresh();
                    })} />) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section={SECTION} title={meta.title} description={meta.description}>
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add {meta.one}</Button>}
      </ConfigHeader>
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} {meta.title.toLowerCase()}</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)}
                  overlayNoRowsTemplate={`<span style="opacity:.7">No ${meta.title.toLowerCase()} yet.</span>`} />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? `New ${meta.one}` : `Edit ${meta.one}`}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name description',
          content: <Stack maw={620}><TextInput label="Description" withAsterisk placeholder={meta.example} {...form.getInputProps('name')} data-autofocus /></Stack> },
      ]} />
    </Stack>
  );
}

// ── Maintenance items ──
export function ItemsPage() {
  const manage = useCan()('maintenance.configure');
  const refresh = useMaintenanceRefresh();
  const { data: rows = [], isFetching } = useMaintenanceItems();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<ItemRow | 'new' | null>(null);
  const form = useForm({ initialValues: { name: '' }, validate: { name: (v) => (v.trim() ? null : 'Enter a description') } });
  const open = (r: ItemRow | 'new') => { form.setValues({ name: r === 'new' ? '' : r.name }); setEditing(r); };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      await mntApi.save('items', editing === 'new' ? null : editing!.id, v);
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const shown = rows.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<ItemRow>[] = [
    { headerName: 'Description', field: 'name', flex: 1, sort: 'asc' },
    { headerName: 'Is System', field: 'is_system', width: 120,
      cellRenderer: (p: ICellRendererParams<ItemRow>) => p.data && (p.data.is_system
        ? <Tooltip label="A starter item — it can't be changed or deleted; add your own"><Badge size="sm" variant="light" color="gray" leftSection={<IconLock size={11} />}>System</Badge></Tooltip>
        : <Text size="sm" c="dimmed">No</Text>) },
    { headerName: 'In maintenance types', field: 'types', width: 190, type: 'numericColumn' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<ItemRow>) => p.data && !p.data.is_system && (
        <RowActions label="item" onEdit={() => open(p.data!)}
                    onDelete={() => confirmDelete(`Delete “${p.data!.name}”?`, 'It is taken off the maintenance types that include it.', async () => {
                      await mntApi.remove('items', p.data!.id); refresh();
                    })} />) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section={SECTION} title="Maintenance Items" description="The tasks and parts a maintenance job can include — your own list, e.g. “Change oil filter”, “Licence renewal”.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add maintenance item</Button>}
      </ConfigHeader>
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} items</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => manage && e.data && !e.data.is_system && open(e.data)} />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Maintenance Item' : 'Edit Maintenance Item'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'description name',
          content: <Stack maw={620}><TextInput label="Description" withAsterisk placeholder="e.g. Change oil filter" {...form.getInputProps('name')} data-autofocus /></Stack> },
      ]} />
    </Stack>
  );
}

// ── Maintenance types ──
const durationText = (d: number, h: number) => `${d} day${d === 1 ? '' : 's'} ${h} hour${h === 1 ? '' : 's'}`;

export function TypesPage() {
  const manage = useCan()('maintenance.configure');
  const refresh = useMaintenanceRefresh();
  const { data: rows = [], isFetching } = useMaintenanceTypes();
  const { data: items = [] } = useMaintenanceItems();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<MaintenanceTypeRow | 'new' | null>(null);
  const form = useForm({
    initialValues: { name: '', duration_days: 1, duration_hours: 0, item_ids: [] as string[] },
    validate: { name: (v) => (v.trim() ? null : 'Enter a description') },
  });
  const open = (r: MaintenanceTypeRow | 'new') => {
    form.setValues(r === 'new' ? { name: '', duration_days: 1, duration_hours: 0, item_ids: [] }
      : { name: r.name, duration_days: r.duration_days, duration_hours: r.duration_hours, item_ids: r.item_ids });
    setEditing(r);
  };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      await mntApi.save('types', editing === 'new' ? null : editing!.id, v);
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const itemName = new Map(items.map((i) => [i.id, i.name]));
  const shown = rows.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<MaintenanceTypeRow>[] = [
    { headerName: 'Description', field: 'name', flex: 1, sort: 'asc', minWidth: 200 },
    { headerName: 'Expected Duration', width: 190, valueGetter: (p) => p.data && durationText(p.data.duration_days, p.data.duration_hours) },
    { headerName: 'Maintenance Items', flex: 1.5, minWidth: 220, valueGetter: (p) => p.data?.item_ids.map((i) => itemName.get(i)).filter(Boolean).join(', ') || '—',
      tooltipValueGetter: (p) => p.value },
    { headerName: 'Schedules', field: 'schedules', width: 120, type: 'numericColumn' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<MaintenanceTypeRow>) => p.data && (
        <RowActions label="maintenance type" onEdit={() => open(p.data!)}
                    onDelete={() => confirmDelete(`Delete “${p.data!.name}”?`, 'Schedules using it must be changed first.', async () => {
                      await mntApi.remove('types', p.data!.id); refresh();
                    })} />) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section={SECTION} title="Maintenance Types" description="Kinds of job (e.g. Minor service), the items each includes and how long it usually takes.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add maintenance type</Button>}
      </ConfigHeader>
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} types</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} tooltipShowDelay={300}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)} />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Maintenance Type' : 'Edit Maintenance Type'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'description expected duration days hours',
          content: (
            <Stack maw={620}>
              <TextInput label="Description" withAsterisk placeholder="e.g. Minor service" {...form.getInputProps('name')} data-autofocus />
              <SimpleGrid cols={2}>
                <NumberInput label="Expected duration (days)" min={0} max={365} {...form.getInputProps('duration_days')} />
                <NumberInput label="Expected duration (hours)" min={0} max={23} {...form.getInputProps('duration_hours')} />
              </SimpleGrid>
              <Text size="xs" c="dimmed">Sets a job’s planned end from its planned start.</Text>
            </Stack>
          ) },
        { id: 'items', label: 'Maintenance Items', keywords: 'items tasks parts checklist',
          content: (
            <Stack maw={760}>
              <CheckList items={items.map((i) => ({ value: i.id, label: i.name }))} value={form.values.item_ids}
                         onChange={(v) => form.setFieldValue('item_ids', v)} height={300} empty="No items yet — add one below." />
              <InlineAdd placeholder="New item, e.g. Replace spark plugs" onAdd={async (name) => {
                const it = await mntApi.save<Named>('items', null, { name });
                form.setFieldValue('item_ids', [...form.values.item_ids, it.id]);
                refresh();
              }} />
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}

// ── Workshops ──
export function WorkshopsPage() {
  const manage = useCan()('maintenance.configure');
  const refresh = useMaintenanceRefresh();
  const { data: rows = [], isFetching } = useWorkshops();
  const { data: catalog } = useMaintenanceCatalog();
  const { data: places = [] } = usePlaces();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<WorkshopRow | 'new' | null>(null);
  const blank = { name: '', poi_id: null as string | null, chain_id: null as string | null, phone: '', working_hours: '',
                  image_data: null as string | null, type_ids: [] as string[] };
  const form = useForm({ initialValues: blank, validate: { name: (v) => (v.trim() ? null : 'Enter a description') } });
  const open = (r: WorkshopRow | 'new') => {
    form.setValues(r === 'new' ? blank : { name: r.name, poi_id: r.poi_id, chain_id: r.chain_id, phone: r.phone ?? '',
                                           working_hours: r.working_hours ?? '', image_data: r.image_data, type_ids: r.type_ids });
    setEditing(r);
  };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      await mntApi.save('workshops', editing === 'new' ? null : editing!.id, v);
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const typeName = new Map((catalog?.workshop_type ?? []).map((t) => [t.id, t.name]));
  const shown = rows.filter((r) => !search || `${r.name} ${r.place ?? ''} ${r.chain ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<WorkshopRow>[] = [
    { headerName: 'Description', field: 'name', flex: 1, sort: 'asc', minWidth: 180 },
    { headerName: 'Place', field: 'place', flex: 1, minWidth: 160, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Workshop Chain', field: 'chain', width: 170, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Phone', field: 'phone', width: 140, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Workshop Types', flex: 1, minWidth: 160, valueGetter: (p) => p.data?.type_ids.map((t) => typeName.get(t)).filter(Boolean).join(', ') || '—' },
    { headerName: 'Jobs', field: 'jobs', width: 90, type: 'numericColumn' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<WorkshopRow>) => p.data && (
        <RowActions label="workshop" onEdit={() => open(p.data!)}
                    onDelete={() => confirmDelete(`Delete “${p.data!.name}”?`, 'A workshop that has jobs can’t be deleted.', async () => {
                      await mntApi.remove('workshops', p.data!.id); refresh();
                    })} />) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section={SECTION} title="Workshops" description="Where maintenance is done. Link a workshop to a Place to see vehicles arrive and leave.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add workshop</Button>}
      </ConfigHeader>
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} workshops</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)} />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Workshop' : 'Edit Workshop'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'description place chain phone',
          content: (
            <Stack maw={620}>
              <TextInput label="Description" withAsterisk placeholder="e.g. Hilux Centre Midrand" {...form.getInputProps('name')} data-autofocus />
              <Select label="Place" placeholder="None" clearable searchable data={places.map((p) => ({ value: String(p.id), label: p.name }))}
                      value={form.values.poi_id} onChange={(v) => form.setFieldValue('poi_id', v)}
                      description="A place drawn under Configuration → Places" />
              <Select label="Workshop chain" placeholder="None" clearable searchable
                      data={(catalog?.workshop_chain ?? []).map((c) => ({ value: c.id, label: c.name }))}
                      value={form.values.chain_id} onChange={(v) => form.setFieldValue('chain_id', v)} />
              <InlineAdd placeholder="New workshop chain" onAdd={async (name) => {
                const c = await mntApi.save<Named>('lookups/workshop_chain', null, { name });
                form.setFieldValue('chain_id', c.id);
                refresh();
              }} />
              <TextInput label="Phone" placeholder="e.g. 011 555 0100" {...form.getInputProps('phone')} />
              <TextInput label="Working hours" placeholder="e.g. Mon–Fri 07:30–17:00, Sat 08:00–12:00" {...form.getInputProps('working_hours')} />
              <div>
                <Text size="sm" fw={500} mb={4}>Image</Text>
                <Group align="flex-end">
                  {form.values.image_data
                    ? <Image src={form.values.image_data} h={110} w={180} radius="md" fit="cover" alt="Workshop" />
                    : <Paper withBorder h={110} w={180} radius="md" style={{ display: 'grid', placeItems: 'center' }}><IconPhoto size={30} opacity={0.4} /></Paper>}
                  <Stack gap={6}>
                    <FileButton accept="image/png,image/jpeg,image/webp" onChange={(file) => {
                      if (!file) return;
                      if (file.size > 600_000) { notifications.show({ color: 'orange', message: 'Use an image up to 600 KB' }); return; }
                      const reader = new FileReader();
                      reader.onload = () => form.setFieldValue('image_data', String(reader.result));
                      reader.readAsDataURL(file);
                    }}>
                      {(props) => <Button size="xs" variant="default" leftSection={<IconPhoto size={14} />} {...props}>Upload image</Button>}
                    </FileButton>
                    {form.values.image_data && <Button size="xs" variant="subtle" color="red" onClick={() => form.setFieldValue('image_data', null)}>Remove</Button>}
                  </Stack>
                </Group>
              </div>
            </Stack>
          ) },
        { id: 'types', label: 'Workshop Types', keywords: 'types tyres electrical',
          content: (
            <Stack maw={760}>
              <CheckList items={(catalog?.workshop_type ?? []).map((t) => ({ value: t.id, label: t.name }))} value={form.values.type_ids}
                         onChange={(v) => form.setFieldValue('type_ids', v)} height={260} empty="No workshop types yet — add one below." />
              <InlineAdd placeholder="New workshop type, e.g. Tyres" onAdd={async (name) => {
                const t = await mntApi.save<Named>('lookups/workshop_type', null, { name });
                form.setFieldValue('type_ids', [...form.values.type_ids, t.id]);
                refresh();
              }} />
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}

// ── Schedules ──
const METERS = [
  { key: 'km', label: 'Odometer', unit: 'km', step: 1000 },
  { key: 'months', label: 'Months', unit: 'months', step: 1 },
  { key: 'hours', label: 'Engine hours', unit: 'h', step: 50 },
] as const;
type Meter = (typeof METERS)[number]['key'];
type ScheduleForm = {
  type_id: string | null; name: string; starts_on: Date; recurring: boolean; is_active: boolean;
  remind_km: number; remind_days: number; remind_hours: number; vehicle_type_ids: string[]; imeis: string[];
} & Record<`${'at' | 'every' | 'until'}_${Meter}`, number | ''>;

const emptySchedule = (): ScheduleForm => ({
  type_id: null, name: '', starts_on: new Date(), recurring: true, is_active: true, remind_km: 500, remind_days: 14, remind_hours: 10,
  vehicle_type_ids: [], imeis: [], at_km: '', at_months: '', at_hours: '', every_km: '', every_months: '', every_hours: '',
  until_km: '', until_months: '', until_hours: '',
});

/** In words: "At 10 000 km, then every 10 000 km or 12 months (whichever comes first), until 200 000 km". */
function scheduleSentence(v: ScheduleForm) {
  const part = (row: 'at' | 'every' | 'until') => METERS.map((m) => {
    const n = v[`${row}_${m.key}`];
    return n === '' ? null : `${Number(n).toLocaleString()} ${m.unit}`;
  }).filter(Boolean) as string[];
  const at = part('at'), every = part('every'), until = part('until');
  if (!at.length) return 'Set at least one “At” value.';
  const either = (p: string[]) => (p.length > 1 ? `${p.join(' or ')} (whichever comes first)` : p[0]);
  let s = `First due at ${either(at)}`;
  if (v.recurring && every.length) s += `, then every ${either(every)} after each completed job`;
  if (v.recurring && until.length) s += `, until ${until.join(' / ')}`;
  return `${s}. Months count from ${dayjs(v.starts_on).format('D MMM YYYY')}.`;
}

export function SchedulesPage() {
  const manage = useCan()('maintenance.configure');
  const refresh = useMaintenanceRefresh();
  const { data: rows = [], isFetching } = useSchedules();
  const { data: catalog } = useMaintenanceCatalog();
  const { data: categories = [] } = useCategories();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ScheduleRow | null>(null);
  const [editing, setEditing] = useState<ScheduleRow | 'new' | null>(null);
  const form = useForm<ScheduleForm>({
    initialValues: emptySchedule(),
    validate: {
      type_id: (v) => (v ? null : 'Choose a maintenance type'),
      name: (v) => (v.trim() ? null : 'Enter a description'),
    },
  });
  const open = (r: ScheduleRow | 'new') => {
    if (r === 'new') form.setValues(emptySchedule());
    else {
      const n = (x: number | null) => (x == null ? '' : x);
      form.setValues({
        type_id: r.type_id, name: r.name, starts_on: dayjs(r.starts_on).toDate(), recurring: r.recurring, is_active: r.is_active,
        remind_km: r.remind_km, remind_days: r.remind_days, remind_hours: r.remind_hours,
        vehicle_type_ids: r.vehicle_type_ids, imeis: r.imeis,
        at_km: n(r.at_km), at_months: n(r.at_months), at_hours: n(r.at_hours),
        every_km: n(r.every_km), every_months: n(r.every_months), every_hours: n(r.every_hours),
        until_km: n(r.until_km), until_months: n(r.until_months), until_hours: n(r.until_hours),
      });
    }
    setEditing(r);
  };
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    const num = (x: number | '') => (x === '' ? null : x);
    const body = {
      ...v, starts_on: dayjs(v.starts_on).format('YYYY-MM-DD'),
      ...Object.fromEntries((['at', 'every', 'until'] as const).flatMap((row) => METERS.map((m) => [`${row}_${m.key}`, num(v[`${row}_${m.key}`])]))),
    };
    try {
      await mntApi.save('schedules', editing === 'new' ? null : editing!.id, body);
      refresh();
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const copy = async () => {
    if (!selected) return;
    try { await mntApi.post(`schedules/${selected.id}/copy`); refresh(); notifications.show({ message: `${selected.name} copied` }); }
    catch (e) { fail(e); }
  };

  // Vehicles the schedule covers: by type, plus picked one by one
  const vehicles = catalog?.vehicles ?? [];
  const covered = useMemo(() => {
    const types = new Set(form.values.vehicle_type_ids), picked = new Set(form.values.imeis);
    return vehicles.filter((v) => picked.has(v.imei) || (v.type_id && types.has(v.type_id))).length;
  }, [vehicles, form.values.vehicle_type_ids, form.values.imeis]);
  const typeName = new Map((catalog?.vehicle_type ?? []).map((t) => [t.id, t.name]));

  const shown = rows.filter((r) => !search || `${r.name} ${r.type ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<ScheduleRow>[] = [
    { headerName: '# of Vehicles', field: 'vehicle_count', width: 130, type: 'numericColumn' },
    { headerName: 'Maintenance Type', field: 'type', flex: 1, minWidth: 160 },
    { headerName: 'Description', field: 'name', flex: 1, minWidth: 180, sort: 'asc' },
    { headerName: 'At', field: 'at', flex: 1, minWidth: 150 },
    { headerName: 'Recurring', field: 'every', flex: 1, minWidth: 150, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Until', field: 'until', width: 150, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Vehicle Types', minWidth: 150, valueGetter: (p) => p.data?.vehicle_type_ids.map((t) => typeName.get(t)).filter(Boolean).join(', ') || '—' },
    { headerName: 'Active', field: 'is_active', width: 100,
      cellRenderer: (p: ICellRendererParams<ScheduleRow>) => p.data && <Badge size="sm" variant="light" color={p.data.is_active ? 'green' : 'gray'}>{p.data.is_active ? 'Yes' : 'Paused'}</Badge> },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<ScheduleRow>) => p.data && (
        <RowActions label="schedule" onEdit={() => open(p.data!)}
                    onDelete={() => confirmDelete(`Delete “${p.data!.name}”?`, 'Saved jobs stay; it stops projecting new ones.', async () => {
                      await mntApi.remove('schedules', p.data!.id); refresh();
                    })} />) }] : []),
  ];

  const meterRow = (row: 'at' | 'every' | 'until', label: string, hint: string) => (
    <div>
      <Text size="sm" fw={500}>{label}</Text>
      <Text size="xs" c="dimmed" mb={4}>{hint}</Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        {METERS.map((m) => (
          <NumberInput key={m.key} placeholder={m.label} min={1} step={m.step} thousandSeparator=" " allowDecimal={false}
                       rightSection={<Text size="xs" c="dimmed">{m.unit}</Text>} rightSectionWidth={56} aria-label={`${label} ${m.label}`}
                       {...form.getInputProps(`${row}_${m.key}`)} />
        ))}
      </SimpleGrid>
    </div>
  );

  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section={SECTION} title="Maintenance Schedules"
                    description="When each maintenance type falls due — by odometer, months or engine hours, whichever comes first — and for which vehicle types or vehicles.">
        {manage && <Tooltip label={selected ? `Copy “${selected.name}”` : 'Select a schedule to copy'}>
          <Button size="xs" variant="default" leftSection={<IconCopy size={14} />} onClick={copy} disabled={!selected}>Copy</Button></Tooltip>}
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add maintenance schedule</Button>}
      </ConfigHeader>
      <Group mb="sm"><SearchBox value={search} onChange={setSearch} /><Text size="sm" c="dimmed">{shown.length} schedules</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id}
                  rowSelection="single" onSelectionChanged={(e) => setSelected(e.api.getSelectedRows()[0] ?? null)}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No schedules yet — add one, e.g. Oil change every 10 000 km.</span>' />
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Maintenance Schedule' : 'Edit Maintenance Schedule'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'schedule', label: 'Schedule', keywords: 'type description at every until recurring odometer months engine hours remind',
          content: (
            <Stack maw={760}>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <Select label="Maintenance type" withAsterisk searchable placeholder="Choose…"
                        data={(catalog?.types ?? []).map((t) => ({ value: t.id, label: t.name }))}
                        value={form.values.type_id} onChange={(v) => {
                          form.setFieldValue('type_id', v);
                          const t = catalog?.types.find((x) => x.id === v);
                          if (t && !form.values.name) form.setFieldValue('name', t.name);
                        }} error={form.errors.type_id} />
                <TextInput label="Description" withAsterisk placeholder="e.g. Oil change every 10 000 km" {...form.getInputProps('name')} />
              </SimpleGrid>
              <InlineAdd placeholder="New maintenance type, e.g. Minor service" onAdd={async (name) => {
                const t = await mntApi.save<Named>('types', null, { name, duration_days: 1, duration_hours: 0, item_ids: [] });
                form.setFieldValue('type_id', t.id);
                if (!form.values.name) form.setFieldValue('name', name);
                refresh();
              }} />
              {meterRow('at', 'At', 'When it first falls due: an odometer reading, months after the start date, or engine hours')}
              <Group gap="xl">
                <Switch label="Recurring" checked={form.values.recurring} onChange={(e) => form.setFieldValue('recurring', e.currentTarget.checked)} />
                <Switch label="Active" checked={form.values.is_active} onChange={(e) => form.setFieldValue('is_active', e.currentTarget.checked)} />
                <DateInput label="Months count from" valueFormat="D MMM YYYY" w={200} value={form.values.starts_on}
                           onChange={(d) => d && form.setFieldValue('starts_on', d)} />
              </Group>
              {form.values.recurring && meterRow('every', 'Every', 'Repeats this long after each completed job (its odometer, engine hours and date)')}
              {form.values.recurring && meterRow('until', 'Until (optional)', 'Stops once a threshold would pass this')}
              <div>
                <Text size="sm" fw={500}>Remind before</Text>
                <Text size="xs" c="dimmed" mb={4}>It turns “Due” (and notifies) this close to the threshold; past it, “Overdue”</Text>
                <SimpleGrid cols={{ base: 1, sm: 3 }}>
                  <NumberInput min={0} step={100} thousandSeparator=" " rightSection={<Text size="xs" c="dimmed">km</Text>} rightSectionWidth={40} {...form.getInputProps('remind_km')} aria-label="Remind before km" />
                  <NumberInput min={0} rightSection={<Text size="xs" c="dimmed">days</Text>} rightSectionWidth={48} {...form.getInputProps('remind_days')} aria-label="Remind before days" />
                  <NumberInput min={0} rightSection={<Text size="xs" c="dimmed">h</Text>} rightSectionWidth={40} {...form.getInputProps('remind_hours')} aria-label="Remind before engine hours" />
                </SimpleGrid>
              </div>
              <Paper withBorder p="sm" radius="md"><Text size="sm">{scheduleSentence(form.values)}</Text></Paper>
            </Stack>
          ) },
        { id: 'vehicles', label: 'Vehicles', keywords: 'vehicles vehicle types group assign',
          content: (
            <Stack maw={760}>
              <Text size="sm">Covers <b>{covered}</b> vehicle{covered === 1 ? '' : 's'}: every vehicle of the chosen types (including ones added later), plus any picked below.</Text>
              <div>
                <Text size="sm" fw={500} mb={6}>Vehicle types</Text>
                <CheckList items={(catalog?.vehicle_type ?? []).map((t) => ({
                  value: t.id, label: t.name, description: plural(vehicles.filter((v) => v.type_id === t.id).length, 'vehicle') }))}
                           value={form.values.vehicle_type_ids} onChange={(v) => form.setFieldValue('vehicle_type_ids', v)} height={180}
                           empty="No vehicle types yet (Configuration → Vehicle Types)." />
              </div>
              <div>
                <Text size="sm" fw={500} mb={6}>Individual vehicles</Text>
                <TransferList items={vehicles.map((v) => ({ value: v.imei, label: v.name, group: v.group, type: v.type_id ? typeName.get(v.type_id) ?? null : null }))}
                              value={form.values.imeis} onChange={(v) => form.setFieldValue('imeis', v)}
                              groups={categories.map((c) => c.name)}
                              types={(catalog?.vehicle_type ?? []).map((t) => ({ value: t.name, label: t.name }))} />
              </div>
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}
