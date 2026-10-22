import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Checkbox, CopyButton, Group, Menu, Modal, Paper, ScrollArea,
  Select, SimpleGrid, Stack, Switch, Tabs, Text, TextInput, Textarea, ThemeIcon, Title, Tooltip, UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconCheck, IconCopy, IconDots, IconKey, IconLock, IconPencil, IconPlus, IconSearch, IconShieldLock, IconTrash,
  IconUserCheck, IconUserOff, IconUsers, IconUsersGroup,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useMe, usePermissions, usePortalUsers, useRoles, useSecurityGroups } from '../api/hooks';
import type { PortalUserRow, Role, SecurityGroup } from '../api/types';
import { DataGrid } from '../components/DataGrid';
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
type UserForm = { email: string; first_name: string; last_name: string; role_id: string | null; security_group_id: string | null; is_active: boolean };

function UsersTab() {
  const qc = useQueryClient();
  const { data: users = [], isFetching } = usePortalUsers();
  const { data: roles = [] } = useRoles();
  const { data: groups = [] } = useSecurityGroups();
  const { data: me } = useMe();
  const [editing, setEditing] = useState<PortalUserRow | 'new' | null>(null);
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const roleById = useMemo(() => new Map(roles.map((r) => [r.id, r])), [roles]);
  const sgById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);

  const form = useForm<UserForm>({
    initialValues: { email: '', first_name: '', last_name: '', role_id: null, security_group_id: null, is_active: true },
    validate: {
      email: (v) => (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim()) ? null : 'Enter a valid email address'),
      role_id: (v) => (v ? null : 'Choose a role'),
      security_group_id: (v, all) => (v || roleById.get(all.role_id ?? '')?.is_admin ? null : 'Choose a security group'),
    },
  });
  const open = (u: PortalUserRow | 'new') => {
    form.reset();
    if (u !== 'new') {
      form.setValues({ email: u.email, first_name: u.first_name ?? '', last_name: u.last_name ?? '', role_id: u.role_id,
                       security_group_id: u.security_group_id, is_active: u.is_active });
    }
    setEditing(u);
  };
  const refresh = () => { qc.invalidateQueries({ queryKey: ['portal-users'] }); qc.invalidateQueries({ queryKey: ['roles'] }); qc.invalidateQueries({ queryKey: ['security-groups'] }); };
  const save = form.onSubmit(async (v) => {
    try {
      if (editing === 'new') {
        const res = await api<{ portal_user: PortalUserRow; temp_password: string }>('/api/portal/users', { method: 'POST', json: {
          email: v.email.trim(), first_name: v.first_name.trim() || null, last_name: v.last_name.trim() || null,
          role_id: v.role_id, security_group_id: v.security_group_id,
        } });
        setTemp({ email: res.portal_user.email, password: res.temp_password });
      } else if (editing) {
        await api(`/api/portal/users/${editing.id}`, { method: 'PATCH', json: {
          first_name: v.first_name, last_name: v.last_name, role_id: v.role_id, security_group_id: v.security_group_id,
          ...(v.is_active !== editing.is_active ? { is_active: v.is_active } : {}),
        } });
        notifications.show({ color: 'green', message: 'User saved' });
      }
      refresh();
      setEditing(null);
    } catch (e) { fail(e); }
  });
  const resetPassword = (u: PortalUserRow) => modals.openConfirmModal({
    title: `Reset password for ${u.email}?`, children: <Text size="sm">Their current password stops working straight away.</Text>,
    labels: { confirm: 'Reset password', cancel: 'Cancel' },
    onConfirm: async () => {
      try { const r = await api<{ temp_password: string }>(`/api/portal/users/${u.id}/reset-password`, { method: 'POST' }); setTemp({ email: u.email, password: r.temp_password }); }
      catch (e) { fail(e); }
    },
  });
  const setActive = async (u: PortalUserRow, active: boolean) => {
    try { await api(`/api/portal/users/${u.id}`, { method: 'PATCH', json: { is_active: active } }); refresh(); } catch (e) { fail(e); }
  };

  const isSelf = (u: PortalUserRow) => u.id === me?.portal_user.id;
  const rows = users.filter((u) => !search || `${u.email} ${fullName(u)}`.toLowerCase().includes(search.toLowerCase()));
  const cols: ColDef<PortalUserRow>[] = [
    { headerName: 'Name', valueGetter: (p) => p.data && fullName(p.data), flex: 1, minWidth: 150 },
    { headerName: 'Email', field: 'email', flex: 1.3, minWidth: 200 },
    { headerName: 'Role', valueGetter: (p) => roleById.get(p.data?.role_id ?? '')?.name ?? (p.data?.is_group_admin ? 'User Group Administrator' : '—'), flex: 1, minWidth: 170 },
    { headerName: 'Security group', flex: 1, minWidth: 150,
      valueGetter: (p) => sgById.get(p.data?.security_group_id ?? '')?.name ?? '',
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && (p.value
        ? p.value
        : roleById.get(p.data.role_id ?? '')?.is_admin || p.data.is_group_admin
          ? <Text size="sm" c="dimmed">All vehicles</Text>
          : <Badge size="sm" color="orange" variant="light">None — sees no vehicles</Badge>) },
    { headerName: 'Status', field: 'is_active', width: 110,
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && <Badge size="sm" variant="light" color={p.data.is_active ? 'green' : 'gray'}>{p.data.is_active ? 'Active' : 'Disabled'}</Badge> },
    { headerName: 'Created', field: 'created_at', valueFormatter: (p) => dateTime(p.value), width: 170 },
    { headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right',
      cellRenderer: (p: ICellRendererParams<PortalUserRow>) => p.data && !isSelf(p.data) && (
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label="User actions"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => open(p.data!)}>Edit</Menu.Item>
            <Menu.Item leftSection={<IconKey size={14} />} onClick={() => resetPassword(p.data!)}>Reset password</Menu.Item>
            {p.data.is_active
              ? <Menu.Item color="red" leftSection={<IconUserOff size={14} />} onClick={() => setActive(p.data!, false)}>Disable</Menu.Item>
              : <Menu.Item leftSection={<IconUserCheck size={14} />} onClick={() => setActive(p.data!, true)}>Enable</Menu.Item>}
          </Menu.Dropdown>
        </Menu>) },
  ];
  const chosenRole = roleById.get(form.values.role_id ?? '');

  return (
    <Stack gap="sm" className={classes.tabBody}>
      <Group justify="space-between">
        <TextInput size="xs" w={260} placeholder="Search name or email" leftSection={<IconSearch size={14} />} value={search}
                   onChange={(e) => setSearch(e.currentTarget.value)} />
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add user</Button>
      </Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !users.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => e.data && !isSelf(e.data) && open(e.data)} />
      </Paper>
      <Modal opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'Add user' : 'Edit user'} size="lg">
        <form onSubmit={save}>
          <Stack>
            <TextInput label="Email" disabled={editing !== 'new'} {...form.getInputProps('email')} data-autofocus />
            <SimpleGrid cols={2}>
              <TextInput label="First name" {...form.getInputProps('first_name')} />
              <TextInput label="Last name" {...form.getInputProps('last_name')} />
              <Select label="Role" placeholder="Choose a role" allowDeselect={false} withAsterisk
                      data={roles.map((r) => ({ value: r.id, label: r.name }))} {...form.getInputProps('role_id')} />
              <Select label="Security group" placeholder={chosenRole?.is_admin ? 'Optional — admins see all vehicles' : 'Choose a security group'}
                      clearable withAsterisk={!chosenRole?.is_admin}
                      data={groups.map((g) => ({ value: g.id, label: g.name }))} {...form.getInputProps('security_group_id')} />
            </SimpleGrid>
            {chosenRole && (
              <Text size="xs" c="dimmed">{chosenRole.description || `${chosenRole.permissions.length} permissions`}
                {chosenRole.is_admin ? '' : ' · Sees only the vehicles in their security group.'}</Text>
            )}
            {groups.length === 0 && (
              <Alert color="orange" variant="light" p="xs">Create a security group first (Security groups tab).</Alert>
            )}
            {editing !== 'new' && <Switch label="Active (can sign in)" {...form.getInputProps('is_active', { type: 'checkbox' })} />}
            <Group justify="flex-end"><Button variant="default" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit">{editing === 'new' ? 'Add user' : 'Save'}</Button></Group>
          </Stack>
        </form>
      </Modal>
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
  const save = form.onSubmit(async (v) => {
    try {
      if (editing === 'new') await api('/api/portal/security-groups', { method: 'POST', json: v });
      else if (editing) await api(`/api/portal/security-groups/${editing.id}`, { method: 'PUT', json: v });
      qc.invalidateQueries({ queryKey: ['security-groups'] });
      setEditing(null);
    } catch (e) { fail(e); }
  });
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
                  <ActionIcon variant="subtle" onClick={() => open(g)} aria-label="Edit security group"><IconPencil size={16} /></ActionIcon>
                  <ActionIcon variant="subtle" color="red" onClick={() => remove(g)} aria-label="Delete security group"><IconTrash size={16} /></ActionIcon>
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
      <Modal opened={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'Add security group' : 'Edit security group'}>
        <form onSubmit={save}>
          <Stack>
            <TextInput label="Name" placeholder="e.g. Northern region" {...form.getInputProps('name')} data-autofocus />
            <Textarea label="Description" autosize minRows={2} {...form.getInputProps('description')} />
            <Group justify="flex-end"><Button variant="default" onClick={() => setEditing(null)}>Cancel</Button><Button type="submit">Save</Button></Group>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}

