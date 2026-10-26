import { useEffect, useRef, useState } from 'react';
import {
  Badge, Box, Button, Drawer, Group, Paper, Select, SimpleGrid, Stack, Text, Textarea, ThemeIcon, Timeline, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle, IconCheck, IconCircleCheck, IconInfoCircle, IconMapPin, IconPlayerPlay, IconQuestionMark, IconX } from '@tabler/icons-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { useCan, type Range } from '../../api/hooks';
import { reviewBreakdown, useBreakdown, useBreakdowns, type Breakdown } from '../../api/breakdowns';
import { useMaintenanceCatalog, useMaintenanceRefresh } from '../../api/maintenance';
import { ConfigHeader } from '../../components/ConfigHeader';
import { DataGrid } from '../../components/DataGrid';
import { FleetMap, type FleetMapHandle, type MapPoint, type MapRoute } from '../../components/FleetMap';
import { RangePicker, defaultRange } from '../../components/RangePicker';
import { dateTime, duration, time } from '../../utils/format';
import classes from '../CatalogPages.module.css';

const VERDICT = {
  consistent: { label: 'Consistent', color: 'green', icon: IconCircleCheck, hint: 'The tracker agrees: the vehicle stayed put with the ignition off.' },
  check: { label: 'Check', color: 'orange', icon: IconAlertTriangle, hint: 'The tracker shows something that doesn’t fit a breakdown.' },
  unconfirmed: { label: 'Unconfirmed', color: 'gray', icon: IconQuestionMark, hint: 'The tracker sent nothing during the breakdown.' },
} as const;

function Verdict({ b }: { b: Breakdown }) {
  const v = VERDICT[b.evidence.verdict];
  const warns = b.evidence.flags.filter((f) => f.level === 'warn').length;
  return (
    <Tooltip label={b.evidence.flags.map((f) => f.text).join(' · ') || v.hint} multiline w={280} withinPortal>
      <Badge size="sm" variant="light" color={v.color} leftSection={<v.icon size={12} aria-hidden />}>
        {v.label}{warns > 1 ? ` · ${warns}` : ''}
      </Badge>
    </Tooltip>
  );
}

const REVIEW = { accepted: ['Accepted', 'green'], disputed: ['Disputed', 'red'] } as const;

/** Vehicle Maintenance → Breakdowns: what drivers logged in the mobile app, checked against the tracker. */
export function Breakdowns() {
  const [range, setRange] = useState<Range>(defaultRange);
  const [imei, setImei] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { data: catalog } = useMaintenanceCatalog();
  const { data: rows = [], isFetching } = useBreakdowns(range, imei);
  const active = rows.filter((r) => r.status === 'active').length;
  const toCheck = rows.filter((r) => r.evidence.verdict === 'check' && !r.review).length;
  const total = rows.reduce((s, r) => s + r.downtime_s, 0);
  const cols: ColDef<Breakdown>[] = [
    { headerName: 'Vehicle', field: 'vehicle', minWidth: 150, pinned: 'left' },
    { headerName: 'Logged by', field: 'reported_by', width: 160, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Driver', field: 'driver', width: 150, hide: true, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Cause', field: 'cause', width: 120, valueFormatter: (p) => p.value || '—' },
    { headerName: 'Started', field: 'started_at', width: 165, sort: 'desc', valueFormatter: (p) => dateTime(p.value) },
    { headerName: 'Ended', field: 'ended_at', width: 165,
      cellRenderer: (p: ICellRendererParams<Breakdown>) => p.data && (p.data.ended_at ? dateTime(p.data.ended_at)
        : <Badge size="sm" color="red" variant="light" leftSection={<IconPlayerPlay size={11} aria-hidden />}>In progress</Badge>) },
    { headerName: 'Downtime', field: 'downtime_s', width: 115, type: 'rightAligned', valueFormatter: (p) => duration(p.value) },
    { headerName: 'Location', field: 'location', flex: 1, minWidth: 200, tooltipField: 'location',
      valueFormatter: (p) => p.value || (p.data?.latitude != null ? `${p.data.latitude.toFixed(5)}, ${p.data.longitude!.toFixed(5)}` : '—') },
    { headerName: 'Tracker check', colId: 'verdict', width: 150, valueGetter: (p) => p.data && VERDICT[p.data.evidence.verdict].label,
      cellRenderer: (p: ICellRendererParams<Breakdown>) => p.data && <Verdict b={p.data} /> },
    { headerName: 'Review', field: 'review', width: 120,
      cellRenderer: (p: ICellRendererParams<Breakdown>) => p.data && (p.data.review
        ? <Badge size="sm" variant="light" color={REVIEW[p.data.review][1]}>{REVIEW[p.data.review][0]}</Badge>
        : <Text size="sm" c="dimmed">Not reviewed</Text>) },
  ];
  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader root="/maintenance" rootLabel="Vehicle Maintenance" title="Breakdowns"
                    description="Breakdowns drivers log in the mobile app, checked against each vehicle’s tracker: did it move, was the ignition on, was the driver with it? Each one is also a “Breakdown” job in the Maintenance List." />
      <Paper withBorder p="sm" mb="sm">
        <Group gap="xs" wrap="wrap">
          <RangePicker value={range} onChange={setRange} />
          <Select size="sm" w={200} placeholder="All vehicles" clearable searchable value={imei} onChange={setImei}
                  data={(catalog?.vehicles ?? []).map((v) => ({ value: v.imei, label: v.name }))} />
          <Group gap="lg" ml="auto">
            <Text size="sm"><b>{rows.length}</b> <Text span c="dimmed">breakdowns</Text></Text>
            <Text size="sm"><b>{duration(total)}</b> <Text span c="dimmed">downtime</Text></Text>
            {active > 0 && <Text size="sm" c="red"><b>{active}</b> in progress</Text>}
            {toCheck > 0 && <Text size="sm" c="orange"><b>{toCheck}</b> to check</Text>}
          </Group>
        </Group>
      </Paper>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} tooltipShowDelay={300}
                  stateKey="maintenance-breakdowns" onRowClicked={(e) => e.data && setOpen(e.data.id)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No breakdowns in this period. Drivers log them in the mobile app: Assets → vehicle → Log breakdown.</span>' />
      </Paper>
      <BreakdownDrawer id={open} onClose={() => setOpen(null)} />
    </Stack>
  );
}

