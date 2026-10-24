import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ActionIcon, Anchor, Badge, Card, Group, Select, SimpleGrid, Skeleton, Stack, Text, Title, Tooltip, UnstyledButton } from '@mantine/core';
import { IconRoute, IconClock, IconRoad, IconTrendingUp, IconTrendingDown, IconCar, IconPlayerPause, IconPlayerPlay, IconFocus2 } from '@tabler/icons-react';
import { useCan, useCategories, useKpis, useLive, useVehicles } from '../api/hooks';
import { FleetMap, type FleetMapHandle, type MapRoute, type MapVehicle } from '../components/FleetMap';
import { LiveTrack } from '../components/LiveTrack';
import { ALL_VEHICLES, inGroup, toMapVehicle } from './vehicles';
import { useT } from '../i18n';
import { plural } from '../utils/format';
import { Sparkline } from '../components/Sparkline';
import type { Kpis } from '../api/types';
import dayjs from 'dayjs';
import classes from './DashboardPage.module.css';

type Measure = 'distance_km' | 'driving_hours' | 'trips' | 'avg_trip_km';

/** This week's figure, the change from last week, and a sparkline of the last 8 weeks. */
function Kpi({ title, measure, unit, group, icon: Icon, kpis }: {
  title: string; measure: Measure; unit?: string; group: string; icon: typeof IconRoute; kpis?: Kpis;
}) {
  const t = useT();
  const navigate = useNavigate();
  const weeks = kpis?.weeks ?? [];
  const cur = kpis?.current_week[measure], prev = kpis?.previous_week[measure];
  const fmt = (v: number) => `${v.toLocaleString()}${unit ? ` ${unit}` : ''}`;
  const delta = weekChange(cur, prev);
  const labels = weeks.map((w, i) => (i === weeks.length - 1 ? 'This week' : `Week of ${dayjs(w.week_start).format('D MMM')}`));
  return (
    <Card className={classes.kpi}>
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
        <Text fw={600} truncate>{title}</Text>
        <Anchor size="xs" component="button" onClick={() => navigate('/workspace')} className={classes.kpiLink}
                aria-label={`View trips: ${title}`}>
          <Group gap={4} wrap="nowrap"><Icon size={16} stroke={1.6} aria-hidden />{t('app.dashboard.view_trips', 'View trips')} →</Group>
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed" truncate>{t('app.dashboard.this_week', 'This week')} · {group}</Text>
      <Group gap="md" align="flex-end" mt="md" wrap="nowrap">
        <Group gap={6} align="baseline" wrap="nowrap">
          <Text className={classes.kpiValue}>{cur == null ? '—' : cur.toLocaleString()}</Text>
          {unit && <Text c="dimmed" fw={500}>{unit}</Text>}
        </Group>
        <div className={classes.spark}>
          <Sparkline values={weeks.map((w) => w[measure])} labels={labels} format={fmt}
                     summary={`${title}, last 8 weeks: ${weeks.map((w) => fmt(w[measure])).join(', ')}`} />
        </div>
      </Group>
      <Group mt="sm" gap={6} wrap="nowrap" miw={0}>
          {delta === 'new' ? (
            <Badge size="sm" variant="light" color="gray" style={{ flex: 'none' }} leftSection={<IconTrendingUp size={12} />}>{t('app.dashboard.new_activity', 'New activity')}</Badge>
          ) : delta != null && (
            <Badge size="sm" variant="light" color="gray" style={{ flex: 'none' }} leftSection={delta >= 0 ? <IconTrendingUp size={12} /> : <IconTrendingDown size={12} />}>
              {delta > 999 ? '> 999%' : `${delta >= 0 ? '+' : ''}${Math.round(delta)}%`}
            </Badge>
          )}
          {prev != null && <Text size="xs" c="dimmed" truncate>{t('app.dashboard.vs_prev', 'vs {value} last week', { value: fmt(prev) })}</Text>}
      </Group>
    </Card>
  );
}

