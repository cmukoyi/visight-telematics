import { useEffect, useState } from 'react';
import { Badge, Button, CloseButton, Group, Paper, SimpleGrid, Stack, Switch, Text } from '@mantine/core';
import { IconBroadcast, IconGauge, IconKey, IconRoute } from '@tabler/icons-react';
import type { LivePosition, Vehicle } from '../api/types';
import { detail } from '../api/types';
import { duration, time, vehicleName } from '../utils/format';
import classes from './LiveTrack.module.css';

function secondsAgo(iso: string | null | undefined, now: number) {
  if (!iso) return null;
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
}
const agoText = (s: number | null) => (s == null ? '—' : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`);

/** The live-tracking card for one vehicle (data from useLive, refreshed every 5 s). */
export function LiveTrack({ vehicle, live, follow, onFollow, onClose, onShowTrip }: {
  vehicle: Vehicle; live: LivePosition | undefined; follow: boolean; onFollow: (v: boolean) => void;
  onClose: () => void; onShowTrip?: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const pos = live?.position;
  const age = secondsAgo(pos?.recorded_at, now);
  const moving = !!pos && pos.speed > 3;
  const fresh = age != null && age < 180;
  const state = !pos ? { label: 'No position yet', color: 'gray' }
    : !fresh ? { label: 'Not reporting', color: 'gray' }
    : moving ? { label: `Moving · ${pos.speed} km/h`, color: 'green' }
    : pos.ignition ? { label: 'Stopped, ignition on', color: 'yellow' } : { label: 'Parked', color: 'blue' };
  const reg = detail(vehicle, 'registration');
  const driver = detail(vehicle, 'driver');

  return (
    <Paper className={classes.card} shadow="xl" withBorder>
      <Group justify="space-between" wrap="nowrap" mb={6}>
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <span className={`${classes.pulse} ${fresh ? classes.on : ''}`} />
          <div style={{ minWidth: 0 }}>
            <Text fw={700} truncate>{vehicleName(vehicle)}</Text>
            <Text size="xs" c="dimmed" truncate>{[reg, driver].filter(Boolean).join(' · ') || vehicle.imei}</Text>
          </div>
        </Group>
        <CloseButton onClick={onClose} aria-label="Stop live tracking" />
      </Group>
      <Badge color={state.color} variant="light" size="lg" fullWidth mb="sm" leftSection={<IconBroadcast size={14} />}>{state.label}</Badge>
      <SimpleGrid cols={3} spacing={6} mb="sm">
        <Stack gap={0} className={classes.stat}><Text size="xs" c="dimmed"><IconGauge size={12} /> Speed</Text><Text fw={700}>{pos ? `${pos.speed}` : '—'}<Text span size="xs" c="dimmed"> km/h</Text></Text></Stack>
        <Stack gap={0} className={classes.stat}><Text size="xs" c="dimmed"><IconKey size={12} /> Ignition</Text><Text fw={700}>{pos?.ignition == null ? '—' : pos.ignition ? 'On' : 'Off'}</Text></Stack>
        <Stack gap={0} className={classes.stat}><Text size="xs" c="dimmed">Last report</Text><Text fw={700}>{agoText(age)}</Text></Stack>
      </SimpleGrid>
      {live?.trip ? (
        <Paper withBorder radius="md" p="xs" mb="sm">
          <Group justify="space-between" wrap="nowrap">
            <Group gap={6} wrap="nowrap"><IconRoute size={16} /><Text size="sm" fw={600}>On a trip since {time(live.trip.started_at)}</Text></Group>
            {onShowTrip && <Button size="compact-xs" variant="subtle" onClick={onShowTrip}>Details</Button>}
          </Group>
          <Text size="xs" c="dimmed" mt={2}>{live.trip.distance_km} km · {duration(live.trip.duration_s)} · max {live.trip.max_speed} km/h</Text>
        </Paper>
      ) : (
        <Text size="xs" c="dimmed" mb="sm">Not on a trip — the line shows the last hour.</Text>
      )}
      <Group justify="space-between">
        <Switch size="sm" label="Follow on map" checked={follow} onChange={(e) => onFollow(e.currentTarget.checked)} />
        <Text size="xs" c="dimmed">{pos?.event ?? ''}</Text>
      </Group>
    </Paper>
  );
}
