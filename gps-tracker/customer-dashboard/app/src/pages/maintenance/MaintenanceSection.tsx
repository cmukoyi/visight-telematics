import { useMemo, useState } from 'react';
import { Navigate, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Button, Group, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Title, Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Sparkline } from '@mantine/charts';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconCar, IconCurrencyDollar, IconEye, IconListDetails, IconPencil, IconPlus, IconSearch, IconStethoscope, IconTool, IconTrash,
} from '@tabler/icons-react';
import type { ColDef, ColGroupDef, ICellRendererParams } from 'ag-grid-community';
import dayjs from 'dayjs';
import { useCan, useCategories, type Range } from '../../api/hooks';
import {
  mntApi, useCosts, useDtc, useJobs, useMaintenanceCatalog, useMaintenanceRefresh, useMaintenanceSummary, useOverview,
  type CostRow, type JobRow, type OverviewRow, type SummaryRow,
} from '../../api/maintenance';
import { ConfigHeader } from '../../components/ConfigHeader';
import { DataGrid } from '../../components/DataGrid';
import { RangePicker, defaultRange } from '../../components/RangePicker';
import { dateTime } from '../../utils/format';
import { msg, useT } from '../../i18n';
import hub from '../analytics/ReportsHub.module.css';
import classes from '../CatalogPages.module.css';
import { CostEditor, JobEditor, StatusBadge, dueText, money } from './Editors';

const ROOT = '/maintenance';
const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const Header = ({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) => (
  <ConfigHeader root={ROOT} rootLabel="Vehicle Maintenance" title={title} description={description}>{children}</ConfigHeader>
);
const day = (v: string | null) => (v ? dayjs(v).format('DD MMM YYYY') : '—');
const today = (): Range => ({ from: dayjs().startOf('day').toDate(), to: dayjs().endOf('day').toDate() });

const TILES = [
  { to: 'overview', title: msg('app.maintenance.overview', 'Overview'), description: msg('app.maintenance.overview_desc', 'Vehicles in the workshop and maintenance costs'), icon: IconEye },
  { to: 'summary', title: msg('app.maintenance.summary', 'Summary by Vehicle'), description: msg('app.maintenance.summary_desc', 'Each vehicle’s next and previous maintenance'), icon: IconCar },
  { to: 'list', title: msg('app.maintenance.list', 'Maintenance List'), description: msg('app.maintenance.list_desc', 'Due, overdue, booked and completed jobs'), icon: IconTool },
  { to: 'costs', title: msg('app.maintenance.costs', 'Cost Item'), description: msg('app.maintenance.costs_desc', 'What maintenance costs, per vehicle and cost centre'), icon: IconCurrencyDollar },
  { to: 'dtc', title: msg('app.maintenance.dtc', 'DTC'), description: msg('app.maintenance.dtc_desc', 'Engine fault codes the vehicles report'), icon: IconStethoscope },
];

function Hub() {
  const navigate = useNavigate();
  const tr = useT();
  return (
    <Stack p="lg" gap="lg">
      <Title order={2}>{tr('app.nav.maintenance', 'Vehicle Maintenance')}</Title>
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }} spacing="lg" maw={1200}>
        {TILES.map((t) => (
          <UnstyledButton key={t.to} className={hub.tile} onClick={() => navigate(t.to)}>
            <span className={hub.icon}><t.icon size={44} stroke={1.3} /></span>
            <Text fw={600} mt="sm">{tr(t.title)}</Text>
            <Text size="xs" c="dimmed" ta="center">{tr(t.description)}</Text>
          </UnstyledButton>
        ))}
      </SimpleGrid>
    </Stack>
  );
}

// ── Overview ──
function Stat({ label, value, color, onClick }: { label: string; value: string | number; color?: string; onClick?: () => void }) {
  return (
    <UnstyledButton onClick={onClick} style={{ textAlign: 'left' }}>
      <Paper withBorder p="md" radius="lg">
        <Text size="sm" c="dimmed">{label}</Text>
        <Text fz={32} fw={650} c={color} lh={1.2}>{value}</Text>
      </Paper>
    </UnstyledButton>
  );
}

