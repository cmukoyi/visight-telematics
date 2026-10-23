import { useMemo, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Anchor, Badge, Breadcrumbs, Button, CopyButton, Group, Menu, Modal, Paper,
  SimpleGrid, Stack, Tabs, Text, TextInput, Textarea, ThemeIcon, Title, Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconCheck, IconCopy, IconDots, IconHistory, IconLock, IconPencil, IconPlus, IconSearch, IconShieldLock, IconTrash,
  IconUserCheck, IconUserOff, IconUsers, IconUsersGroup,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useMe, usePortalUsers, useRoles, useSecurityGroups } from '../api/hooks';
import { AuditTrail } from './AuditTrailPage';
import { RoleEditor } from './RoleEditor';
import { UserEditor } from './UserEditor';
import type { PortalUserRow, Role, SecurityGroup } from '../api/types';
import { ConfigHeader } from '../components/ConfigHeader';
import { DataGrid } from '../components/DataGrid';
import { EditorShell, firstError } from '../components/EditorShell';
import { dateTime } from '../utils/format';
import classes from './SecurityPage.module.css';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const fullName = (u: PortalUserRow) => [u.first_name, u.last_name].filter(Boolean).join(' ') || '—';

/** Shows a temporary password once, with a copy button. */
function TempPassword({ email, password, onClose }: { email: string; password: string | null; onClose: () => void }) {
  return (
    <Modal opened={!!password} onClose={onClose} title="Temporary password" centered>
      <Stack>
        <Text size="sm">Give this password to <b>{email}</b>. It is shown only once; they can change it under My account.</Text>
        <Group wrap="nowrap">
          <TextInput value={password ?? ''} readOnly style={{ flex: 1 }} ff="monospace" aria-label="Temporary password" />
          <CopyButton value={password ?? ''}>
            {({ copied, copy }) => (
              <Button variant="light" color={copied ? 'green' : undefined} leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />} onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </Button>
            )}
          </CopyButton>
        </Group>
        <Group justify="flex-end"><Button onClick={onClose}>Done</Button></Group>
      </Stack>
    </Modal>
  );
}