/** Week-on-week change in %; from (almost) nothing it's "new activity", not +132600% */
function weekChange(a?: number, b?: number): number | 'new' | null {
  if (a == null || b == null) return null;
  if (b <= Math.abs(a) * 0.05) return a > 0 ? 'new' : null;
  return ((a - b) / b) * 100;
}

// Keeps a followed vehicle clear of the live-tracking card (top left, 320 px wide)
const FOLLOW_PADDING = { top: 60, bottom: 60, left: 350, right: 60 };

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [group, setGroup] = useState<string>(params.get('group') ?? ALL_VEHICLES);
  // Live refresh can be paused (WCAG 2.2.2); "Updated 12 s ago" shows how fresh the positions are
  const [paused, setPaused] = useState(false);
  const { data: vehicles, isLoading, dataUpdatedAt } = useVehicles(!paused);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  // A status chip filters the map to that status (click again for all)
  const [status, setStatus] = useState<'active' | 'idle' | 'offline' | null>(null);
  const { data: categories } = useCategories();
  const { data: kpis } = useKpis(group === ALL_VEHICLES ? null : group);
  const mapRef = useRef<FleetMapHandle>(null);
  // Live tracking: the selected vehicle (also from ?vehicle=<imei>, e.g. from search)
  const [selected, setSelected] = useState<string | null>(params.get('vehicle'));
  const [follow, setFollow] = useState(true);
  const [showTrail, setShowTrail] = useState(true);
  const canTrack = useCan()('live.track');
  const { data: live } = useLive(canTrack ? selected : null);
  const tracked = vehicles?.find((v) => v.imei === selected) ?? null;
  useEffect(() => {
    const v = params.get('vehicle');
    const g = params.get('group');
    if (v) { setSelected(v); setFollow(true); }
    if (g) setGroup(g);
    if (v || g) setParams({}, { replace: true });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  const select = (imei: string | null) => { setSelected(imei); setFollow(!!imei); };

  const inScope = useMemo(() => (vehicles ?? []).filter((v) => inGroup(v, group)), [vehicles, group]);
  const markers = useMemo(() => {
    const out = inScope.filter((v) => !status || v.activity_status === status || v.imei === selected)
      .map(toMapVehicle).filter(Boolean) as MapVehicle[];
    const pos = live?.position;
    // The tracked vehicle uses its live (5-second) position
    return pos ? out.map((m) => (m.id === selected ? { ...m, lat: pos.latitude, lng: pos.longitude, status: 'active' as const } : m)) : out;
  }, [inScope, live, selected, status]);
  const trail: MapRoute[] = showTrail && live && live.trail.length > 1
    ? [{ id: 'live-trail', color: '#22c55e', coords: live.trail, arrows: true }] : [];
  // Follow: re-centre on every new position (and straight away when switched on)
  const pos = live?.position;
  useEffect(() => {
    if (follow && pos) mapRef.current?.panTo(pos.latitude, pos.longitude);
  }, [pos?.latitude, pos?.longitude, follow, selected]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => ({
    active: inScope.filter((v) => v.activity_status === 'active').length,
    idle: inScope.filter((v) => v.activity_status === 'idle').length,
    offline: inScope.filter((v) => v.activity_status === 'offline').length,
  }), [inScope]);

  useEffect(() => {
    if (markers.length && !selected) mapRef.current?.fit(markers.map((m) => [m.lat, m.lng]));
  }, [markers.length, group, status]);  // eslint-disable-line react-hooks/exhaustive-deps

  const t = useT();
  const groupLabel = group === ALL_VEHICLES ? t('app.common.all_vehicles', 'All vehicles') : group;

  return (
    <Stack p="lg" gap="lg">
      <Group justify="space-between" wrap="wrap">
        <div>
          <Title order={1} size="h3">{t('app.dashboard.title', 'Where is my fleet')}</Title>
          <Group gap={6} wrap="wrap" style={{ rowGap: 0 }}>
            <Text c="dimmed" size="sm">{t('app.dashboard.subtitle_short', '{vehicles} · click a vehicle to track it live', { count: inScope.length, vehicles: plural(inScope.length, 'vehicle') })}</Text>
            <Text c="dimmed" size="sm" aria-hidden>·</Text>
            <Text c={paused ? 'orange' : 'dimmed'} size="sm">
              {paused ? t('app.dashboard.paused', 'Live updates paused')
                : dataUpdatedAt ? t('app.dashboard.updated_ago', 'Updated {s} s ago', { s: Math.max(0, Math.round((now - dataUpdatedAt) / 1000)) }) : ''}
            </Text>
            <Tooltip label={paused ? t('app.dashboard.resume', 'Resume live updates') : t('app.dashboard.pause', 'Pause live updates')}>
              <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => setPaused(!paused)}
                          aria-label={paused ? 'Resume live updates' : 'Pause live updates'}>
                {paused ? <IconPlayerPlay size={14} /> : <IconPlayerPause size={14} />}
              </ActionIcon>
            </Tooltip>
          </Group>
        </div>
        <Group gap="sm">
          {([['active', 'green', t('app.status.n_active', '{count} active', { count: counts.active })],
             ['idle', 'yellow', t('app.status.n_idle', '{count} idle', { count: counts.idle })],
             ['offline', 'gray', t('app.status.n_offline', '{count} offline', { count: counts.offline })]] as const).map(([key, color, label]) => (
            <UnstyledButton key={key} aria-pressed={status === key} onClick={() => setStatus(status === key ? null : key)}
                            title={status === key ? 'Show all vehicles' : `Show only ${key} vehicles`} className={classes.chip}>
              <Badge size="lg" variant={status === key ? 'filled' : 'dot'} color={color} style={{ cursor: 'pointer' }}>{label}</Badge>
            </UnstyledButton>
          ))}
          <Tooltip label="Show all vehicles on the map">
            <ActionIcon variant="default" size="lg" aria-label="Fit all vehicles on the map"
                        onClick={() => { select(null); markers.length && mapRef.current?.fit(markers.map((m) => [m.lat, m.lng])); }}>
              <IconFocus2 size={18} />
            </ActionIcon>
          </Tooltip>
          <Select
            aria-label="Vehicle group"
            leftSection={<IconCar size={16} />}
            value={group}
            onChange={(v) => setGroup(v ?? ALL_VEHICLES)}
            data={[{ value: ALL_VEHICLES, label: t('app.common.all_vehicles', 'All vehicles') },
                   ...(categories ?? []).filter((c) => c.is_active).map((c) => ({ value: c.name, label: c.name }))]}
            allowDeselect={false}
            w={220}
          />
        </Group>
      </Group>

      <Card p={0} className={classes.mapCard}>
        {isLoading ? <Skeleton h="100%" /> : (
          <FleetMap ref={mapRef} vehicles={markers} selectedVehicleId={selected} routes={trail}
                    fitPadding={tracked && window.innerWidth >= 720 ? FOLLOW_PADDING : undefined}
                    onVehicleClick={(id) => select(id === selected ? null : id)} />
        )}
        {tracked && canTrack && (
          <LiveTrack vehicle={tracked} live={live} follow={follow} onFollow={setFollow} trail={showTrail} onTrail={setShowTrail}
                     onClose={() => select(null)}
                     onShowTrip={() => navigate('/workspace')} />
        )}
      </Card>

      <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing="lg">
        <Kpi title={t('app.dashboard.distance', 'Distance driven')} measure="distance_km" unit="km" group={groupLabel} icon={IconRoad} kpis={kpis} />
        <Kpi title={t('app.dashboard.driving_time', 'Driving time')} measure="driving_hours" unit="h" group={groupLabel} icon={IconClock} kpis={kpis} />
        <Kpi title={t('app.dashboard.trips', 'Trips')} measure="trips" group={groupLabel} icon={IconCar} kpis={kpis} />
        <Kpi title={t('app.dashboard.avg_trip', 'Average trip')} measure="avg_trip_km" unit="km" group={groupLabel} icon={IconRoute} kpis={kpis} />
      </SimpleGrid>
    </Stack>
  );
}
