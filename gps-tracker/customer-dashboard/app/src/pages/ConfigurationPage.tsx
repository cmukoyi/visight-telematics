import { useState } from 'react';
import { Link, Route, Routes, useNavigate } from 'react-router-dom';
import {
  ActionIcon, Anchor, Badge, Breadcrumbs, Button, ColorInput, Group, Modal, Paper, PasswordInput, Select, SimpleGrid, Stack,
  Text, TextInput, ThemeIcon, Title, UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconArrowUpRight, IconBell, IconCar, IconCategory, IconKey, IconMapPin, IconPencil, IconPlugConnected,
  IconTrash, IconUsers, IconPlus,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCategories, useDataExchange, useVehicles } from '../api/hooks';
import type { Category, Vehicle } from '../api/types';
import { getSession, isAdminLike } from '../auth/session';
import { DataGrid } from '../components/DataGrid';
import { STATUS } from '../theme';
import { ago, dateTime, vehicleName } from '../utils/format';
import classes from './ConfigurationPage.module.css';

interface Tile { title: string; description: string; icon: typeof IconCar; to?: string; classic?: string; adminOnly?: boolean }

const TILES: Tile[] = [
  { title: 'Vehicles & devices', description: 'Names, groups and packages of your tracking units', icon: IconCar, to: 'devices' },
  { title: 'Vehicle groups', description: 'Groups used to filter the dashboard, workspace and reports', icon: IconCategory, to: 'groups' },
  { title: 'Data Exchange', description: 'Link the exchange that routes your devices to this account', icon: IconPlugConnected, to: 'exchange', adminOnly: true },
  { title: 'My account', description: 'Change your password', icon: IconKey, to: 'account' },
  { title: 'Users', description: 'Invite users and manage their access', icon: IconUsers, classic: 'users', adminOnly: true },
  { title: 'Places', description: 'Geofences, depots and customer sites', icon: IconMapPin, classic: 'locations' },
  { title: 'Notifications & appearance', description: 'Alert settings, logo and colours', icon: IconBell, classic: 'settings', adminOnly: true },
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
  const admin = isAdminLike(getSession().user);
  return (
    <Stack p="lg" gap="lg">
      <Title order={2}>Configuration</Title>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3, xl: 4 }} spacing="md">
        {TILES.filter((t) => admin || !t.adminOnly).map((t) => (
          <UnstyledButton key={t.title} className={classes.tile}
                          onClick={() => (t.to ? navigate(t.to) : window.open(classicUrl(t.classic!), '_self'))}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <ThemeIcon size={44} radius="md" variant="light"><t.icon size={24} /></ThemeIcon>
              {t.classic && <Badge size="xs" variant="outline" color="gray" rightSection={<IconArrowUpRight size={10} />}>Classic</Badge>}
            </Group>
            <Text fw={650} mt="md">{t.title}</Text>
            <Text size="sm" c="dimmed" mt={4}>{t.description}</Text>
          </UnstyledButton>
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
  const form = useForm({ initialValues: { description: '', category: '' } });
  const admin = isAdminLike(getSession().user);

  const open = (v: Vehicle) => { form.setValues({ description: v.description ?? '', category: v.category_name ?? '' }); setEditing(v); };
  const save = form.onSubmit(async (values) => {
    try {
      await api(`/api/portal/tags/${editing!.id}`, { method: 'PUT', json: values });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      setEditing(null);
      notifications.show({ color: 'green', message: 'Vehicle saved' });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  });

  const cols: ColDef<Vehicle>[] = [
    { headerName: 'Name', valueGetter: (p) => p.data && vehicleName(p.data), flex: 1.3 },
    { headerName: 'IMEI', field: 'imei', width: 170 },
    { headerName: 'Group', field: 'category_name', valueFormatter: (p) => p.value || '—', width: 150 },
    { headerName: 'Status', field: 'activity_status', width: 120,
      cellRenderer: (p: ICellRendererParams<Vehicle>) => p.data && (
        <Badge size="sm" variant="dot" color={STATUS[p.data.activity_status]} styles={{ root: { textTransform: 'capitalize' } }}>{p.data.activity_status}</Badge>) },
    { headerName: 'Last seen', field: 'last_seen', valueFormatter: (p) => ago(p.value), width: 130 },
    { headerName: 'Package', field: 'package_name', valueFormatter: (p) => p.value || '—', width: 150 },
    { headerName: 'Expires', field: 'expiry_date', width: 140, valueFormatter: (p) => (p.value ? dateTime(p.value).slice(0, 11) : '—'),
      cellStyle: (p) => ((p.data?.days_remaining ?? 99) < 30 ? { color: 'var(--mantine-color-orange-6)' } : null) },
    ...(admin ? [{ headerName: '', width: 60, minWidth: 60, sortable: false, filter: false,
      cellRenderer: (p: ICellRendererParams<Vehicle>) => p.data && (
        <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit vehicle"><IconPencil size={15} /></ActionIcon>) }] : []),
  ];

  return (
    <Stack p="lg" gap={0} className={classes.page}>
      <Header title="Vehicles & devices" />
      <Text size="sm" c="dimmed" mb="sm">Devices arrive automatically from your Data Exchange. Give them a name and a group here.</Text>
      <Paper withBorder className={classes.gridCard}>
        <DataGrid rowData={vehicles} columnDefs={cols} loading={isFetching && !vehicles.length} getRowId={(p) => p.data.id} />
      </Paper>
      <Modal opened={!!editing} onClose={() => setEditing(null)} title={editing ? `Edit ${vehicleName(editing)}` : ''}>
        <form onSubmit={save}>
          <Stack>
            <TextInput label="Name" placeholder="e.g. Truck 12 — CA 123-456" {...form.getInputProps('description')} data-autofocus />
            <Select label="Group" placeholder="No group" clearable data={categories.map((c) => c.name)}
                    value={form.values.category || null} onChange={(v) => form.setFieldValue('category', v ?? '')} />
            <Group justify="flex-end"><Button variant="default" onClick={() => setEditing(null)}>Cancel</Button><Button type="submit">Save</Button></Group>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}

// ── Vehicle groups ──
function Groups() {
  const qc = useQueryClient();
  const { data: categories = [] } = useCategories();
  const { data: vehicles = [] } = useVehicles();
  const [editing, setEditing] = useState<Category | 'new' | null>(null);
  const form = useForm({ initialValues: { name: '', color: '#3e7cfb' }, validate: { name: (v) => (v.trim() ? null : 'Enter a name') } });

  const open = (c: Category | 'new') => {
    form.setValues(c === 'new' ? { name: '', color: '#3e7cfb' } : { name: c.name, color: c.color || '#3e7cfb' });
    setEditing(c);
  };
  const save = form.onSubmit(async (values) => {
    try {
      if (editing === 'new') await api('/api/portal/categories', { method: 'POST', json: values });
      else await api(`/api/portal/categories/${(editing as Category).id}`, { method: 'PUT', json: values });
      qc.invalidateQueries({ queryKey: ['categories'] });
      qc.invalidateQueries({ queryKey: ['vehicles'] });
      setEditing(null);
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  });
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
        <Text size="sm" c="dimmed">“All vehicles” is built in. Add groups to filter by depot, region or vehicle type.</Text>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add group</Button>
      </Group>
      <Paper withBorder>
        {categories.length === 0 && <Text c="dimmed" size="sm" p="md">No groups yet.</Text>}
        {categories.map((c) => (
          <Group key={c.id} className={classes.row} wrap="nowrap">
            <span className={classes.swatch} style={{ background: c.color || '#3e7cfb' }} />
            <Text fw={500} style={{ flex: 1 }}>{c.name}</Text>
            <Text size="sm" c="dimmed">{vehicles.filter((v) => v.category_name === c.name).length} vehicles</Text>
            <ActionIcon variant="subtle" onClick={() => open(c)} aria-label="Edit group"><IconPencil size={16} /></ActionIcon>
            <ActionIcon variant="subtle" color="red" onClick={() => remove(c)} aria-label="Delete group"><IconTrash size={16} /></ActionIcon>
          </Group>
        ))}
      </Paper>
      <Modal opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'Add group' : 'Edit group'}>
        <form onSubmit={save}>
          <Stack>
            <TextInput label="Name" {...form.getInputProps('name')} data-autofocus />
            <ColorInput label="Colour" {...form.getInputProps('color')} />
            <Group justify="flex-end"><Button variant="default" onClick={() => setEditing(null)}>Cancel</Button><Button type="submit">Save</Button></Group>
          </Stack>
        </form>
      </Modal>
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

// ── My account ──
function Account() {
  const user = getSession().user;
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
      <Header title="My account" />
      <Paper withBorder p="lg" mb="md">
        <Group gap="sm"><ThemeIcon variant="light" size="lg"><IconKey size={20} /></ThemeIcon>
          <div><Text fw={650}>{[user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email}</Text>
            <Text size="sm" c="dimmed">{user?.email} · {user?.role}</Text></div></Group>
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
      <Route path="account" element={<Account />} />
      <Route path="*" element={<Tiles />} />
    </Routes>
  );
}

