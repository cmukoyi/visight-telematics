import { useEffect, useState } from 'react';
import { Link, Navigate, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Code, ColorInput, Group, Modal, Paper, PasswordInput, PinInput, Radio, Select,
  SimpleGrid, Stack, Text, TextInput, ThemeIcon, Title, Tooltip, UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconAlertTriangle, IconArrowUpRight, IconBan, IconBolt, IconCar, IconKey, IconUsers, IconMapPin, IconPencil, IconPlugConnected,
  IconSearch, IconTrash, IconPlus, IconShieldLock, IconDots, IconBellRinging, IconChevronRight,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useCategories, useDataExchange, useMe, useSecurityGroups, useVehicles } from '../api/hooks';
import { VEHICLE_DETAILS, detail, type Category, type Vehicle } from '../api/types';
import { getSession } from '../auth/session';
import { ConfigHeader } from '../components/ConfigHeader';
import { DataGrid } from '../components/DataGrid';
import { EditorShell, firstError } from '../components/EditorShell';
import { EventTypeGroupsPage, EventTypesPage, GeofencesPage, PlaceGroupsPage } from './CatalogPages';
import { STATUS } from '../theme';
import { ago, dateTime, vehicleName } from '../utils/format';
import classes from './ConfigurationPage.module.css';
import { NotificationRulesPage } from './NotificationRulesPage';
import { PlacesPage } from './PlacesPage';
import { SecurityPage, UsersPage } from './SecurityPage';
import { MyNotificationPrefs, UserGroupPage } from './UserGroupPage';

// Configuration sections, each a tile with its sub-menu. `any`: shown when the role has one of these permissions.
interface MenuItem { label: string; to?: string; classic?: string; any: string[] }
interface Section { title: string; icon: typeof IconCar; items: MenuItem[] }

const SECTIONS: Section[] = [
  { title: 'Vehicles', icon: IconCar, items: [
    { label: 'Vehicles', to: 'devices', any: [] },
    { label: 'Vehicle Groups', to: 'groups', any: ['vehicle_groups.manage'] },
    { label: 'Data Exchange', to: 'exchange', any: ['data_exchange.manage'] },
  ] },
  { title: 'Users', icon: IconUsers, items: [
    { label: 'Users', to: 'users', any: ['users.view', 'users.manage'] },
    { label: 'User Groups', to: 'user-groups', any: [] },
    { label: 'Custom Themes', to: 'custom-themes', any: ['theme.manage'] },
  ] },
  { title: 'Places', icon: IconMapPin, items: [
    { label: 'Places', to: 'places', any: ['places.view', 'places.manage'] },
    { label: 'Place Groups', to: 'place-groups', any: ['places.view', 'places.manage'] },
    { label: 'Geofences', to: 'geofences', any: ['places.view', 'places.manage'] },
  ] },
  { title: 'Events', icon: IconBolt, items: [
    { label: 'Event Types', to: 'event-types', any: [] },
    { label: 'Event Type Groups', to: 'event-type-groups', any: ['events.manage', 'rules.manage'] },
  ] },
  { title: 'Security', icon: IconShieldLock, items: [
    { label: 'Security Groups', to: 'security?tab=groups', any: ['security.manage', 'users.manage'] },
    { label: 'Roles', to: 'security?tab=roles', any: ['roles.manage', 'users.manage'] },
    { label: 'Audit Trail', to: 'security?tab=audit', any: ['audit.view'] },
  ] },
  { title: 'Misc', icon: IconDots, items: [
    { label: 'Notification Rules', to: 'misc/notification-rules', any: ['inbox.view', 'rules.manage'] },
  ] },
];

const classicUrl = (tab: string) => `/customer/classic/#tab=${tab}`;

function Header({ title }: { title: string }) {
  return (
    <Stack gap={4} mb="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
        <Text size="sm">{title}</Text>
      </Breadcrumbs>
      <Title order={2}>{title}</Title>
    </Stack>
  );
}