function OverviewCard({ kind }: { kind: 'workshop' | 'costs' }) {
  const navigate = useNavigate();
  const [range, setRange] = useState<Range>(today);
  const [by, setBy] = useState<'vehicle_group' | 'vehicle_type'>('vehicle_group');
  const { data, isFetching } = useOverview(range, by);
  const rows = data?.rows ?? [];
  const drill = (r: OverviewRow) => {
    const catalogKey = by === 'vehicle_group' ? 'vehicle_group' : 'vehicle_type';
    navigate(`${ROOT}/${kind === 'workshop' ? 'list' : 'costs'}?${catalogKey}=${encodeURIComponent(r.name)}`);
  };
  return (
    <Paper withBorder radius="lg" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap">
        <Text fz={20} fw={600}>{kind === 'workshop' ? 'Vehicles in Workshop' : 'Maintenance Costs'}</Text>
        <RangePicker value={range} onChange={setRange} />
      </Group>
      <SegmentedControl size="xs" mb="sm" value={by} onChange={(v) => setBy(v as typeof by)}
                        data={[{ value: 'vehicle_group', label: 'Vehicle Groups' }, { value: 'vehicle_type', label: 'Vehicle Types' }]} />
      <ScrollArea.Autosize mah={460} type="auto">
        <Table striped highlightOnHover fz="sm" stickyHeader>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Description</Table.Th>
              {kind === 'workshop' ? <><Table.Th ta="right">Vehicles</Table.Th><Table.Th ta="right">In Workshop</Table.Th><Table.Th>Trend (last {data?.trend_days.length ?? 14} days)</Table.Th></>
                : <Table.Th ta="right">Total Cost</Table.Th>}
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.name}>
                <Table.Td>{r.name}</Table.Td>
                {kind === 'workshop' ? <>
                  <Table.Td ta="right">{r.vehicles}</Table.Td>
                  <Table.Td ta="right" fw={r.in_workshop ? 650 : undefined}>{r.in_workshop}</Table.Td>
                  <Table.Td w={160}>{r.trend.some(Boolean)
                    ? <Sparkline w={140} h={28} data={r.trend} curveType="linear" color="var(--viz-1)" fillOpacity={0.3} strokeWidth={1.5} />
                    : <Text size="xs" c="dimmed">None</Text>}</Table.Td>
                </> : <Table.Td ta="right" style={{ fontVariantNumeric: 'tabular-nums' }}>{money(r.cost)}</Table.Td>}
                <Table.Td><Tooltip label={kind === 'workshop' ? 'Open their maintenance' : 'Open their costs'}>
                  <ActionIcon size="sm" variant="subtle" onClick={() => drill(r)} aria-label="Open"><IconListDetails size={16} /></ActionIcon></Tooltip></Table.Td>
              </Table.Tr>
            ))}
            {!rows.length && <Table.Tr><Table.Td colSpan={5}><Text size="sm" c="dimmed">{isFetching ? 'Loading…' : 'No vehicles.'}</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </ScrollArea.Autosize>
    </Paper>
  );
}

function Overview() {
  const navigate = useNavigate();
  const month: Range = { from: dayjs().startOf('month').toDate(), to: dayjs().endOf('day').toDate() };
  const { data } = useOverview(month, 'vehicle_group');
  return (
    <Stack p="lg" gap="md">
      <Header title="Overview" description="What needs doing, what’s in the workshop and what maintenance costs." />
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Stat label="Overdue" value={data?.overdue ?? '—'} color={data?.overdue ? 'red' : undefined} onClick={() => navigate(`${ROOT}/list?status=Overdue`)} />
        <Stat label="Due soon" value={data?.due ?? '—'} color={data?.due ? 'orange' : undefined} onClick={() => navigate(`${ROOT}/list?status=Due`)} />
        <Stat label="In the workshop now" value={data?.in_workshop_now ?? '—'} onClick={() => navigate(`${ROOT}/list?status=In%20Progress`)} />
        <Stat label="Costs this month" value={data ? money(data.cost) : '—'} onClick={() => navigate(`${ROOT}/costs`)} />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <OverviewCard kind="workshop" />
        <OverviewCard kind="costs" />
      </SimpleGrid>
    </Stack>
  );
}

