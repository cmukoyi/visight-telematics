import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Badge, Button, CloseButton, Group, Loader, Paper, ScrollArea, SegmentedControl, Select, Stack, Text, Textarea,
  TextInput, Title, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconChecks, IconMail, IconMailOpened, IconSearch, IconTable, IconMap } from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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
  tag_offline: 'Device offline', battery_low: 'Low battery', geofence_entry: 'Place entered', geofence_enter: 'Place entered', geofence_exit: 'Place exited',
  overspeed: 'Speeding', harsh_braking: 'Harsh braking', harsh_acceleration: 'Harsh acceleration', crash: 'Crash',
  towing: 'Towing', power_cut: 'Power cut', panic: 'Panic', package_expiry: 'Package expiry',
  maintenance_due: 'Maintenance due', maintenance_overdue: 'Maintenance overdue',
  licence_expiring: 'Licence expiring', licence_expired: 'Licence expired', breakdown: 'Breakdown',
};
const typeLabel = (t: string) => TYPE_LABELS[t] ?? t.replace(/^event_/, '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
/** The server's summary line ("Jeep Compass (DH68DMZN) left Home at 32 km/h after 2h 05m there"),
 *  else the title with its speed. */
function summary(a: Alert) {
  if (a.summary) return a.summary;
  const vehicle = a.tag_label ?? '';
  let s = a.title ?? '';
  if (vehicle && s.toLowerCase().startsWith(vehicle.toLowerCase())) s = s.slice(vehicle.length).replace(/^[\s:·,-]+/, '');
  s = s ? s[0].toUpperCase() + s.slice(1) : typeLabel(a.alert_type);
  const speed = num(a.meta_data?.speed);
  return !Number.isNaN(speed) && speed > 0 && !/km\/h/.test(s) ? `${s} at ${Math.round(speed)} km/h` : s;
}
const SEVERE = new Set(['breakdown', 'crash', 'panic', 'towing', 'power_cut', 'maintenance_overdue', 'licence_expired']);

const num = (v: unknown) => (typeof v === 'number' ? v : typeof v === 'string' && v !== '' ? Number(v) : NaN);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed" mb={2}>{label}</Text>
      <div className={classes.value}>{children}</div>
    </div>
  );
}

