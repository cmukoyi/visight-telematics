import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ActionIcon, Badge, CloseButton, CopyButton, Divider, Group, Loader, Paper, ScrollArea, SegmentedControl, SimpleGrid,
  Stack, Tabs, Text, Tooltip, UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconBattery2, IconBolt, IconBroadcast, IconCalendar, IconCheck, IconChevronLeft, IconChevronRight, IconClock,
  IconCopy, IconCpu, IconEye, IconEyeOff, IconGauge, IconKey, IconMapPin, IconPencil, IconReportAnalytics, IconRoad,
  IconRoute, IconSatellite, IconShare, IconDeviceSim, IconAntennaBars5, IconWalk,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import { useCan, useTrips, useVehicleStatus } from '../api/hooks';
import { detail, type Trip, type Vehicle } from '../api/types';
import { ago, dateTime, duration, km, time, vehicleName } from '../utils/format';
import classes from './VehiclePanel.module.css';

type Tab = 'details' | 'trips';
type Period = 'today' | 'yesterday' | 'week';

const PERIODS: Record<Period, () => { from: Date; to: Date }> = {
  today: () => ({ from: dayjs().startOf('day').toDate(), to: dayjs().endOf('day').toDate() }),
  yesterday: () => ({ from: dayjs().subtract(1, 'day').startOf('day').toDate(), to: dayjs().subtract(1, 'day').endOf('day').toDate() }),
  week: () => ({ from: dayjs().subtract(6, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }),
};

function Field({ icon: Icon, label, value }: { icon: typeof IconKey; label: string; value: React.ReactNode }) {
  return (
    <div className={classes.field}>
      <Group gap={6} wrap="nowrap"><Icon size={14} className={classes.fieldIcon} /><Text size="xs" c="dimmed" truncate>{label}</Text></Group>
      <Text fw={600} size="sm" mt={2} truncate>{value ?? '—'}</Text>
    </div>
  );
}

function Action({ icon: Icon, label, onClick, active }: { icon: typeof IconKey; label: string; onClick: () => void; active?: boolean }) {
  return (
    <UnstyledButton className={classes.action} onClick={onClick} aria-label={label}>
      <span className={`${classes.actionIcon} ${active ? classes.actionActive : ''}`}><Icon size={18} /></span>
      <Text size="11px" ta="center" lh={1.2}>{label}</Text>
    </UnstyledButton>
  );
}

interface Props {
  vehicle: Vehicle;
  plotted: boolean;
  onTogglePlot: () => void;
  plottedTrips: Set<string>;
  onToggleTrip: (trip: Trip) => void;
  onClose: () => void;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

/** The right-hand vehicle panel in Workspace: Vehicle details and Trips tabs; collapses to a strip. */
export function VehiclePanel({ vehicle, plotted, onTogglePlot, plottedTrips, onToggleTrip, onClose, collapsed, onCollapse }: Props) {
  const navigate = useNavigate();
  const can = useCan();
  const [tab, setTab] = useState<Tab>('details');
  const [period, setPeriod] = useState<Period>('today');
  const range = useMemo(() => PERIODS[period](), [period]);
  const status = useVehicleStatus(vehicle.imei);
  const trips = useTrips(range, vehicle.imei, can('history.view') && tab === 'trips' && !collapsed);
  const st = status.data;
  const reading = (name: string) => st?.readings.find((r) => r.name === name)?.display;
  const pos = st?.position;
  const mapsLink = pos ? `https://www.google.com/maps?q=${pos.latitude},${pos.longitude}` : null;
  const makeModel = [detail(vehicle, 'make'), detail(vehicle, 'model'), detail(vehicle, 'year')].filter(Boolean).join(' ');

  const open = (t: Tab) => { setTab(t); onCollapse(false); };
  if (collapsed) {
    return (
      <Paper className={`${classes.panel} ${classes.collapsed}`} shadow="xl">
        <Tooltip label="Expand" position="left"><ActionIcon variant="subtle" color="gray" onClick={() => onCollapse(false)} aria-label="Expand panel">
          <IconChevronLeft size={18} /></ActionIcon></Tooltip>
        <UnstyledButton className={classes.vtab} onClick={() => open('details')}>Vehicle details</UnstyledButton>
        {can('history.view') && <UnstyledButton className={classes.vtab} onClick={() => open('trips')}>Trips</UnstyledButton>}
      </Paper>
    );
  }

  const share = async () => {
    if (!mapsLink) return;
    try {
      await navigator.clipboard.writeText(mapsLink);
      notifications.show({ color: 'green', message: 'Location link copied — paste it to share' });
    } catch {
      window.open(mapsLink, '_blank', 'noopener');
    }
  };

  return (
    <Paper className={classes.panel} shadow="xl">
      <Group justify="space-between" wrap="nowrap" className={classes.head}>
        <Tooltip label="Collapse"><ActionIcon variant="subtle" color="gray" onClick={() => onCollapse(true)} aria-label="Collapse panel">
          <IconChevronRight size={18} /></ActionIcon></Tooltip>
        <CloseButton onClick={onClose} aria-label="Close panel" />
      </Group>
      <Group gap={8} wrap="nowrap" px="md" mb="sm">
        <span className={classes.dot} data-status={vehicle.activity_status} />
        <div style={{ minWidth: 0 }}>
          <Text fw={700} size="lg" truncate>{vehicleName(vehicle)}</Text>
          <Text size="xs" c="dimmed" truncate>{[detail(vehicle, 'registration'), vehicle.category_name].filter(Boolean).join(' · ') || vehicle.imei}</Text>
        </div>
      </Group>

      <Tabs value={tab} onChange={(v) => setTab((v as Tab) ?? 'details')} className={classes.tabs}>
        <Tabs.List grow px="md">
          <Tabs.Tab value="details">Vehicle details</Tabs.Tab>
          {can('history.view') && <Tabs.Tab value="trips">Trips</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="details" className={classes.tabPanel}>
          <ScrollArea h="100%" type="auto">
            <SimpleGrid cols={5} spacing={4} px="xs" py="sm">
              <Action icon={plotted ? IconEyeOff : IconEye} label={plotted ? 'Unplot' : 'Toggle plot'} onClick={onTogglePlot} active={plotted} />
              <Action icon={IconShare} label="Share location" onClick={share} />
              {can('map.view') && <Action icon={IconBroadcast} label="Live track" onClick={() => navigate(`/dashboard?vehicle=${encodeURIComponent(vehicle.imei)}`)} />}
              {can('vehicles.manage') && <Action icon={IconPencil} label="Edit vehicle" onClick={() => navigate(`/configuration/devices?edit=${vehicle.id}`)} />}
              {can('reports.view') && <Action icon={IconReportAnalytics} label="View report" onClick={() => navigate('/reports?run=trips')} />}
            </SimpleGrid>
            <Divider />
            {status.isLoading ? <Group justify="center" p="xl"><Loader size="sm" /></Group> : (
              <Stack gap={0}>
                <div className={classes.section}>
                  <Text fw={650} mb={6}>Vehicle details</Text>
                  <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
                    <Field icon={IconCpu} label="IMEI" value={vehicle.imei} />
                    <Field icon={IconCpu} label="Unit type" value={vehicle.device_model} />
                    <Field icon={IconRoad} label="Make / model" value={makeModel || 'Unknown'} />
                    <Field icon={IconKey} label="Registration" value={detail(vehicle, 'registration') || '—'} />
                    <Field icon={IconWalk} label="Driver" value={detail(vehicle, 'driver') || '—'} />
                    <Field icon={IconRoute} label="Vehicle group" value={vehicle.category_name || '—'} />
                  </SimpleGrid>
                </div>
                <div className={classes.section}>
                  <Group gap={6} mb={4}><IconMapPin size={15} /><Text fw={650}>Last known position</Text></Group>
                  {pos ? (
                    <>
                      <Text size="sm">{pos.address || 'Address not available'}</Text>
                      <Group gap={4} mt={2}>
                        <Text size="xs" c="dimmed" ff="monospace">{pos.latitude.toFixed(5)}, {pos.longitude.toFixed(5)}</Text>
                        <CopyButton value={`${pos.latitude.toFixed(5)}, ${pos.longitude.toFixed(5)}`}>
                          {({ copied, copy }) => (
                            <ActionIcon size="xs" variant="subtle" color={copied ? 'green' : 'gray'} onClick={copy} aria-label="Copy coordinates">
                              {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}
                            </ActionIcon>)}
                        </CopyButton>
                      </Group>
                      <Text size="xs" c="dimmed" mt={2}>{dateTime(pos.recorded_at)} · {ago(pos.recorded_at)}</Text>
                    </>
                  ) : <Text size="sm" c="dimmed">No position reported yet.</Text>}
                </div>
                <div className={classes.section}>
                  <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
                    <Field icon={IconKey} label="Ignition" value={reading('Ignition')} />
                    <Field icon={IconGauge} label="Speed" value={pos ? `${pos.speed} km/h` : undefined} />
                    <Field icon={IconRoad} label="Odometer" value={reading('Total odometer')} />
                    <Field icon={IconWalk} label="Movement" value={reading('Movement')} />
                    <Field icon={IconBolt} label="Vehicle voltage" value={reading('External voltage')} />
                    <Field icon={IconBattery2} label="Unit battery" value={reading('Battery voltage')} />
                    <Field icon={IconAntennaBars5} label="GSM signal" value={reading('GSM signal')} />
                    <Field icon={IconSatellite} label="Satellites" value={pos?.satellites ?? reading('GNSS status')} />
                    <Field icon={IconClock} label="Last report" value={st?.last_report ? ago(st.last_report) : undefined} />
                    <Field icon={IconBroadcast} label="Last event" value={st?.last_event} />
                  </SimpleGrid>
                </div>
                <div className={classes.section}>
                  <Group gap={6} mb={6}><IconDeviceSim size={15} /><Text fw={650}>SIM card</Text></Group>
                  <SimpleGrid cols={2} spacing="xs">
                    <Field icon={IconDeviceSim} label="ICCID" value={st?.iccid} />
                    <Field icon={IconAntennaBars5} label="Operator" value={reading('Active GSM operator')} />
                  </SimpleGrid>
                </div>
                <div className={classes.section}>
                  <Text fw={650} mb={6}>Today's statistics</Text>
                  <SimpleGrid cols={3} spacing="xs">
                    <Field icon={IconRoute} label="Trips" value={st?.today.trips} />
                    <Field icon={IconRoad} label="Distance" value={st ? `${st.today.distance_km} km` : undefined} />
                    <Field icon={IconClock} label="Driving" value={st ? duration(st.today.driving_s) : undefined} />
                  </SimpleGrid>
                </div>
              </Stack>
            )}
          </ScrollArea>
        </Tabs.Panel>

        <Tabs.Panel value="trips" className={classes.tabPanel}>
          <Stack gap={0} h="100%">
            <div className={classes.section}>
              <SegmentedControl fullWidth size="xs" value={period} onChange={(v) => setPeriod(v as Period)}
                                data={[{ value: 'today', label: 'Today' }, { value: 'yesterday', label: 'Yesterday' }, { value: 'week', label: '7 days' }]} />
            </div>
            <ScrollArea style={{ flex: 1 }} type="auto">
              {trips.isLoading && <Group justify="center" p="xl"><Loader size="sm" /></Group>}
              {!trips.isLoading && (trips.data ?? []).length === 0 && (
                <Stack align="center" gap={4} p="xl"><IconCalendar size={28} opacity={0.4} /><Text size="sm" c="dimmed">No trips in this period.</Text></Stack>
              )}
              {(trips.data ?? []).map((t) => {
                const on = plottedTrips.has(t.id);
                return (
                  <UnstyledButton key={t.id} className={`${classes.trip} ${on ? classes.tripOn : ''}`} onClick={() => onToggleTrip(t)}>
                    <Group justify="space-between" wrap="nowrap" mb={4}>
                      <Text size="sm" fw={650}>{period === 'week' ? dayjs(t.started_at).format('ddd DD MMM, ') : ''}{time(t.started_at)} – {t.status === 'open' ? 'now' : time(t.ended_at)}</Text>
                      <Group gap={4} wrap="nowrap">
                        <Badge size="sm" variant="light">{km(t.distance_m)}</Badge>
                        <Badge size="sm" variant="default">{duration(t.duration_s)}</Badge>
                        {on ? <IconEye size={15} /> : <IconEyeOff size={15} opacity={0.5} />}
                      </Group>
                    </Group>
                    <Text size="xs" truncate><span className={classes.from}>●</span> {t.start_address ?? 'Looking up address…'}</Text>
                    <Text size="xs" truncate><span className={classes.to}>●</span> {t.status === 'open' ? 'In progress' : t.end_address ?? 'Looking up address…'}</Text>
                    {t.speeding_count + t.harsh_braking_count + t.harsh_acceleration_count + t.harsh_cornering_count > 0 && (
                      <Group gap={4} mt={4}>
                        {t.speeding_count > 0 && <Badge size="xs" color="orange" variant="light">{t.speeding_count} speeding</Badge>}
                        {t.harsh_braking_count + t.harsh_acceleration_count + t.harsh_cornering_count > 0 &&
                          <Badge size="xs" color="red" variant="light">{t.harsh_braking_count + t.harsh_acceleration_count + t.harsh_cornering_count} harsh</Badge>}
                      </Group>
                    )}
                  </UnstyledButton>
                );
              })}
            </ScrollArea>
            <Text size="xs" c="dimmed" p="sm" ta="center">Click a trip to show or hide it on the map.</Text>
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Paper>
  );
}
