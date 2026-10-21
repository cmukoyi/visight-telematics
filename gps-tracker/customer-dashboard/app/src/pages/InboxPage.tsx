import { useMemo, useState } from 'react';
import { ActionIcon, Badge, Button, Group, Paper, SegmentedControl, Select, Text, TextInput, Title, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconChecks, IconMail, IconMailOpened, IconSearch, IconTable, IconMap } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useInbox, useVehicles, type Range } from '../api/hooks';
import type { Alert } from '../api/types';
import { DataGrid } from '../components/DataGrid';
import { FleetMap, type MapPoint } from '../components/FleetMap';
import { RangePicker, defaultRange } from '../components/RangePicker';
import { dateTime, vehicleName } from '../utils/format';
import classes from './InboxPage.module.css';

const TYPE_LABELS: Record<string, string> = {
  tag_offline: 'Device offline', battery_low: 'Low battery', geofence_enter: 'Place entered', geofence_exit: 'Place exited',
  overspeed: 'Speeding', harsh_braking: 'Harsh braking', harsh_acceleration: 'Harsh acceleration', crash: 'Crash',
  towing: 'Towing', power_cut: 'Power cut', panic: 'Panic', package_expiry: 'Package expiry',
};
const typeLabel = (t: string) => TYPE_LABELS[t] ?? t.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const SEVERE = new Set(['crash', 'panic', 'towing', 'power_cut']);

const num = (v: unknown) => (typeof v === 'number' ? v : typeof v === 'string' && v !== '' ? Number(v) : NaN);

export function InboxPage() {
  const qc = useQueryClient();
  const [range, setRange] = useState<Range>(defaultRange);
  const [status, setStatus] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [imei, setImei] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<'grid' | 'map'>('grid');
  const { data: vehicles = [] } = useVehicles();
  const inbox = useInbox({ range, status, type, imei, search });
  const alerts = inbox.data ?? [];

  const refresh = () => { qc.invalidateQueries({ queryKey: ['inbox'] }); qc.invalidateQueries({ queryKey: ['unread'] }); };
  const markRead = async (a: Alert) => {
    try { await api(`/api/portal/alerts/${a.id}/read`, { method: 'PUT' }); refresh(); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  const markAll = async () => {
    try { await api('/api/portal/alerts/read-all', { method: 'PUT' }); refresh(); notifications.show({ message: 'All alerts marked as read' }); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };

  const types = useMemo(() => [...new Set(alerts.map((a) => a.alert_type).concat(type ? [type] : []))].sort(), [alerts, type]);
  const unread = alerts.filter((a) => !a.is_read).length;

  const cols: ColDef<Alert>[] = [
    { headerName: '', width: 54, minWidth: 54, sortable: false, filter: false,
      cellRenderer: (p: ICellRendererParams<Alert>) => p.data && (
        <Tooltip label={p.data.is_read ? 'Read' : 'Mark as read'} withinPortal>
          <ActionIcon size="sm" variant="subtle" color={p.data.is_read ? 'gray' : 'brand'} disabled={p.data.is_read}
                      onClick={() => markRead(p.data!)} aria-label="Mark as read">
            {p.data.is_read ? <IconMailOpened size={15} /> : <IconMail size={15} />}
          </ActionIcon>
        </Tooltip>) },
    { headerName: 'Time', field: 'created_at', valueFormatter: (p) => dateTime(p.value), sort: 'desc', width: 170 },
    { headerName: 'Type', field: 'alert_type', valueFormatter: (p) => typeLabel(p.value), width: 170,
      cellRenderer: (p: ICellRendererParams<Alert>) => p.data && (
        <Badge size="sm" variant="light" color={SEVERE.has(p.data.alert_type) ? 'red' : 'blue'}>{typeLabel(p.data.alert_type)}</Badge>) },
    { headerName: 'Vehicle', valueGetter: (p) => p.data?.tag_label ?? p.data?.tag_imei ?? '—', width: 180 },
    { headerName: 'Title', field: 'title', flex: 1, cellClass: (p) => (p.data?.is_read ? '' : classes.unread) },
    { headerName: 'Message', field: 'message', flex: 2, tooltipField: 'message' },
  ];

  const points: MapPoint[] = alerts.flatMap((a) => {
    const lat = num(a.meta_data?.latitude), lng = num(a.meta_data?.longitude);
    return Number.isNaN(lat) || Number.isNaN(lng) ? [] : [{
      id: a.id, lat, lng, color: SEVERE.has(a.alert_type) ? '#dc2626' : a.is_read ? '#64748b' : '#3e7cfb',
      label: a.title, detail: `${dateTime(a.created_at)}\n${a.message}`,
    }];
  });

  return (
    <div className={classes.root}>
      <Group justify="space-between" mb="md" wrap="wrap">
        <Group gap="sm">
          <Title order={2}>Inbox</Title>
          {unread > 0 && <Badge color="red" variant="filled">{unread} unread</Badge>}
        </Group>
        <Group gap="xs">
          <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'grid' | 'map')} data={[
            { value: 'grid', label: <Group gap={4} wrap="nowrap"><IconTable size={14} />Grid</Group> },
            { value: 'map', label: <Group gap={4} wrap="nowrap"><IconMap size={14} />Map</Group> },
          ]} />
          <Button size="xs" variant="light" leftSection={<IconChecks size={16} />} onClick={markAll} disabled={!unread}>Mark all read</Button>
        </Group>
      </Group>

      <Paper p="sm" mb="sm" withBorder>
        <Group gap="xs" wrap="wrap">
          <RangePicker value={range} onChange={setRange} />
          <Select size="sm" w={140} placeholder="Any status" clearable value={status} onChange={setStatus} aria-label="Status"
                  data={[{ value: 'unread', label: 'Unread' }, { value: 'read', label: 'Read' }]} />
          <Select size="sm" w={190} placeholder="All alert types" clearable value={type} onChange={setType} aria-label="Alert type"
                  data={types.map((t) => ({ value: t, label: typeLabel(t) }))} />
          <Select size="sm" w={210} placeholder="All vehicles" clearable searchable value={imei} onChange={setImei} aria-label="Vehicle"
                  data={vehicles.map((v) => ({ value: v.imei, label: vehicleName(v) }))} />
          <TextInput size="sm" w={220} placeholder="Search title or message" leftSection={<IconSearch size={14} />}
                     value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <Text size="sm" c="dimmed" ml="auto">{alerts.length} alerts</Text>
        </Group>
      </Paper>

      <Paper className={classes.body} withBorder>
        {view === 'grid'
          ? <DataGrid rowData={alerts} columnDefs={cols} loading={inbox.isFetching} getRowId={(p) => p.data.id} tooltipShowDelay={400} />
          : <FleetMap points={points} />}
      </Paper>
    </div>
  );
}