/** The selected alert, on the right of the grid: what happened, notes, and Mark as read. */
function AlertDetails({ alert, onClose, onSaved }: { alert: Alert; onClose: () => void; onSaved: () => void }) {
  const navigate = useNavigate();
  const { data: full } = useQuery({
    queryKey: ['inbox-alert', alert.id],
    queryFn: () => api<Alert>(`/api/portal/inbox/${alert.id}`),
  });
  const a = { ...alert, ...full };
  const m = a.meta_data ?? {};
  const [notes, setNotes] = useState(alert.notes ?? '');
  const [saving, setSaving] = useState(false);
  useEffect(() => setNotes(alert.notes ?? ''), [alert.id, alert.notes]);

  const rules = Array.isArray(m.rules) ? (m.rules as string[]) : [];
  const lat = num(m.latitude), lng = num(m.longitude);
  const coords = Number.isNaN(lat) || Number.isNaN(lng) ? null : `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  const place = typeof m.poi_name === 'string' ? m.poi_name : null;
  const location = [place, full ? a.address : null].filter(Boolean).join(' — ') || (full ? coords : null);
  const speed = m.speed == null || m.speed === '' ? null : `${m.speed} km/h`;

  const save = async () => {
    setSaving(true);
    try {
      await api(`/api/portal/alerts/${a.id}/read`, { method: 'PUT', json: { notes } });
      notifications.show({ message: a.is_read ? 'Notes saved' : 'Alert marked as read' });
      onSaved();
      if (!a.is_read) onClose();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Paper className={classes.details} withBorder>
      <Group justify="space-between" wrap="nowrap" p="md" pb="sm" className={classes.detailsHead}>
        <Text fw={650} size="lg">Alert details</Text>
        <CloseButton onClick={onClose} aria-label="Close alert details" />
      </Group>
      <ScrollArea className={classes.detailsBody} type="auto">
        <Stack gap="sm" p="md">
          <Group gap="xs">
            <Badge variant="light" color={SEVERE.has(a.alert_type) ? 'red' : 'blue'}>{typeLabel(a.alert_type)}</Badge>
            <Badge variant="dot" color={a.is_read ? 'gray' : 'red'}>{a.is_read ? 'Read' : 'Unread'}</Badge>
          </Group>
          <Text fw={600}>{a.summary ?? a.title}</Text>
          {a.message && <Text size="sm" c="dimmed">{a.message}</Text>}
          <Field label="Timestamp">{dateTime(typeof m.recorded_at === 'string' ? m.recorded_at : a.created_at)}</Field>
          {rules.length > 0 && <Field label={rules.length > 1 ? 'Notification rules' : 'Notification rule'}>{rules.join(', ')}</Field>}
          <Field label="Vehicle">{[a.tag_label, a.tag_imei && a.tag_imei !== a.tag_label ? a.tag_imei : null].filter(Boolean).join(' · ') || '—'}</Field>
          {(coords || place) && <Field label="Location">{location ?? <Loader size="xs" />}</Field>}
          {speed && <Field label="Speed">{speed}</Field>}
          {a.is_read && a.read_by && (
            <Text size="xs" c="dimmed">Processed by {a.read_by}{a.read_at ? ` on ${dateTime(a.read_at)}` : ''}</Text>
          )}
          {rules.length > 0 && (
            <Group justify="flex-end">
              <Button size="xs" variant="default" onClick={() => navigate('/configuration/misc/notification-rules')}>Manage notification rule</Button>
            </Group>
          )}
        </Stack>
      </ScrollArea>
      <Stack gap="xs" p="md" className={classes.detailsFoot}>
        <Textarea placeholder="Add notes…" autosize minRows={3} maxRows={6} value={notes}
                  onChange={(e) => setNotes(e.currentTarget.value)} aria-label="Notes" />
        <Group grow gap="xs">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button loading={saving} onClick={save} leftSection={a.is_read ? undefined : <IconMailOpened size={16} />}
                  disabled={a.is_read && notes === (a.notes ?? '')}>
            {a.is_read ? 'Save notes' : 'Mark as read'}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function InboxPage() {
  const qc = useQueryClient();
  const [range, setRange] = useState<Range>(defaultRange);
  const [status, setStatus] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [imei, setImei] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get('search') ?? '');
  useEffect(() => {
    const q = params.get('search');
    if (q) setSearch(q);
    const st = params.get('status');
    if (st === 'unread' || st === 'read') setStatus(st);
  }, [params]);
  const [view, setView] = useState<'grid' | 'map'>('grid');
  const { data: vehicles = [] } = useVehicles();
  const inbox = useInbox({ range, status, type, imei, search });
  const alerts = inbox.data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = alerts.find((a) => a.id === selectedId) ?? null;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['inbox'] });
    qc.invalidateQueries({ queryKey: ['inbox-alert'] });
    qc.invalidateQueries({ queryKey: ['unread'] });
  };
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
    { colId: 'read', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<Alert>) => p.data && (
        <Tooltip label={p.data.is_read ? 'Read' : 'Mark as read'} withinPortal>
          <ActionIcon size="sm" variant="subtle" color={p.data.is_read ? 'gray' : 'brand'} disabled={p.data.is_read}
                      onClick={() => markRead(p.data!)}
                      aria-label={p.data.is_read ? `Read: ${p.data.title}` : `Mark as read: ${p.data.title}, ${dateTime(p.data.created_at)}`}>
            {p.data.is_read ? <IconMailOpened size={15} /> : <IconMail size={15} />}
          </ActionIcon>
        </Tooltip>) },
    { headerName: 'Time', field: 'created_at', valueFormatter: (p) => dateTime(p.value), sort: 'desc', width: 170 },
    { headerName: 'Type', field: 'alert_type', valueFormatter: (p) => typeLabel(p.value), width: 170,
      cellRenderer: (p: ICellRendererParams<Alert>) => p.data && (
        <Badge size="sm" variant="light" color={SEVERE.has(p.data.alert_type) ? 'red' : 'blue'}>{typeLabel(p.data.alert_type)}</Badge>) },
    { headerName: 'Vehicle', valueGetter: (p) => p.data?.tag_label ?? p.data?.tag_imei ?? '—', width: 180 },
    { headerName: 'Summary', colId: 'summary', valueGetter: (p) => (p.data ? summary(p.data) : ''), flex: 1, minWidth: 220,
      tooltipValueGetter: (p) => (p.data ? summary(p.data) : ''), cellClass: (p) => (p.data?.is_read ? '' : classes.unread) },
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
          <Title order={1} size="h2">Inbox</Title>
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

      <div className={classes.split}>
        <Paper className={classes.body} withBorder>
          {view === 'grid'
            ? <DataGrid rowData={alerts} columnDefs={cols} loading={inbox.isFetching} getRowId={(p) => p.data.id} tooltipShowDelay={400}
                        stateKey="inbox" onRowClicked={(e) => e.data && setSelectedId(e.data.id)}
                        rowClassRules={{ [classes.selectedRow]: (p) => p.data?.id === selectedId }} />
            : <FleetMap points={points} />}
        </Paper>
        {selected && <AlertDetails key={selected.id} alert={selected} onClose={() => setSelectedId(null)} onSaved={refresh} />}
      </div>
    </div>
  );
}