// ── Users ──
function UsersTab() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('users.manage');
  const { data: users = [], isFetching } = usePortalUsers();
  const { data: groups = [] } = useSecurityGroups();
  const { data: me } = useMe();
  const [editing, setEditing] = useState<PortalUserRow | 'new' | null>(null);
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const sgById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ['portal-users'] }); qc.invalidateQueries({ queryKey: ['roles'] }); };
  const setActive = async (u: PortalUserRow, active: boolean) => {
    try { await api(`/api/portal/users/${u.id}`, { method: 'PATCH', json: { is_active: active } }); refresh(); } catch (e) { fail(e); }
  };

  const isSelf = (u: PortalUserRow) => u.id === me?.portal_user.id;
  const rows = users.filter((u) => !search || `${u.email} ${fullName(u)} ${(u.role_names ?? []).join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<PortalUserRow>[] = [
    { colId: 'state', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data &&
        <span className={classes.stateDot} data-active={p.data.is_active} title={p.data.is_active ? 'Active' : 'Disabled'} /> },
    { colId: 'description', headerName: 'Description', valueGetter: (p) => p.data && fullName(p.data), flex: 1, minWidth: 160, sort: 'asc' },
    { colId: 'username', headerName: 'Username', field: 'email', flex: 1.2, minWidth: 200 },
    { colId: 'last_login', headerName: 'Last login', field: 'last_login_at', valueFormatter: (p) => dateTime(p.value), width: 170 },
    { colId: 'last_activity', headerName: 'Last activity', field: 'last_active_at', valueFormatter: (p) => dateTime(p.value), width: 170 },
    { colId: 'role', headerName: 'Roles', valueGetter: (p) => (p.data?.role_names ?? []).join(', ') || '—', flex: 1.3, minWidth: 200,
      tooltipValueGetter: (p) => (p.data?.role_names ?? []).join(', ') },
    { colId: 'security_group', headerName: 'Security group', flex: 1, minWidth: 150,
      valueGetter: (p) => sgById.get(p.data?.security_group_id ?? '')?.name ?? '',
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && (p.value
        ? p.value
        : p.data.role === 'admin' || p.data.is_group_admin
          ? <Text size="sm" c="dimmed">All vehicles</Text>
          : <Text size="sm" c="dimmed">—</Text>) },
    { colId: 'status', headerName: 'Status', field: 'is_active', width: 110, hide: true,
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && <Badge size="sm" variant="light" color={p.data.is_active ? 'green' : 'gray'}>{p.data.is_active ? 'Active' : 'Disabled'}</Badge> },
    { colId: 'created', headerName: 'Created', field: 'created_at', valueFormatter: (p) => dateTime(p.value), width: 170, hide: true },
    ...(manage ? [{ headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && !isSelf(p.data) && (
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label="User actions"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => setEditing(p.data!)}>Edit</Menu.Item>
            {p.data.is_active
              ? <Menu.Item color="red" leftSection={<IconUserOff size={14} />} onClick={() => setActive(p.data!, false)}>Disable</Menu.Item>
              : <Menu.Item leftSection={<IconUserCheck size={14} />} onClick={() => setActive(p.data!, true)}>Enable</Menu.Item>}
          </Menu.Dropdown>
        </Menu>) }] : []),
  ];

  return (
    <Stack gap="sm" className={classes.tabBody}>
      <Group justify="space-between">
        <TextInput size="xs" w={260} placeholder="Search name, email or role" leftSection={<IconSearch size={14} />} value={search}
                   onChange={(e) => setSearch(e.currentTarget.value)} />
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>Add user</Button>}
      </Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !users.length} getRowId={(p) => p.data.id} stateKey="config-users"
                  onRowDoubleClicked={(e) => manage && e.data && !isSelf(e.data) && setEditing(e.data)} />
      </Paper>
      <UserEditor opened={!!editing} user={editing === 'new' ? null : editing} onClose={() => setEditing(null)}
                  onCreated={(email, password) => setTemp({ email, password })} />
      <TempPassword email={temp?.email ?? ''} password={temp?.password ?? null} onClose={() => setTemp(null)} />
    </Stack>
  );
}

// ── Security groups ──
function SecurityGroupsTab() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('security.manage');
  const { data: groups = [] } = useSecurityGroups();
  const [editing, setEditing] = useState<SecurityGroup | 'new' | null>(null);
  const form = useForm({ initialValues: { name: '', description: '' }, validate: { name: (v) => (v.trim() ? null : 'Enter a name') } });
  const open = (g: SecurityGroup | 'new') => { form.setValues(g === 'new' ? { name: '', description: '' } : { name: g.name, description: g.description ?? '' }); setEditing(g); };
  const { data: users = [] } = usePortalUsers(can('users.view') || can('users.manage'));
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      if (editing === 'new') await api('/api/portal/security-groups', { method: 'POST', json: v });
      else if (editing) await api(`/api/portal/security-groups/${editing.id}`, { method: 'PUT', json: v });
      qc.invalidateQueries({ queryKey: ['security-groups'] });
      notifications.show({ color: 'green', message: `${v.name} saved` });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { fail(e); }
  }, firstError)();
  const remove = (g: SecurityGroup) => modals.openConfirmModal({
    title: `Delete “${g.name}”?`, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">Only empty security groups can be deleted.</Text>,
    onConfirm: async () => { try { await api(`/api/portal/security-groups/${g.id}`, { method: 'DELETE' }); qc.invalidateQueries({ queryKey: ['security-groups'] }); } catch (e) { fail(e); } },
  });

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          A security group decides which vehicles a user sees: put vehicle groups in it (Configuration → Vehicle groups) and add users to it.
          User Group Administrators see every vehicle.
        </Text>
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add security group</Button>}
      </Group>
      {groups.length === 0 && <Paper withBorder p="xl"><Text c="dimmed" ta="center" size="sm">No security groups yet.</Text></Paper>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {groups.map((g) => (
          <Paper key={g.id} withBorder p="md" className={classes.card}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Group gap="sm" wrap="nowrap">
                <ThemeIcon variant="light" size="lg"><IconShieldLock size={20} /></ThemeIcon>
                <div><Text fw={650}>{g.name}</Text>{g.description && <Text size="xs" c="dimmed">{g.description}</Text>}</div>
              </Group>
              {manage && (
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" onClick={() => open(g)} aria-label={`Edit ${g.name}`}><IconPencil size={16} /></ActionIcon>
                  <ActionIcon variant="subtle" color="red" onClick={() => remove(g)} aria-label={`Delete ${g.name}`}><IconTrash size={16} /></ActionIcon>
                </Group>
              )}
            </Group>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700} mt="md" mb={4}>Vehicle groups</Text>
            <Group gap={4}>
              {g.vehicle_groups.length ? g.vehicle_groups.map((n) => <Badge key={n} variant="light">{n}</Badge>)
                : <Text size="sm" c="dimmed">None yet</Text>}
            </Group>
            <Group gap={6} mt="sm"><IconUsers size={14} opacity={0.6} /><Text size="sm" c="dimmed">{g.user_count} user{g.user_count === 1 ? '' : 's'}</Text></Group>
          </Paper>
        ))}
      </SimpleGrid>
      <EditorShell opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New Security Group' : 'Edit Security Group'}
                   onSave={manage ? () => save(false) : undefined} onSaveAndNew={manage ? () => save(true) : undefined} sections={[
        { id: 'general', label: 'General', keywords: 'name description',
          content: (
            <Stack maw={620}>
              <TextInput label="Name" withAsterisk placeholder="e.g. Northern region" disabled={!manage} {...form.getInputProps('name')} data-autofocus />
              <Textarea label="Description" autosize minRows={2} disabled={!manage} {...form.getInputProps('description')} />
            </Stack>
          ) },
        { id: 'vehicles', label: 'Vehicle groups', keywords: 'vehicle groups vehicles',
          content: (
            <Stack maw={760} gap="xs">
              <Text size="sm" c="dimmed">Users in this security group see the vehicles in these vehicle groups. Choose a vehicle group's security group under Configuration → Vehicles → Vehicle Groups.</Text>
              <Group gap={6}>
                {editing && editing !== 'new' && editing.vehicle_groups.length
                  ? editing.vehicle_groups.map((n) => <Badge key={n} variant="light">{n}</Badge>)
                  : <Text size="sm" c="dimmed">None yet</Text>}
              </Group>
            </Stack>
          ) },
        { id: 'users', label: 'Users', keywords: 'users members',
          content: (() => {
            const members = editing && editing !== 'new' ? users.filter((u) => u.security_group_id === editing.id) : [];
            return (
              <Stack maw={760} gap={6}>
                <Text size="sm" c="dimmed">Choose a user's security group in their user editor (Configuration → Users).</Text>
                {members.length === 0 && <Text size="sm" c="dimmed">No users yet.</Text>}
                {members.map((u) => <Text key={u.id} size="sm">{fullName(u)} <Text span c="dimmed">· {u.email}</Text></Text>)}
              </Stack>
            );
          })() },
      ]} />
    </Stack>
  );
}

// ── Roles ──
function RolesTab() {
  const qc = useQueryClient();
  const manage = useCan()('roles.manage');
  const { data: roles = [], isFetching } = useRoles();
  const [editing, setEditing] = useState<Role | 'new' | null>(null);
  const remove = (r: Role) => modals.openConfirmModal({
    title: `Delete role “${r.name}”?`, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">Only roles that nobody holds can be deleted.</Text>,
    onConfirm: async () => { try { await api(`/api/portal/roles/${r.id}`, { method: 'DELETE' }); qc.invalidateQueries({ queryKey: ['roles'] }); } catch (e) { fail(e); } },
  });
  const cols: ColDef<Role>[] = [
    { colId: 'name', headerName: 'Role', field: 'name', flex: 1, minWidth: 200,
      cellRenderer: (p: ICellRendererParams<Role>) => p.data && (
        <Group gap={6} wrap="nowrap">
          <Text size="sm" fw={600}>{p.data.name}</Text>
          {p.data.is_admin ? <Badge size="xs" color="red" variant="light">Admin</Badge>
            : p.data.is_system ? <Tooltip label="Built-in role — duplicate it to make your own"><Badge size="xs" variant="default" leftSection={<IconLock size={10} />}>Built-in</Badge></Tooltip> : null}
        </Group>) },
    { colId: 'description', headerName: 'What it’s for', field: 'description', flex: 2, minWidth: 260, valueFormatter: (p) => p.value || '—' },
    { colId: 'features', headerName: 'Features', width: 120, valueGetter: (p) => p.data?.permissions.length ?? 0,
      valueFormatter: (p) => (p.data?.is_admin ? 'All' : String(p.value)) },
    { colId: 'users', headerName: 'Users', field: 'user_count', width: 100 },
    ...(manage ? [{ headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<Role>) => p.data && (
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label="Role actions"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => setEditing(p.data!)}>{p.data.is_system ? 'Open' : 'Edit'}</Menu.Item>
            {!p.data.is_system && <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => remove(p.data!)}>Delete</Menu.Item>}
          </Menu.Dropdown>
        </Menu>) }] : []),
  ];
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={720}>
          A role is a set of features. Users can hold several roles and may do anything one of them allows. Built-in roles are kept up to date for you;
          duplicate one to make your own.
        </Text>
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>New role</Button>}
      </Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={roles} columnDefs={cols} loading={isFetching && !roles.length} getRowId={(p) => p.data.id} stateKey="config-roles"
                  onRowDoubleClicked={(e) => e.data && setEditing(e.data)} />
      </Paper>
      <RoleEditor opened={!!editing} role={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}

/** Configuration → Users → Users */
export function UsersPage() {
  const can = useCan();
  return (
    <Stack p="lg" gap={0}>
      <ConfigHeader section="Users" title="Users" description="People who can sign in, with their role and the security group whose vehicles they see." />
      {can('users.view') || can('users.manage') ? <UsersTab /> : <Text c="dimmed">Your roles don’t include seeing users.</Text>}
    </Stack>
  );
}

export function SecurityPage() {
  const can = useCan();
  const [params, setParams] = useSearchParams();
  if (params.get('tab') === 'users') return <Navigate to="/configuration/users" replace />;
  const tabs = [
    { value: 'groups', label: 'Security groups', icon: IconUsersGroup, show: can('security.manage') || can('users.manage') },
    { value: 'roles', label: 'Roles', icon: IconShieldLock, show: can('roles.manage') || can('users.manage') || can('users.view') },
    { value: 'audit', label: 'Audit Trail', icon: IconHistory, show: can('audit.view') },
  ].filter((t) => t.show);
  const tab = tabs.some((t) => t.value === params.get('tab')) ? params.get('tab')! : tabs[0]?.value;

  return (
    <Stack p="lg" gap="md" className={classes.root}>
      <Stack gap={4}>
        <Breadcrumbs>
          <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
          <Text size="sm">Security</Text>
        </Breadcrumbs>
        <Title order={1} size="h2">Security</Title>
      </Stack>
      {tabs.length === 0 ? <Text c="dimmed">Your roles don’t include security settings.</Text> : (
        <Tabs value={tab} onChange={(v) => setParams(v ? { tab: v } : {}, { replace: true })} keepMounted={false}>
          <Tabs.List mb="md">
            {tabs.map((t) => <Tabs.Tab key={t.value} value={t.value} leftSection={<t.icon size={16} />}>{t.label}</Tabs.Tab>)}
          </Tabs.List>
          <Tabs.Panel value="groups"><SecurityGroupsTab /></Tabs.Panel>
          <Tabs.Panel value="roles"><RolesTab /></Tabs.Panel>
          <Tabs.Panel value="audit"><AuditTrail /></Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
}
