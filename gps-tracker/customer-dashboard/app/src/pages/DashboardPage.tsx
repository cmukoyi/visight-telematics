import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Card, Group, Select, SimpleGrid, Skeleton, Stack, Text, Title } from '@mantine/core';
import { IconRoute, IconClock, IconRoad, IconTrendingUp, IconTrendingDown, IconCar } from '@tabler/icons-react';
import { useCategories, useKpis, useVehicles } from '../api/hooks';
import { FleetMap, type FleetMapHandle, type MapVehicle } from '../components/FleetMap';
import { ALL_VEHICLES, inGroup, toMapVehicle } from './vehicles';
import classes from './DashboardPage.module.css';

function Kpi({ period, title, value, unit, group, icon: Icon, delta }: {
  period: string; title: string; value: string | number; unit?: string; group: string;
  icon: typeof IconRoute; delta?: number | null;
}) {
  return (
    <Card className={classes.kpi}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} lts={0.4}>{period}</Text>
          <Text fw={600} mt={2}>{title}</Text>
        </div>
        <Icon size={22} stroke={1.5} className={classes.kpiIcon} />
      </Group>
      <Group gap={6} align="baseline" mt="md">
        <Text className={classes.kpiValue}>{value}</Text>
        {unit && <Text c="dimmed" fw={500}>{unit}</Text>}
      </Group>
      <Group justify="space-between" mt={6}>
        <Text size="xs" c="dimmed">{group}</Text>
        {delta != null && Number.isFinite(delta) && (
          <Badge size="sm" variant="light" color={delta >= 0 ? 'teal' : 'orange'}
                 leftSection={delta >= 0 ? <IconTrendingUp size={12} /> : <IconTrendingDown size={12} />}>
            {delta >= 0 ? '+' : ''}{Math.round(delta)}% vs last week
          </Badge>
        )}
      </Group>
    </Card>
  );
}

export function DashboardPage() {
  const [group, setGroup] = useState<string>(ALL_VEHICLES);
  const { data: vehicles, isLoading } = useVehicles();
  const { data: categories } = useCategories();
  const { data: kpis } = useKpis(group === ALL_VEHICLES ? null : group);
  const mapRef = useRef<FleetMapHandle>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const inScope = useMemo(() => (vehicles ?? []).filter((v) => inGroup(v, group)), [vehicles, group]);
  const markers = useMemo(() => inScope.map(toMapVehicle).filter(Boolean) as MapVehicle[], [inScope]);
  const counts = useMemo(() => ({
    active: inScope.filter((v) => v.activity_status === 'active').length,
    idle: inScope.filter((v) => v.activity_status === 'idle').length,
    offline: inScope.filter((v) => v.activity_status === 'offline').length,
  }), [inScope]);

  useEffect(() => {
    if (markers.length) mapRef.current?.fit(markers.map((m) => [m.lat, m.lng]));
  }, [markers.length, group]);  // eslint-disable-line react-hooks/exhaustive-deps

  const groupLabel = group === ALL_VEHICLES ? 'All vehicles' : group;
  const cur = kpis?.current_week;
  const prev = kpis?.previous_week;
  const pct = (a?: number, b?: number) => (a != null && b ? ((a - b) / b) * 100 : null);

  return (
    <Stack p="lg" gap="lg">
      <Group justify="space-between" wrap="wrap">
        <div>
          <Title order={3}>Where is my fleet</Title>
          <Text c="dimmed" size="sm">{inScope.length} vehicles · updated every 30 seconds</Text>
        </div>
        <Group gap="sm">
          <Badge size="lg" variant="dot" color="green">{counts.active} active</Badge>
          <Badge size="lg" variant="dot" color="yellow">{counts.idle} idle</Badge>
          <Badge size="lg" variant="dot" color="gray">{counts.offline} offline</Badge>
          <Select
            aria-label="Vehicle group"
            leftSection={<IconCar size={16} />}
            value={group}
            onChange={(v) => setGroup(v ?? ALL_VEHICLES)}
            data={[{ value: ALL_VEHICLES, label: 'All Vehicles' },
                   ...(categories ?? []).filter((c) => c.is_active).map((c) => ({ value: c.name, label: c.name }))]}
            allowDeselect={false}
            w={220}
          />
        </Group>
      </Group>

      <Card p={0} className={classes.mapCard}>
        {isLoading ? <Skeleton h="100%" /> : (
          <FleetMap ref={mapRef} vehicles={markers} selectedVehicleId={selected}
                    onVehicleClick={(id) => setSelected(id === selected ? null : id)} />
        )}
      </Card>

      <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }} spacing="lg">
        <Kpi period="Current week" title="Average journey length" value={cur?.avg_trip_km ?? '—'} unit="km" group={groupLabel}
             icon={IconRoute} delta={pct(cur?.avg_trip_km, prev?.avg_trip_km)} />
        <Kpi period="Current week" title="Distance driven" value={cur?.distance_km.toLocaleString() ?? '—'} unit="km" group={groupLabel}
             icon={IconRoad} delta={pct(cur?.distance_km, prev?.distance_km)} />
        <Kpi period="Current week" title="Driving time" value={cur?.driving_hours ?? '—'} unit="h" group={groupLabel}
             icon={IconClock} delta={pct(cur?.driving_hours, prev?.driving_hours)} />
        <Kpi period="Previous week" title="Average journey length" value={prev?.avg_trip_km ?? '—'} unit="km" group={groupLabel} icon={IconRoute} />
        <Kpi period="Previous week" title="Distance driven" value={prev?.distance_km.toLocaleString() ?? '—'} unit="km" group={groupLabel} icon={IconRoad} />
        <Kpi period="Previous week" title="Trips" value={prev?.trips ?? '—'} group={groupLabel} icon={IconCar} />
      </SimpleGrid>
    </Stack>
  );
}