// ── Roles ──
function RolesTab() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can('security.manage');
  const { data: roles = [] } = useRoles();
  const { data: permissions = [] } = usePermissions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ name: string; description: string; permissions: string[] } | null>(null);
  const [creating, setCreating] = useState(false);
  const selected = roles.find((r) => r.id === selectedId) ?? roles[0];
  const sections = useMemo(() => [...new Set(permissions.map((p) => p.section))], [permissions]);

  const edit = (r: Role) => { setSelectedId(r.id); setCreating(false); setDraft({ name: r.name, description: r.description ?? '', permissions: [...r.permissions] }); };
  const startNew = () => { setCreating(true); setDraft({ name: '', description: '', permissions: ['map.view'] }); };
  const shown = draft ?? (selected ? { name: selected.name, description: selected.description ?? '', permissions: selected.permissions } : null);
  const readOnly = !manage || !draft || (!creating && selected?.is_admin);
  const toggle = (key: string) => setDraft((d) => d && { ...d, permissions: d.permissions.includes(key) ? d.permissions.filter((p) => p !== key) : [...d.permissions, key] });

  const save = async () => {
    if (!draft) return;
    try {
      const saved = creating
        ? await api<Role>('/api/portal/roles', { method: 'POST', json: draft })
        : await api<Role>(`/api/portal/roles/${selected!.id}`, { method: 'PUT', json: draft });
      await qc.invalidateQueries({ queryKey: ['roles'] });
      qc.invalidateQueries({ queryKey: ['me'] });
      setSelectedId(saved.id); setDraft(null); setCreating(false);
      notifications.show({ color: 'green', message: `Role “${saved.name}” saved` });
    } catch (e) { fail(e); }
  };
  const remove = (r: Role) => modals.openConfirmModal({
    title: `Delete role “${r.name}”?`, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">Only roles with no users can be deleted.</Text>,
    onConfirm: async () => { try { await api(`/api/portal/roles/${r.id}`, { method: 'DELETE' }); setSelectedId(null); qc.invalidateQueries({ queryKey: ['roles'] }); } catch (e) { fail(e); } },
  });

  return (
    <div className={classes.roles}>
      <Paper withBorder className={classes.roleList}>
        <Group justify="space-between" p="sm" className={classes.roleListHead}>
          <Text fw={650} size="sm">Roles</Text>
          {manage && <Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />} onClick={startNew}>New role</Button>}
        </Group>
        <ScrollArea type="auto" className={classes.roleScroll}>
          {roles.map((r) => (
            <UnstyledButton key={r.id} className={`${classes.roleRow} ${!creating && selected?.id === r.id ? classes.roleActive : ''}`}
                            onClick={() => { setSelectedId(r.id); setDraft(null); setCreating(false); }}>
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}>
                  <Group gap={6} wrap="nowrap">
                    <Text size="sm" fw={600} truncate>{r.name}</Text>
                    {r.is_system && <Tooltip label="Built-in role"><IconLock size={12} opacity={0.5} /></Tooltip>}
                  </Group>
                  <Text size="xs" c="dimmed">{r.is_admin ? 'All permissions · all vehicles' : `${r.permissions.length} permissions`}</Text>
                </div>
                <Badge size="sm" variant="default">{r.user_count}</Badge>
              </Group>
            </UnstyledButton>
          ))}
        </ScrollArea>
      </Paper>

      <Paper withBorder p="lg" className={classes.roleDetail}>
        {shown && (
          <Stack gap="md">
            <Group justify="space-between" align="flex-start">
              {draft && (creating || !selected?.is_system) ? (
                <TextInput label="Role name" value={draft.name} w={320} data-autofocus
                           onChange={(e) => { const v = e.currentTarget.value; setDraft((d) => d && { ...d, name: v }); }} />
              ) : (
                <div>
                  <Title order={3}>{shown.name}</Title>
                  <Text size="sm" c="dimmed">{selected?.is_admin ? 'Can do everything and sees every vehicle. Its permissions can’t be changed.'
                    : `${selected?.user_count ?? 0} user${selected?.user_count === 1 ? '' : 's'} · sees vehicles in their own security group`}</Text>
                </div>
              )}
              {manage && !draft && selected && !selected.is_admin && (
                <Group gap="xs">
                  <Button size="xs" variant="light" leftSection={<IconPencil size={14} />} onClick={() => edit(selected)}>Edit permissions</Button>
                  {!selected.is_system && <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} onClick={() => remove(selected)}>Delete</Button>}
                </Group>
              )}
            </Group>
            {draft && (
              <Textarea label="Description" autosize minRows={1} value={draft.description}
                        onChange={(e) => { const v = e.currentTarget.value; setDraft((d) => d && { ...d, description: v }); }} />
            )}
            {!draft && shown.description && <Text size="sm">{shown.description}</Text>}
            <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
              {sections.map((section) => (
                <Paper key={section} withBorder p="sm" radius="md">
                  <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="xs">{section}</Text>
                  <Stack gap={8}>
                    {permissions.filter((p) => p.section === section).map((p) => (
                      <Checkbox key={p.key} label={p.label} checked={shown.permissions.includes(p.key)}
                                disabled={!!readOnly} onChange={() => toggle(p.key)} />
                    ))}
                  </Stack>
                </Paper>
              ))}
            </SimpleGrid>
            {draft && (
              <Group justify="flex-end">
                <Button variant="default" onClick={() => { setDraft(null); setCreating(false); }}>Cancel</Button>
                <Button onClick={save} disabled={!draft.name.trim()}>{creating ? 'Create role' : 'Save role'}</Button>
              </Group>
            )}
          </Stack>
        )}
      </Paper>
    </div>
  );
}