function Tiles() {
  const navigate = useNavigate();
  const can = useCan();
  const allowed = (i: MenuItem) => i.any.length === 0 || i.any.some(can);
  const sections = SECTIONS.map((sec) => ({ ...sec, items: sec.items.filter(allowed) })).filter((sec) => sec.items.length);
  return (
    <Stack p="lg" gap="lg">
      <Title order={2}>Configuration</Title>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3, xl: 4 }} spacing="md">
        {sections.map((sec) => (
          <Paper key={sec.title} className={classes.tile}>
            <Group gap="md" wrap="nowrap" mb="md">
              <sec.icon size={34} stroke={1.3} className={classes.tileIcon} />
              <Text className={classes.tileTitle}>{sec.title}</Text>
            </Group>
            <Stack gap={2} className={classes.links}>
              {sec.items.map((i) => (
                <UnstyledButton key={i.label} className={classes.link}
                                onClick={() => (i.to ? navigate(i.to) : window.open(classicUrl(i.classic!), '_self'))}>
                  {i.label}
                  {i.classic && <IconArrowUpRight size={13} className={classes.ext} />}
                </UnstyledButton>
              ))}
            </Stack>
          </Paper>
        ))}
      </SimpleGrid>
    </Stack>
  );
}

// ── Vehicles & devices ──
function Devices() {
  const qc = useQueryClient();
  const { data: vehicles = [], isFetching } = useVehicles();
  const { data: categories = [] } = useCategories();
  const [editing, setEditing] = useState<Vehicle | null>(null);
  const form = useForm({ initialValues: { description: '', category: '', registration: '', make: '', model: '', year: '', driver: '' } });
  const can = useCan();
  const admin = can('vehicles.manage');
  const canDelete = can('vehicles.delete');

  const open = (v: Vehicle) => {
    form.setValues({ description: v.description ?? '', category: v.category_name ?? '',
                     ...Object.fromEntries(VEHICLE_DETAILS.map((k) => [k, detail(v, k)])) });
    setEditing(v);
  };
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    const v = vehicles.find((x) => x.id === params.get('edit'));
    if (v && admin) { open(v); setParams({}, { replace: true }); }
  }, [vehicles, params]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = form.onSubmit(async (values) => {
    try {
      await api(`/api/portal/tags/${editing!.id}`, { method: 'PUT', json: values });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      setEditing(null);
      notifications.show({ color: 'green', message: 'Vehicle saved' });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  });

  // Delete asks the user to type a short code, so a vehicle and its history aren't removed by a stray click
  const [deleting, setDeleting] = useState<{ vehicle: Vehicle; code: string } | null>(null);
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const startDelete = (v: Vehicle) => { setTyped(''); setDeleting({ vehicle: v, code: String(Math.floor(1000 + Math.random() * 9000)) }); };
  const doDelete = async () => {
    if (!deleting || typed !== deleting.code) return;
    try {
      await api(`/api/portal/tags/${deleting.vehicle.id}`, { method: 'DELETE' });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      notifications.show({ color: 'green', message: `${vehicleName(deleting.vehicle)} deleted` });
      setDeleting(null);
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  const shown = vehicles.filter((v) => !search || [v.imei, vehicleName(v), detail(v, 'registration'), detail(v, 'driver'), v.category_name]
    .join(' ').toLowerCase().includes(search.toLowerCase()));

  const cols: ColDef<Vehicle>[] = [
    { colId: 'state', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<Vehicle>) => p.data &&
        <span className={classes.stateDot} style={{ background: STATUS[p.data.activity_status] }} title={p.data.activity_status} /> },
    { colId: 'imei', headerName: 'IMEI', field: 'imei', width: 180 },
    { colId: 'description', headerName: 'Description', valueGetter: (p) => p.data && vehicleName(p.data), flex: 1.3, minWidth: 180, sort: 'asc' },
    { colId: 'registration', headerName: 'Registration', valueGetter: (p) => p.data && (detail(p.data, 'registration') || '—'), flex: 1, minWidth: 140 },
    { colId: 'make_model', headerName: 'Make / model', hide: true, valueGetter: (p) => p.data && ([detail(p.data, 'make'), detail(p.data, 'model'), detail(p.data, 'year')].filter(Boolean).join(' ') || '—'), width: 170 },
    { colId: 'driver', headerName: 'Driver', hide: true, valueGetter: (p) => p.data && (detail(p.data, 'driver') || '—'), width: 150 },
    { colId: 'group', headerName: 'Group', hide: true, field: 'category_name', valueFormatter: (p) => p.value || '—', width: 150 },
    { colId: 'status', headerName: 'Status', hide: true, field: 'activity_status', width: 120,
      cellRenderer: (p: ICellRendererParams<Vehicle>) => p.data && (
        <Badge size="sm" variant="dot" color={STATUS[p.data.activity_status]} styles={{ root: { textTransform: 'capitalize' } }}>{p.data.activity_status}</Badge>) },
    { colId: 'last_seen', headerName: 'Last seen', field: 'last_seen', valueFormatter: (p) => ago(p.value), width: 130 },
    { colId: 'package', headerName: 'Package', hide: true, field: 'package_name', valueFormatter: (p) => p.value || '—', width: 150 },
    { colId: 'expires', headerName: 'Expires', hide: true, field: 'expiry_date', width: 140, valueFormatter: (p) => (p.value ? dateTime(p.value).slice(0, 11) : '—'),
      cellStyle: (p) => ((p.data?.days_remaining ?? 99) < 30 ? { color: 'var(--mantine-color-orange-6)' } : null) },
    ...(admin ? [{ colId: 'actions', headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<Vehicle>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Edit" withinPortal><ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit vehicle"><IconPencil size={15} /></ActionIcon></Tooltip>
          {canDelete && <Tooltip label="Delete" withinPortal><ActionIcon size="sm" variant="subtle" color="red" onClick={() => startDelete(p.data!)} aria-label="Delete vehicle"><IconBan size={15} /></ActionIcon></Tooltip>}
        </Group>) }] : []),
  ];

  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <ConfigHeader section="Vehicles" title="Vehicles" description="Devices arrive automatically from your Data Exchange. Name them, add details and a group here." />
      <Group mb="sm" justify="space-between">
        <TextInput size="xs" w={280} placeholder="Search IMEI, description, registration, driver" leftSection={<IconSearch size={14} />}
                   value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
        <Text size="sm" c="dimmed">{shown.length} vehicles · the gear shows more columns</Text>
      </Group>
      <Paper withBorder className={classes.gridCard}>
        <DataGrid rowData={shown} columnDefs={cols} loading={isFetching && !vehicles.length} getRowId={(p) => p.data.id}
                  stateKey="config-vehicles" onRowDoubleClicked={(e) => admin && e.data && open(e.data)} />
      </Paper>
      <Modal opened={!!deleting} onClose={() => setDeleting(null)} title="Delete vehicle" centered>
        {deleting && (
          <Stack>
            <Alert color="red" variant="light" icon={<IconAlertTriangle size={16} />}>
              <b>{vehicleName(deleting.vehicle)}</b> ({deleting.vehicle.imei}) and all its positions, trips and events will be
              permanently deleted. This can't be undone.
            </Alert>
            <Text size="sm">To confirm, type the code <Code fz="md" fw={700}>{deleting.code}</Code></Text>
            <PinInput length={4} type="number" value={typed} onChange={setTyped} oneTimeCode={false} aria-label="Confirmation code" />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDeleting(null)}>Cancel</Button>
              <Button color="red" disabled={typed !== deleting.code} onClick={doDelete}>Delete vehicle</Button>
            </Group>
          </Stack>
        )}
      </Modal>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing ? `Edit ${vehicleName(editing)}` : ''}
                   onSave={() => save()} sections={editing ? [
        { id: 'general', label: 'General', keywords: 'name description group',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" placeholder="e.g. Truck 12" {...form.getInputProps('description')} data-autofocus />
              <Select label="Vehicle group" placeholder="No group" clearable data={categories.map((c) => c.name)}
                      description="The group's security group decides who sees this vehicle"
                      value={form.values.category || null} onChange={(v) => form.setFieldValue('category', v ?? '')} />
            </Stack>
          ) },
        { id: 'details', label: 'Vehicle details', keywords: 'registration driver make model year',
          content: (
            <SimpleGrid cols={{ base: 1, sm: 2 }} maw={760}>
              <TextInput label="Registration" placeholder="e.g. CA 123-456" {...form.getInputProps('registration')} />
              <TextInput label="Driver" placeholder="Driver's name" {...form.getInputProps('driver')} />
              <TextInput label="Make" placeholder="e.g. Toyota" {...form.getInputProps('make')} />
              <TextInput label="Model" placeholder="e.g. Hilux 2.8 GD-6" {...form.getInputProps('model')} />
              <TextInput label="Year" placeholder="e.g. 2022" maxLength={4} {...form.getInputProps('year')} />
            </SimpleGrid>
          ) },
        { id: 'device', label: 'Device', keywords: 'imei unit model package expiry last seen',
          content: (
            <SimpleGrid cols={{ base: 1, sm: 2 }} maw={760} verticalSpacing="sm">
              <TextInput label="IMEI" value={editing.imei} readOnly />
              <TextInput label="Unit type" value={editing.device_model ?? '—'} readOnly />
              <TextInput label="Last seen" value={editing.last_seen ? `${dateTime(editing.last_seen)} (${ago(editing.last_seen)})` : 'Never'} readOnly />
              <TextInput label="Package" value={editing.package_name ?? '—'} readOnly />
              <TextInput label="Expires" value={editing.expiry_date ? dateTime(editing.expiry_date).slice(0, 11) : '—'} readOnly />
            </SimpleGrid>
          ) },
        ...(canDelete ? [{ id: 'delete', label: 'Delete vehicle', danger: true, keywords: 'remove delete',
          content: (
            <Stack maw={620} align="flex-start">
              <Text size="sm">Deleting {vehicleName(editing)} removes it and all its positions, trips and events for good. You'll be asked to type a code to confirm.</Text>
              <Button color="red" variant="light" leftSection={<IconBan size={16} />} onClick={() => { const v = editing; setEditing(null); startDelete(v); }}>Delete vehicle</Button>
            </Stack>
          ) }] : []),
      ] : []} />
    </Stack>
  );
}

