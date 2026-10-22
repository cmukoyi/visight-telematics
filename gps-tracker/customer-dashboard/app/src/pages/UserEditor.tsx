import { useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Button, Group, Paper, Radio, Select, SimpleGrid, Stack, Switch, Text, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle, IconKey, IconShieldLock, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useGroupTheme, useLanguages, useMe, usePermissions, useRoles, useSecurityGroups } from '../api/hooks';
import type { PortalUserRow, Role } from '../api/types';
import { EditorShell, type EditorSection } from '../components/EditorShell';
import { CheckList, FeatureSummary } from '../components/FeaturePicker';
import { dateTime } from '../utils/format';

type Draft = { email: string; first_name: string; last_name: string; role_ids: string[]; security_group_id: string | null; is_active: boolean; language: string | null };
const EMPTY: Draft = { email: '', first_name: '', last_name: '', role_ids: [], security_group_id: null, is_active: true, language: null };
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });

/** Which roles the signed-in user may hand out (a non-admin only roles within their own permissions). */
export function useGrantable() {
  const { data: me } = useMe();
  return (role: Role) => {
    const a = me?.access;
    if (!a || a.is_admin) return true;
    return !role.is_admin && role.permissions.every((p) => a.permissions.includes(p));
  };
}

/** Add or edit a portal user: General, Login details, Roles (with what they allow), Security group, Delete. */
export function UserEditor({ user: initial, opened, onClose, onCreated }: {
  user: PortalUserRow | null;      // null = new user
  opened: boolean;
  onClose: () => void;
  onCreated: (email: string, tempPassword: string) => void;
}) {
  const qc = useQueryClient();
  const { data: roles = [] } = useRoles();
  const { data: groups = [] } = useSecurityGroups();
  const { data: allPermissions = [] } = usePermissions();
  const permissions = allPermissions.filter((p) => !p.admin_only);
  const { data: languages = [] } = useLanguages();
  const { data: groupTheme } = useGroupTheme();
  const groupLanguage = languages.find((l) => l.code === groupTheme?.default_language)?.name;
  const grantable = useGrantable();
  const [user, setUser] = useState<PortalUserRow | null>(initial);   // null after "Save and new"
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!opened) return;
    setTried(false);
    setUser(initial);
    setDraft(initial ? { email: initial.email, first_name: initial.first_name ?? '', last_name: initial.last_name ?? '',
                         role_ids: initial.role_ids?.length ? initial.role_ids : initial.role_id ? [initial.role_id] : [],
                         security_group_id: initial.security_group_id, is_active: initial.is_active, language: initial.language ?? null } : EMPTY);
  }, [opened, initial]);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const chosen = roles.filter((r) => draft.role_ids.includes(r.id));
  const admin = chosen.some((r) => r.is_admin);
  const granted = useMemo(() => [...new Set(chosen.flatMap((r) => r.permissions))], [chosen]);
  const allVehicles = admin || granted.includes('security.all_vehicles');
  const errors = {
    first_name: !draft.first_name.trim() ? 'Enter a first name' : null,
    email: !EMAIL.test(draft.email.trim()) ? 'Enter a valid email address' : null,
    roles: draft.role_ids.length === 0 ? 'Choose at least one role' : null,
    security: !draft.security_group_id && !allVehicles ? 'Choose a security group so the user can see vehicles' : null,
  };
  const valid = !Object.values(errors).some(Boolean);
  const held = new Set(user?.role_ids ?? []);

  const refresh = () => ['portal-users', 'roles', 'security-groups', 'me', 'audit'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const save = async (andNew = false) => {
    setTried(true);
    if (!valid) { notifications.show({ color: 'orange', message: Object.values(errors).find(Boolean) }); return; }
    setSaving(true);
    try {
      if (!user) {
        const res = await api<{ portal_user: PortalUserRow; temp_password: string }>('/api/portal/users', { method: 'POST', json: {
          email: draft.email.trim(), first_name: draft.first_name.trim(), last_name: draft.last_name.trim() || null,
          role_ids: draft.role_ids, security_group_id: draft.security_group_id, language: draft.language } });
        onCreated(res.portal_user.email, res.temp_password);
      } else {
        await api(`/api/portal/users/${user.id}`, { method: 'PATCH', json: {
          first_name: draft.first_name.trim(), last_name: draft.last_name.trim(), role_ids: draft.role_ids,
          security_group_id: draft.security_group_id, language: draft.language,
          ...(draft.is_active !== user.is_active ? { is_active: draft.is_active } : {}) } });
        notifications.show({ color: 'green', message: `${draft.email} saved` });
      }
      refresh();
      if (andNew) { setUser(null); setDraft(EMPTY); setTried(false); } else onClose();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };
  const resetPassword = () => user && modals.openConfirmModal({
    title: `Reset password for ${user.email}?`, children: <Text size="sm">Their current password stops working straight away.</Text>,
    labels: { confirm: 'Reset password', cancel: 'Cancel' }, zIndex: 400,
    onConfirm: async () => {
      try { const r = await api<{ temp_password: string }>(`/api/portal/users/${user.id}/reset-password`, { method: 'POST' }); onCreated(user.email, r.temp_password); refresh(); }
      catch (e) { fail(e); }
    },
  });
  const remove = () => user && modals.openConfirmModal({
    title: `Delete ${user.email}?`, zIndex: 400, confirmProps: { color: 'red' }, labels: { confirm: 'Delete user', cancel: 'Cancel' },
    children: <Text size="sm">They can no longer sign in and are removed from the user list. What they did stays in the audit trail.</Text>,
    onConfirm: async () => {
      try { await api(`/api/portal/users/${user.id}`, { method: 'DELETE' }); notifications.show({ color: 'green', message: `${user.email} deleted` }); refresh(); onClose(); }
      catch (e) { fail(e); }
    },
  });

  const sections: EditorSection[] = [
    { id: 'general', label: 'General', keywords: 'first name last name description language',
      content: (
        <Stack maw={620}>
          <TextInput label="First name" withAsterisk value={draft.first_name} onChange={(e) => set({ first_name: e.currentTarget.value })}
                     error={tried && errors.first_name} data-autofocus />
          <TextInput label="Last name" value={draft.last_name} onChange={(e) => set({ last_name: e.currentTarget.value })} />
          <Select label="Language" description="The language the platform is shown in for this user (add and translate languages in the admin portal)"
                  placeholder={`User group default${groupLanguage ? ` (${groupLanguage})` : ''}`} clearable searchable
                  data={languages.map((l) => ({ value: l.code, label: `${l.name} (${l.code})` }))}
                  value={draft.language} onChange={(v) => set({ language: v })} />
          {user && (
            <SimpleGrid cols={2}>
              <Text size="sm"><Text span c="dimmed">Created </Text>{dateTime(user.created_at) || '—'}</Text>
              <Text size="sm"><Text span c="dimmed">Last login </Text>{dateTime(user.last_login_at) || 'Never'}</Text>
            </SimpleGrid>
          )}
        </Stack>
      ) },
    { id: 'login', label: 'Login details', keywords: 'email username password active disabled',
      content: (
        <Stack maw={620}>
          <TextInput label="Email (username)" withAsterisk disabled={!!user} value={draft.email}
                     description={user ? 'The email address can’t be changed here.' : 'They sign in with this address. A temporary password is shown after saving.'}
                     onChange={(e) => set({ email: e.currentTarget.value })} error={tried && errors.email} />
          {user && <Switch label="Active (can sign in)" checked={draft.is_active} onChange={(e) => set({ is_active: e.currentTarget.checked })} />}
          {user && <Group><Button variant="light" leftSection={<IconKey size={16} />} onClick={resetPassword}>Reset password</Button></Group>}
        </Stack>
      ) },
    { id: 'roles', label: 'Roles', keywords: 'role permissions features access',
      content: (
        <Stack>
          <Text size="sm" c="dimmed">A user can hold several roles; they can do everything any of their roles allows. The list on the right shows exactly what that is.</Text>
          {tried && errors.roles && <Text size="sm" c="red">{errors.roles}</Text>}
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing={32}>
            <CheckList value={draft.role_ids} onChange={(v) => set({ role_ids: v })} selectAll={false} height={400}
                       items={roles.map((r) => ({
                         value: r.id, label: r.name, disabled: !grantable(r) && !held.has(r.id),
                         description: !grantable(r) && !held.has(r.id) ? 'You can’t give this role — it allows more than you can do.'
                           : r.description ?? `${r.permissions.length} features`,
                         extra: r.is_admin ? <Badge size="xs" color="red" variant="light">Admin</Badge>
                           : r.is_system ? <Badge size="xs" variant="default">Built-in</Badge> : null,
                       }))} />
            <FeatureSummary permissions={permissions} granted={granted} admin={admin} />
          </SimpleGrid>
        </Stack>
      ) },
    { id: 'security', label: 'Security group', keywords: 'security group vehicles visibility',
      content: (
        <Stack maw={760}>
          <Text size="sm" c="dimmed">
            {allVehicles ? 'This user’s roles let them see every vehicle, so a security group is optional.'
              : 'The user sees only the vehicles in the vehicle groups of this security group.'}
          </Text>
          {tried && errors.security && <Text size="sm" c="red">{errors.security}</Text>}
          {groups.length === 0 && <Alert color="orange" variant="light" icon={<IconAlertTriangle size={16} />}>Create a security group first (Configuration → Security).</Alert>}
          <Radio.Group value={draft.security_group_id ?? ''} onChange={(v) => set({ security_group_id: v || null })}>
            <Stack gap="xs">
              {allVehicles && (
                <Paper withBorder p="sm" radius="md"><Radio value="" label="No security group — sees every vehicle through their roles" /></Paper>
              )}
              {groups.map((g) => (
                <Paper key={g.id} withBorder p="sm" radius="md">
                  <Radio value={g.id} label={<Group gap={6}><IconShieldLock size={15} /><Text size="sm" fw={600}>{g.name}</Text></Group>}
                         description={<>
                           {g.description && <Text size="xs" c="dimmed">{g.description}</Text>}
                           <Text size="xs" c="dimmed">Vehicle groups: {g.vehicle_groups.length ? g.vehicle_groups.join(', ') : 'none yet'}</Text>
                         </>} />
                </Paper>
              ))}
            </Stack>
          </Radio.Group>
        </Stack>
      ) },
    ...(user ? [{ id: 'delete', label: 'Delete user', danger: true, keywords: 'remove delete',
      content: (
        <Stack maw={620} align="flex-start">
          <Text size="sm">Deleting {user.email} stops them signing in and removes them from the user list. To keep the account but stop access, untick Active under Login details instead.</Text>
          <Button color="red" variant="light" leftSection={<IconTrash size={16} />} onClick={remove}>Delete user</Button>
        </Stack>
      ) }] : []),
  ];

  return (
    <EditorShell opened={opened} onClose={onClose} title={user ? 'Edit User' : 'New User'} sections={sections}
                 onSave={() => save(false)} onSaveAndNew={() => save(true)} saving={saving} />
  );
}