export function SecurityPage() {
  const can = useCan();
  const [params, setParams] = useSearchParams();
  const tabs = [
    { value: 'users', label: 'Users', icon: IconUsers, show: can('users.manage') },
    { value: 'groups', label: 'Security groups', icon: IconUsersGroup, show: can('security.manage') || can('users.manage') },
    { value: 'roles', label: 'Roles & permissions', icon: IconShieldLock, show: can('security.manage') || can('users.manage') },
  ].filter((t) => t.show);
  const tab = tabs.some((t) => t.value === params.get('tab')) ? params.get('tab')! : tabs[0]?.value;

  return (
    <Stack p="lg" gap="md" className={classes.root}>
      <Stack gap={4}>
        <Breadcrumbs>
          <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
          <Text size="sm">Security</Text>
        </Breadcrumbs>
        <Title order={2}>Security</Title>
      </Stack>
      {tabs.length === 0 ? <Text c="dimmed">Your role doesn’t include managing users or security.</Text> : (
        <Tabs value={tab} onChange={(v) => setParams(v ? { tab: v } : {}, { replace: true })} keepMounted={false}>
          <Tabs.List mb="md">
            {tabs.map((t) => <Tabs.Tab key={t.value} value={t.value} leftSection={<t.icon size={16} />}>{t.label}</Tabs.Tab>)}
          </Tabs.List>
          <Tabs.Panel value="users"><UsersTab /></Tabs.Panel>
          <Tabs.Panel value="groups"><SecurityGroupsTab /></Tabs.Panel>
          <Tabs.Panel value="roles"><RolesTab /></Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
}