// ── Vehicle groups ──
function Groups() {
  const qc = useQueryClient();
  const { data: categories = [] } = useCategories();
  const { data: vehicles = [] } = useVehicles();
  const { data: securityGroups = [] } = useSecurityGroups();
  const sgName = (id: string | null) => securityGroups.find((g) => g.id === id)?.name;
  const [editing, setEditing] = useState<Category | 'new' | null>(null);
  const form = useForm<{ name: string; color: string; security_group_id: string | null }>({
    initialValues: { name: '', color: '#3e7cfb', security_group_id: null },
    validate: {
      name: (v) => (v.trim() ? null : 'Enter a name'),
      security_group_id: (v) => (v ? null : 'Choose the security group that may see these vehicles'),
    },
  });

  const open = (c: Category | 'new') => {
    form.setValues(c === 'new' ? { name: '', color: '#3e7cfb', security_group_id: securityGroups.length === 1 ? securityGroups[0].id : null }
      : { name: c.name, color: c.color || '#3e7cfb', security_group_id: c.security_group_id });
    setEditing(c);
  };
  const save = (andNew: boolean) => form.onSubmit(async (values) => {
    try {
      if (editing === 'new') await api('/api/portal/categories', { method: 'POST', json: values });
      else await api(`/api/portal/categories/${(editing as Category).id}`, { method: 'PUT', json: values });
      qc.invalidateQueries({ queryKey: ['categories'] });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      qc.invalidateQueries({ queryKey: ['security-groups'] });
      notifications.show({ color: 'green', message: `${values.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  }, firstError)();
  const remove = (c: Category) => modals.openConfirmModal({
    title: `Delete group “${c.name}”?`,
    children: <Text size="sm">Vehicles in this group stay on the platform; they just lose the group.</Text>,
    labels: { confirm: 'Delete group', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => {
      try { await api(`/api/portal/categories/${c.id}`, { method: 'DELETE' }); qc.invalidateQueries({ queryKey: ['categories'] }); }
      catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
    },
  });

  return (
    <Stack p="lg" gap={0} className={classes.narrow}>
      <Header title="Vehicle groups" />
      <Group justify="space-between" mb="sm">
        <Text size="sm" c="dimmed">“All vehicles” is built in. Each group belongs to a security group, whose users can see its vehicles.</Text>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add group</Button>
      </Group>
      <Paper withBorder>
        {categories.length === 0 && <Text c="dimmed" size="sm" p="md">No groups yet.</Text>}
        {categories.map((c) => (
          <Group key={c.id} className={classes.row} wrap="nowrap">
            <span className={classes.swatch} style={{ background: c.color || '#3e7cfb' }} />
            <Text fw={500} style={{ flex: 1 }}>{c.name}</Text>
            {sgName(c.security_group_id)
              ? <Badge variant="light" leftSection={<IconShieldLock size={12} />}>{sgName(c.security_group_id)}</Badge>
              : <Badge variant="light" color="orange">No security group — admins only</Badge>}
            <Text size="sm" c="dimmed" w={90} ta="right">{vehicles.filter((v) => v.category_name === c.name).length} vehicles</Text>
            <ActionIcon variant="subtle" onClick={() => open(c)} aria-label="Edit group"><IconPencil size={16} /></ActionIcon>
            <ActionIcon variant="subtle" color="red" onClick={() => remove(c)} aria-label="Delete group"><IconTrash size={16} /></ActionIcon>
          </Group>
        ))}
      </Paper>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Vehicle Group' : 'Edit Vehicle Group'}
                   onSave={() => save(false)} onSaveAndNew={() => save(true)} sections={[
        { id: 'general', label: 'General', keywords: 'name colour color',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" withAsterisk {...form.getInputProps('name')} data-autofocus />
              <ColorInput label="Colour" {...form.getInputProps('color')} />
            </Stack>
          ) },
        { id: 'security', label: 'Security group', keywords: 'security group visibility',
          content: (
            <Stack maw={760}>
              <Text size="sm" c="dimmed">Users in this security group can see the vehicles in this vehicle group.</Text>
              {form.errors.security_group_id && <Text size="sm" c="red">{form.errors.security_group_id}</Text>}
              {securityGroups.length === 0 && <Text size="sm" c="orange">Create a security group first under Configuration → Security.</Text>}
              <Radio.Group value={form.values.security_group_id ?? ''} onChange={(v) => form.setFieldValue('security_group_id', v || null)}>
                <Stack gap="xs">
                  {securityGroups.map((g) => (
                    <Paper key={g.id} withBorder p="sm" radius="md">
                      <Radio value={g.id} label={<Text size="sm" fw={600}>{g.name}</Text>}
                             description={`${g.user_count} user${g.user_count === 1 ? '' : 's'}${g.description ? ` · ${g.description}` : ''}`} />
                    </Paper>
                  ))}
                </Stack>
              </Radio.Group>
            </Stack>
          ) },
        ...(editing && editing !== 'new' ? [{ id: 'vehicles', label: 'Vehicles', keywords: 'vehicles members',
          content: (() => {
            const inGroup = vehicles.filter((v) => v.category_name === editing.name);
            return (
              <Stack maw={760} gap={6}>
                <Text size="sm" c="dimmed">{inGroup.length} vehicle{inGroup.length === 1 ? '' : 's'} in this group. Change a vehicle's group under Vehicles.</Text>
                {inGroup.map((v) => <Text key={v.id} size="sm">{vehicleName(v)} <Text span c="dimmed">· {v.imei}</Text></Text>)}
              </Stack>
            );
          })() }] : []),
      ]} />
    </Stack>
  );
}

// ── Data Exchange ──
function Exchange() {
  const qc = useQueryClient();
  const { data: ex } = useDataExchange();
  const form = useForm({ initialValues: { exchange_key: '', exchange_secret: '' },
    validate: { exchange_key: (v) => (v.trim() ? null : 'Required'), exchange_secret: (v) => (v.trim() ? null : 'Required') } });
  const link = form.onSubmit(async (values) => {
    try {
      await api('/api/portal/data-exchange/link', { method: 'POST', json: values });
      qc.invalidateQueries({ queryKey: ['data-exchange'] });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      form.reset();
      notifications.show({ color: 'green', message: 'Data Exchange linked' });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  });

  return (
    <Stack p="lg" gap={0} className={classes.narrow}>
      <Header title="Data Exchange" />
      {ex?.linked ? (
        <Paper withBorder p="lg">
          <Group justify="space-between" mb="md">
            <Group gap="sm"><ThemeIcon color="green" variant="light" size="lg"><IconPlugConnected size={20} /></ThemeIcon>
              <div><Text fw={650}>Linked to {ex.reseller_name}</Text><Text size="sm" c="dimmed">Since {dateTime(ex.linked_at)}</Text></div></Group>
            <Badge color="green" variant="light">Active</Badge>
          </Group>
          <SimpleGrid cols={3}>
            <div><Text size="xs" c="dimmed" tt="uppercase">Exchange key</Text><Text ff="monospace" size="sm">{ex.exchange_key}</Text></div>
            <div><Text size="xs" c="dimmed" tt="uppercase">Devices routed</Text><Text fw={650}>{ex.devices_routed ?? 0}</Text></div>
            <div><Text size="xs" c="dimmed" tt="uppercase">Pending</Text><Text fw={650}>{ex.devices_pending ?? 0}</Text></div>
          </SimpleGrid>
        </Paper>
      ) : (
        <Paper withBorder p="lg">
          <Text size="sm" c="dimmed" mb="md">Enter the exchange key and secret your reseller gave you. Devices routed to the exchange appear under Vehicles automatically.</Text>
          <form onSubmit={link}>
            <Stack>
              <TextInput label="Exchange key" placeholder="dpx_…" {...form.getInputProps('exchange_key')} />
              <PasswordInput label="Exchange secret" {...form.getInputProps('exchange_secret')} />
              <Group justify="flex-end"><Button type="submit" leftSection={<IconPlugConnected size={16} />}>Link exchange</Button></Group>
            </Stack>
          </form>
        </Paper>
      )}
    </Stack>
  );
}

// ── My account (from the user menu; everyone, whatever their roles) ──
export function AccountPage() {
  const user = getSession().user;
  const { data: me } = useMe();
  const form = useForm({
    initialValues: { current_password: '', new_password: '', confirm: '' },
    validate: {
      current_password: (v) => (v ? null : 'Required'),
      new_password: (v) => (v.length >= 8 ? null : 'At least 8 characters'),
      confirm: (v, all) => (v === all.new_password ? null : 'Passwords do not match'),
    },
  });
  const submit = form.onSubmit(async ({ current_password, new_password }) => {
    try {
      await api('/api/portal/account/change-password', { method: 'POST', json: { current_password, new_password } });
      form.reset();
      notifications.show({ color: 'green', message: 'Password changed' });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  });
  return (
    <Stack p="lg" gap={0} className={classes.narrow}>
      <Title order={2} mb="md">My account</Title>
      <Paper withBorder p="lg" mb="md">
        <Group gap="sm"><ThemeIcon variant="light" size="lg"><IconKey size={20} /></ThemeIcon>
          <div><Text fw={650}>{[user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email}</Text>
            <Text size="sm" c="dimmed">{user?.email}</Text></div></Group>
        {me?.access && (
          <Text size="sm" mt="sm"><Text span c="dimmed">Roles: </Text>{me.access.is_admin ? 'User Group Administrator' : (me.access.role_names ?? []).join(', ') || '—'}
            {me.access.security_group_name && <><Text span c="dimmed"> · Security group: </Text>{me.access.security_group_name}</>}</Text>
        )}
      </Paper>
      <Paper withBorder p="lg">
        <Text fw={650} mb="md">Change password</Text>
        <form onSubmit={submit}>
          <Stack>
            <PasswordInput label="Current password" autoComplete="current-password" {...form.getInputProps('current_password')} />
            <PasswordInput label="New password" autoComplete="new-password" {...form.getInputProps('new_password')} />
            <PasswordInput label="Confirm new password" autoComplete="new-password" {...form.getInputProps('confirm')} />
            <Group justify="flex-end"><Button type="submit">Change password</Button></Group>
          </Stack>
        </form>
      </Paper>
      <div style={{ height: 16 }} />
      <MyNotificationPrefs />
    </Stack>
  );
}

// ── Misc: a list of smaller tools ──
const MISC = [
  { to: 'notification-rules', title: 'Notification Rules', description: 'Alert when vehicles enter or leave places; optional emails', icon: IconBellRinging },
];

function Misc() {
  const navigate = useNavigate();
  return (
    <Stack p="lg" gap={0} className={classes.narrow}>
      <Header title="Misc" />
      <Paper withBorder>
        {MISC.map((m) => (
          <UnstyledButton key={m.to} className={classes.miscRow} onClick={() => navigate(m.to)}>
            <Group wrap="nowrap">
              <ThemeIcon variant="light" size="lg"><m.icon size={20} /></ThemeIcon>
              <div style={{ flex: 1 }}><Text fw={600}>{m.title}</Text><Text size="sm" c="dimmed">{m.description}</Text></div>
              <IconChevronRight size={18} opacity={0.5} />
            </Group>
          </UnstyledButton>
        ))}
      </Paper>
    </Stack>
  );
}

export function ConfigurationPage() {
  return (
    <Routes>
      <Route index element={<Tiles />} />
      <Route path="devices" element={<Devices />} />
      <Route path="groups" element={<Groups />} />
      <Route path="exchange" element={<Exchange />} />
      <Route path="account" element={<Navigate to="/account" replace />} />
      <Route path="places" element={<PlacesPage />} />
      <Route path="security" element={<SecurityPage />} />
      <Route path="user-group" element={<UserGroupPage mode="theme" />} />
      <Route path="custom-themes" element={<UserGroupPage mode="theme" />} />
      <Route path="user-groups" element={<UserGroupPage mode="preferences" />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="place-groups" element={<PlaceGroupsPage />} />
      <Route path="geofences" element={<GeofencesPage />} />
      <Route path="event-types" element={<EventTypesPage />} />
      <Route path="event-type-groups" element={<EventTypeGroupsPage />} />
      <Route path="misc" element={<Misc />} />
      <Route path="misc/notification-rules" element={<NotificationRulesPage />} />
      <Route path="*" element={<Tiles />} />
    </Routes>
  );
}