// ── Summary by vehicle ──
function Summary() {
  const manage = useCan()('maintenance.manage');
  const { data: rows = [], isFetching } = useMaintenanceSummary();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<JobRow | null>(null);
  const shown = rows.filter((r) => !search || `${r.vehicle} ${r.next?.description ?? ''} ${r.next?.type ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  const edit = (j: JobRow | null) => manage && j && (
    <Tooltip label={j.projected ? 'Book it' : 'Edit'}><ActionIcon size="sm" variant="subtle" onClick={() => setEditing(j)} aria-label="Edit maintenance">
      <IconPencil size={15} /></ActionIcon></Tooltip>);
  const cols: (ColDef<SummaryRow> | ColGroupDef<SummaryRow>)[] = [
    { headerName: 'Vehicle', children: [
      { headerName: 'Description', field: 'vehicle', sort: 'asc', minWidth: 170, flex: 1 },
      { headerName: 'Current Odometer', field: 'odometer_km', width: 150, type: 'numericColumn', valueFormatter: (p) => (p.value == null ? '—' : `${Math.round(p.value).toLocaleString()} km`) },
      { headerName: 'Engine Hours', field: 'engine_hours', width: 125, type: 'numericColumn', hide: true, valueFormatter: (p) => (p.value == null ? '—' : `${p.value} h`) },
    ] },
    { headerName: 'Next Maintenance', children: [
      { headerName: 'Status', width: 125, valueGetter: (p) => p.data?.next?.status ?? null,
        cellRenderer: (p: ICellRendererParams<SummaryRow>) => (p.data?.next ? <StatusBadge status={p.data.next.status} /> : '—') },
      { headerName: 'Planned', width: 125, valueGetter: (p) => p.data?.next?.planned_start ?? null, valueFormatter: (p) => day(p.value) },
      { headerName: 'Odometer', width: 120, type: 'numericColumn', valueGetter: (p) => p.data?.next?.odometer_km ?? null,
        valueFormatter: (p) => (p.value == null ? '—' : Math.round(p.value).toLocaleString()) },
      { headerName: 'Type', flex: 1, minWidth: 160, valueGetter: (p) => p.data?.next?.type ?? p.data?.next?.description ?? '—',
        tooltipValueGetter: (p) => (p.data?.next ? dueText(p.data.next) || p.data.next.description : null) },
      { headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, cellRenderer: (p: ICellRendererParams<SummaryRow>) => edit(p.data?.next ?? null) },
    ] },
    { headerName: 'Previous Maintenance', children: [
      { headerName: 'Completed', width: 125, valueGetter: (p) => p.data?.previous?.actual_end ?? null, valueFormatter: (p) => day(p.value) },
      { headerName: 'Odometer', width: 120, type: 'numericColumn', valueGetter: (p) => p.data?.previous?.odometer_km ?? null,
        valueFormatter: (p) => (p.value == null ? '—' : Math.round(p.value).toLocaleString()) },
      { headerName: 'Type', flex: 1, minWidth: 150, valueGetter: (p) => p.data?.previous?.type ?? '—' },
      { headerName: 'Description', flex: 1, minWidth: 150, valueGetter: (p) => p.data?.previous?.description ?? '—' },
      { headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, cellRenderer: (p: ICellRendererParams<SummaryRow>) => edit(p.data?.previous ?? null) },
    ] },
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <Header title="Summary by Vehicle" description="Each vehicle’s current odometer, its next maintenance (booked or worked out from schedules) and its last completed one." />
      <Group mb="sm"><TextInput size="xs" w={260} placeholder="Search" leftSection={<IconSearch size={14} />} value={search}
                                onChange={(e) => setSearch(e.currentTarget.value)} /><Text size="sm" c="dimmed">{shown.length} vehicles</Text></Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.imei} tooltipShowDelay={300}
                  stateKey="maintenance-summary" />
      </Paper>
      <JobEditor job={editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}

// ── Maintenance list ──
function MaintenanceList() {
  const manage = useCan()('maintenance.manage');
  const refresh = useMaintenanceRefresh();
  const [params] = useSearchParams();
  const { data: catalog } = useMaintenanceCatalog();
  const { data: categories = [] } = useCategories();
  const [range, setRange] = useState<Range>(() => ({ from: dayjs().subtract(30, 'day').startOf('day').toDate(), to: dayjs().add(30, 'day').endOf('day').toDate() }));
  const typeFromName = (name: string | null) => catalog?.vehicle_type.find((t) => t.name === name)?.id ?? null;
  const [vehicleGroup, setVehicleGroup] = useState<string | null>(params.get('vehicle_group'));
  const [vehicleTypeName] = useState<string | null>(params.get('vehicle_type'));
  const [vehicleType, setVehicleType] = useState<string | null>(null);
  const vehicleTypeId = vehicleType ?? typeFromName(vehicleTypeName);
  const [typeId, setTypeId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(params.get('status'));
  const [workshop, setWorkshop] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const { data: rows = [], isFetching } = useJobs({ range, status, type_id: typeId, workshop_id: workshop, vehicle_group: vehicleGroup, vehicle_type_id: vehicleTypeId });
  const [editing, setEditing] = useState<JobRow | 'new' | null>(null);
  const [costFor, setCostFor] = useState<JobRow | null>(null);
  const shown = rows.filter((r) => !search || `${r.vehicle} ${r.description} ${r.reference ?? ''} ${r.type ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  const remove = (j: JobRow) => modals.openConfirmModal({
    title: `Delete “${j.description}”?`, children: <Text size="sm">Its cost items stay, without the link.</Text>,
    labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: () => { mntApi.remove('jobs', j.id).then(refresh).catch(fail); },
  });
  const cols: ColDef<JobRow>[] = [
    { headerName: 'Vehicle', field: 'vehicle', minWidth: 150, flex: 1 },
    { headerName: 'Description', field: 'description', minWidth: 170, flex: 1, tooltipValueGetter: (p) => (p.data?.projected ? dueText(p.data) : p.data?.description) },
    { headerName: 'Reference', field: 'reference', width: 120, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Maintenance Type', field: 'type', minWidth: 150, flex: 1, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Status', field: 'status', width: 130, cellRenderer: (p: ICellRendererParams<JobRow>) => p.data && <StatusBadge status={p.data.status} /> },
    { headerName: 'Planned Start', field: 'planned_start', width: 130, sort: 'asc', valueFormatter: (p) => day(p.value) },
    { headerName: 'Actual Start', field: 'actual_start', width: 130, valueFormatter: (p) => day(p.value) },
    { headerName: 'Maint. Odometer', field: 'odometer_km', width: 140, type: 'numericColumn',
      valueFormatter: (p) => (p.value == null ? '—' : Math.round(p.value).toLocaleString()), headerTooltip: 'Due at (projected) or at the job (saved)' },
    { headerName: 'Workshop', field: 'workshop', width: 150, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Cost', field: 'cost', width: 110, type: 'numericColumn', valueFormatter: (p) => (p.value == null ? '—' : money(p.value)) },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<JobRow>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <Tooltip label={p.data.projected ? 'Book it' : 'Edit'}><ActionIcon size="sm" variant="subtle" onClick={() => setEditing(p.data!)} aria-label="Edit maintenance">
            <IconPencil size={15} /></ActionIcon></Tooltip>
          <Tooltip label={p.data.projected ? 'Worked out from a schedule — nothing to delete' : 'Delete'}>
            <ActionIcon size="sm" variant="subtle" color="red" disabled={p.data.projected} onClick={() => remove(p.data!)} aria-label="Delete maintenance">
              <IconTrash size={15} /></ActionIcon></Tooltip>
        </Group>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <Header title="Maintenance List" description="Jobs worked out from schedules (Overdue, Due, Recommended) and saved ones (Booked, In Progress, Completed). Overdue jobs always show.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>Add maintenance</Button>}
      </Header>
      <Paper withBorder p="sm" mb="sm">
        <Group gap="xs" wrap="wrap">
          <RangePicker value={range} onChange={setRange} />
          <Select size="sm" w={170} placeholder="Vehicle group" clearable data={categories.map((c) => c.name)} value={vehicleGroup} onChange={setVehicleGroup} />
          <Select size="sm" w={170} placeholder="Vehicle type" clearable data={(catalog?.vehicle_type ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={vehicleTypeId} onChange={setVehicleType} />
          <Select size="sm" w={190} placeholder="Maintenance type" clearable searchable data={(catalog?.types ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={typeId} onChange={setTypeId} />
          <Select size="sm" w={150} placeholder="Status" clearable data={catalog?.statuses ?? []} value={status} onChange={setStatus} />
          <Select size="sm" w={170} placeholder="Workshop" clearable searchable data={(catalog?.workshops ?? []).map((w) => ({ value: w.id, label: w.name }))}
                  value={workshop} onChange={setWorkshop} />
          <TextInput size="sm" w={200} placeholder="Search" leftSection={<IconSearch size={14} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <Text size="sm" c="dimmed" ml="auto">{shown.length} jobs</Text>
        </Group>
      </Paper>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} tooltipShowDelay={300}
                  stateKey="maintenance-list" onRowDoubleClicked={(e) => manage && e.data && setEditing(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">Nothing in this period. Schedules (Configuration → Maintenance Schedules) add due jobs here.</span>' />
      </Paper>
      <JobEditor job={editing} onClose={() => setEditing(null)} onCost={(j) => { setEditing(null); setCostFor(j); }} />
      <CostEditor cost={costFor ? 'new' : null} job={costFor} onClose={() => setCostFor(null)} />
    </Stack>
  );
}

// ── Cost items ──
function Costs() {
  const manage = useCan()('maintenance.manage');
  const refresh = useMaintenanceRefresh();
  const [params] = useSearchParams();
  const { data: catalog } = useMaintenanceCatalog();
  const { data: categories = [] } = useCategories();
  const [range, setRange] = useState<Range | null>(null);
  const [vehicleGroup, setVehicleGroup] = useState<string | null>(params.get('vehicle_group'));
  const [vehicleType, setVehicleType] = useState<string | null>(null);
  const typeParam = params.get('vehicle_type');
  const vehicleTypeId = vehicleType ?? catalog?.vehicle_type.find((t) => t.name === typeParam)?.id ?? null;
  const [typeId, setTypeId] = useState<string | null>(null);
  const [itemId, setItemId] = useState<string | null>(null);
  const [centre, setCentre] = useState<string | null>(null);
  const { data: rows = [], isFetching } = useCosts({ range, vehicle_group: vehicleGroup, vehicle_type_id: vehicleTypeId, type_id: typeId, item_id: itemId, cost_centre_id: centre });
  const [editing, setEditing] = useState<CostRow | 'new' | null>(null);
  const total = useMemo(() => rows.reduce((a, r) => a + r.amount, 0), [rows]);
  const remove = (c: CostRow) => modals.openConfirmModal({
    title: 'Delete this cost item?', children: <Text size="sm">{c.vehicle}: {c.description ?? c.item ?? ''} {money(c.amount)}</Text>,
    labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: () => { mntApi.remove('costs', c.id).then(refresh).catch(fail); },
  });
  const cols: ColDef<CostRow>[] = [
    { headerName: 'Vehicle', field: 'vehicle', minWidth: 150, flex: 1 },
    { headerName: 'Vehicle Type', field: 'vehicle_type', width: 140, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Date', field: 'cost_date', width: 125, sort: 'desc', valueFormatter: (p) => day(p.value) },
    { headerName: 'Maintenance', field: 'maintenance', minWidth: 150, flex: 1, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Maintenance Item', field: 'item', minWidth: 150, flex: 1, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Description', field: 'description', minWidth: 150, flex: 1, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Cost', field: 'amount', width: 120, type: 'numericColumn', valueFormatter: (p) => money(p.value) },
    { headerName: 'Cost Centre', field: 'cost_centre', width: 150, valueFormatter: (p) => p.value || '—' },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<CostRow>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <ActionIcon size="sm" variant="subtle" onClick={() => setEditing(p.data!)} aria-label="Edit cost item"><IconPencil size={15} /></ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" onClick={() => remove(p.data!)} aria-label="Delete cost item"><IconTrash size={15} /></ActionIcon>
        </Group>) }] : []),
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <Header title="Cost Item" description="Maintenance costs per vehicle — on a job or on their own — charged to cost centres.">
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>Add cost item</Button>}
      </Header>
      <Paper withBorder p="sm" mb="sm">
        <Group gap="xs" wrap="wrap">
          {range ? <RangePicker value={range} onChange={setRange} /> : <Button size="sm" variant="default" onClick={() => setRange(defaultRange())}>All dates</Button>}
          {range && <Button size="sm" variant="subtle" onClick={() => setRange(null)}>All dates</Button>}
          <Select size="sm" w={170} placeholder="Vehicle group" clearable data={categories.map((c) => c.name)} value={vehicleGroup} onChange={setVehicleGroup} />
          <Select size="sm" w={160} placeholder="Vehicle type" clearable data={(catalog?.vehicle_type ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={vehicleTypeId} onChange={setVehicleType} />
          <Select size="sm" w={180} placeholder="Maintenance type" clearable searchable data={(catalog?.types ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={typeId} onChange={setTypeId} />
          <Select size="sm" w={180} placeholder="Maintenance item" clearable searchable data={(catalog?.items ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={itemId} onChange={setItemId} />
          <Select size="sm" w={160} placeholder="Cost centre" clearable data={(catalog?.cost_centre ?? []).map((t) => ({ value: t.id, label: t.name }))}
                  value={centre} onChange={setCentre} />
          <Text size="sm" ml="auto"><Text span c="dimmed">{rows.length} items · total </Text><b>{money(total)}</b></Text>
        </Group>
      </Paper>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} stateKey="maintenance-costs"
                  onRowDoubleClicked={(e) => manage && e.data && setEditing(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No cost items yet.</span>' />
      </Paper>
      <CostEditor cost={editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}

// ── DTC ──
function Dtc() {
  const { data: catalog } = useMaintenanceCatalog();
  const { data: categories = [] } = useCategories();
  const [group, setGroup] = useState<string>('__all');
  const [imei, setImei] = useState<string | null>(null);
  const [range, setRange] = useState<Range>(() => ({ from: dayjs().subtract(6, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }));
  const { data: codes = [], isFetching } = useDtc(imei, range);
  const vehicles = (catalog?.vehicles ?? []).filter((v) => group === '__all' || v.group === group);
  const groups = [{ value: '__all', label: 'All vehicles' }, ...categories.map((c) => ({ value: c.name, label: c.name }))];
  const pane = (title: string, items: { value: string; label: string }[], value: string | null, onPick: (v: string) => void) => (
    <Paper withBorder radius="md" style={{ overflow: 'hidden' }}>
      <Text fw={600} px="sm" py={8} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>{title}</Text>
      <ScrollArea h="calc(100dvh - 300px)" type="auto">
        {items.map((i) => (
          <UnstyledButton key={i.value} onClick={() => onPick(i.value)} px="sm" py={6} w="100%"
                          style={{ background: i.value === value ? 'var(--mantine-color-default-hover)' : undefined, fontWeight: i.value === value ? 600 : undefined }}>
            <Text size="sm" truncate>{i.label}</Text>
          </UnstyledButton>
        ))}
        {!items.length && <Text size="sm" c="dimmed" p="sm">None</Text>}
      </ScrollArea>
    </Paper>
  );
  return (
    <Stack p="lg" gap="sm">
      <Header title="DTC" description="Diagnostic trouble codes (engine fault codes) the vehicles’ devices read from the OBD port." />
      <SimpleGrid cols={{ base: 1, md: 4 }} spacing="sm">
        {pane('Vehicle Groups', groups, group, (g) => { setGroup(g); setImei(null); })}
        {pane('Vehicles', vehicles.map((v) => ({ value: v.imei, label: v.name })), imei, setImei)}
        <Paper withBorder radius="md" p="sm" style={{ gridColumn: 'span 2' }}>
          <Group justify="space-between" mb="sm">
            <Text fw={600}>{imei ? catalog?.vehicles.find((v) => v.imei === imei)?.name : 'Choose a vehicle'}</Text>
            <RangePicker value={range} onChange={setRange} />
          </Group>
          <ScrollArea.Autosize mah="calc(100dvh - 340px)" type="auto">
            <Table striped fz="sm" stickyHeader>
              <Table.Thead><Table.Tr><Table.Th>Error Code</Table.Th><Table.Th>Description</Table.Th><Table.Th>Category</Table.Th><Table.Th>Event Timestamp</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {codes.map((c, i) => (
                  <Table.Tr key={`${c.code}-${c.recorded_at}-${i}`}><Table.Td fw={600}>{c.code}</Table.Td><Table.Td>{c.description}</Table.Td>
                    <Table.Td>{c.category}</Table.Td><Table.Td>{dateTime(c.recorded_at)}</Table.Td></Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {imei && !codes.length && (
              <Text size="sm" c="dimmed" mt="sm">{isFetching ? 'Loading…'
                : 'No fault codes in this period. Codes come from the vehicle’s OBD port (Teltonika “Fault codes”, IO 281); a device without an OBD connection doesn’t send them.'}</Text>
            )}
          </ScrollArea.Autosize>
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}

/** Main menu → Vehicle Maintenance: a hub of Overview, Summary by Vehicle, Maintenance List, Cost Item and DTC. */
export function MaintenanceSection() {
  return (
    <Routes>
      <Route index element={<Hub />} />
      <Route path="overview" element={<Overview />} />
      <Route path="summary" element={<Summary />} />
      <Route path="list" element={<MaintenanceList />} />
      <Route path="costs" element={<Costs />} />
      <Route path="dtc" element={<Dtc />} />
      <Route path="*" element={<Navigate to={ROOT} replace />} />
    </Routes>
  );
}