function Fact({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text fw={600} c={warn ? 'orange' : undefined}>{value}</Text>
    </div>
  );
}

function BreakdownDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: b } = useBreakdown(id);
  const canReview = useCan()('maintenance.manage');
  const refresh = useMaintenanceRefresh();
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => { setNote(b?.review_note ?? ''); }, [b?.id, b?.review_note]);
  const ev = b?.evidence;
  const points: MapPoint[] = !b ? [] : [
    ...(b.latitude != null && b.longitude != null ? [{ id: 'phone', lat: b.latitude, lng: b.longitude, color: '#2563eb', label: 'Phone when logged',
      detail: `${b.reported_by ?? ''}\n${dateTime(b.started_at)}${b.accuracy ? `\n±${Math.round(b.accuracy)} m` : ''}` }] : []),
    ...(ev?.vehicle_position ? [{ id: 'vehicle', lat: ev.vehicle_position[0], lng: ev.vehicle_position[1], color: '#f59e0b',
      label: 'Vehicle when logged', detail: 'Its tracker’s last position before the breakdown' }] : []),
    ...(b.end_latitude != null && b.end_longitude != null ? [{ id: 'end', lat: b.end_latitude, lng: b.end_longitude, color: '#16a34a',
      label: 'Phone when resolved', detail: b.ended_at ? dateTime(b.ended_at) : '' }] : []),
  ];
  const routes: MapRoute[] = ev?.track && ev.track.length > 1 ? [{ id: 'track', color: '#dc2626', coords: ev.track, arrows: true }] : [];
  // Show the phone, the vehicle and its track together
  const mapRef = useRef<FleetMapHandle>(null);
  useEffect(() => {
    const all: [number, number][] = [...points.map((p) => [p.lat, p.lng] as [number, number]), ...(ev?.track ?? [])];
    if (all.length) setTimeout(() => mapRef.current?.fit(all), 150);
  }, [b?.id, points.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async (review: Breakdown['review']) => {
    if (!b) return;
    setSaving(true);
    try { await reviewBreakdown(b.id, review, note); refresh(); notifications.show({ color: 'green', message: review ? `Breakdown ${review}` : 'Review cleared' }); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
    finally { setSaving(false); }
  };
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={560} title={b ? `${b.vehicle} · breakdown` : 'Breakdown'}>
      {b && ev && (
        <Stack gap="md">
          <Box h={260} style={{ borderRadius: 'var(--mantine-radius-md)', overflow: 'hidden' }}>
            <FleetMap key={b.id} ref={mapRef} points={points} routes={routes} />
          </Box>
          <Group gap="lg" justify="space-between">
            <Fact label="Downtime" value={`${duration(b.downtime_s)}${b.ended_at ? '' : ' (still running)'}`} />
            <Fact label="Cause" value={b.cause ?? '—'} />
            <Fact label="Logged by" value={b.reported_by ?? '—'} />
            <Fact label="Assigned driver" value={b.driver ?? '—'} />
          </Group>
          <Paper withBorder p="sm" radius="md">
            <Group gap="xs" mb={6}><Verdict b={b} /><Text size="sm" c="dimmed">{VERDICT[ev.verdict].hint}</Text></Group>
            {ev.flags.map((f) => (
              <Group key={f.text} gap={6} wrap="nowrap" mt={4}>
                <ThemeIcon size="sm" variant="light" color={f.level === 'warn' ? 'orange' : 'gray'}>
                  {f.level === 'warn' ? <IconAlertTriangle size={13} /> : <IconInfoCircle size={13} />}
                </ThemeIcon>
                <Text size="sm">{f.text}</Text>
              </Group>
            ))}
            <SimpleGrid cols={3} mt="sm" spacing="xs">
              <Fact label="Moved" value={ev.moved_km == null ? 'No data' : `${ev.moved_km.toFixed(1)} km`} warn={(ev.moved_km ?? 0) >= 1} />
              <Fact label="Ignition on" value={duration(ev.ignition_on_s)} warn={ev.ignition_on_s >= 900} />
              <Fact label="Trips" value={ev.trips ? `${ev.trips} (${ev.trip_km} km)` : 'None'} warn={ev.trips > 0} />
              <Fact label="Phone to vehicle" value={ev.phone_gap_m == null ? '—' : ev.phone_gap_m < 1000 ? `${ev.phone_gap_m} m` : `${(ev.phone_gap_m / 1000).toFixed(1)} km`}
                    warn={(ev.phone_gap_m ?? 0) >= 500} />
              <Fact label="Top speed" value={`${ev.max_speed} km/h`} />
              <Fact label="Tracker reports" value={`${ev.reports}${ev.last_report ? ` · last ${time(ev.last_report)}` : ''}`} />
            </SimpleGrid>
          </Paper>
          <div>
            <Text fw={600} mb="xs">Timeline</Text>
            <Timeline bulletSize={22} lineWidth={2} active={b.phases.length + (b.ended_at ? 1 : 0)}>
              <Timeline.Item bullet={<IconMapPin size={12} />} title="Breakdown started">
                <Text size="sm" c="dimmed">{dateTime(b.started_at)}</Text>
                {b.location && <Text size="sm">{b.location}</Text>}
              </Timeline.Item>
              {b.phases.map((p) => (
                <Timeline.Item key={p.at} title={p.phase}><Text size="sm" c="dimmed">{dateTime(p.at)}</Text></Timeline.Item>
              ))}
              <Timeline.Item bullet={b.ended_at ? <IconCheck size={12} /> : undefined} title={b.ended_at ? 'Resolved' : 'Not resolved yet'}>
                {b.ended_at && <Text size="sm" c="dimmed">{dateTime(b.ended_at)}</Text>}
                {b.notes && <Text size="sm">“{b.notes}”</Text>}
              </Timeline.Item>
            </Timeline>
          </div>
          {canReview ? (
            <Paper withBorder p="sm" radius="md">
              <Text fw={600} mb={4}>Review</Text>
              {b.review && <Text size="sm" c="dimmed" mb={6}>{REVIEW[b.review][0]} by {b.reviewed_by}</Text>}
              <Textarea placeholder="Note, e.g. what the driver said" autosize minRows={2} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
              <Group mt="sm" gap="xs">
                <Button size="xs" color="green" variant={b.review === 'accepted' ? 'filled' : 'light'} leftSection={<IconCheck size={14} />}
                        loading={saving} onClick={() => save('accepted')}>Accept</Button>
                <Button size="xs" color="red" variant={b.review === 'disputed' ? 'filled' : 'light'} leftSection={<IconX size={14} />}
                        loading={saving} onClick={() => save('disputed')}>Dispute</Button>
                {b.review && <Button size="xs" variant="subtle" color="gray" onClick={() => save(null)}>Clear review</Button>}
              </Group>
            </Paper>
          ) : b.review && <Text size="sm">{REVIEW[b.review][0]} by {b.reviewed_by}{b.review_note ? `: ${b.review_note}` : ''}</Text>}
        </Stack>
      )}
    </Drawer>
  );
}
