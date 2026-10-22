import { useEffect, useState } from 'react';
import { Alert, Button, Stack, Text, TextInput, Textarea } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCopy, IconInfoCircle, IconLock } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCan, useMe, usePermissions, usePortalUsers } from '../api/hooks';
import type { Role } from '../api/types';
import { EditorShell, type EditorSection } from '../components/EditorShell';
import { CheckList, FeaturePicker } from '../components/FeaturePicker';

type Draft = { name: string; description: string; permissions: string[]; user_ids: string[] };
const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });

/** New / edit role: General, Features (what the role allows) and Users (who holds it). */
export function RoleEditor({ role: initial, opened, onClose }: { role: Role | null; opened: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const can = useCan();
  const { data: me } = useMe();
  const { data: allPermissions = [] } = usePermissions();
  // Configuration features are for User Group Administrators only — a role can't give them
  const permissions = allPermissions.filter((p) => !p.admin_only);
  const canUsers = can('users.manage');
  const { data: users = [] } = usePortalUsers(opened && (canUsers || can('users.view')));
  const [role, setRole] = useState<Role | null>(initial);
  const [draft, setDraft] = useState<Draft>({ name: '', description: '', permissions: [], user_ids: [] });
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!opened) return;
    setRole(initial);
    setDraft(initial ? { name: initial.name, description: initial.description ?? '', permissions: [...initial.permissions],
                         user_ids: initial.users.map((u) => u.id) }
      : { name: '', description: '', permissions: [], user_ids: [] });
  }, [opened, initial]);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const builtIn = !!role?.is_system;
  const mine = new Set(me?.access.permissions ?? []);
  const isAdmin = !!me?.access.is_admin;
  const locked = (key: string) => (isAdmin || mine.has(key) ? null : '(You don’t have this yourself, so you can’t give it.)');
  const meId = me?.portal_user.id;

  const duplicate = () => {
    if (!role) return;
    setRole(null);
    setDraft({ name: `${role.name} (copy)`, description: role.description ?? '',
               permissions: role.is_admin ? permissions.map((p) => p.key) : [...role.permissions], user_ids: [] });
  };
  const save = async (andNew = false) => {
    if (!draft.name.trim()) { notifications.show({ color: 'orange', message: 'Give the role a name' }); return; }
    setSaving(true);
    try {
      const body = { name: draft.name.trim(), description: draft.description.trim() || null, permissions: draft.permissions,
                     ...(canUsers ? { user_ids: draft.user_ids } : {}) };
      const saved = role
        ? await api<Role>(`/api/portal/roles/${role.id}`, { method: 'PUT', json: body })
        : await api<Role>('/api/portal/roles', { method: 'POST', json: body });
      ['roles', 'portal-users', 'me', 'audit'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      notifications.show({ color: 'green', message: `Role “${saved.name}” saved` });
      if (andNew) { setRole(null); setDraft({ name: '', description: '', permissions: [], user_ids: [] }); } else onClose();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  const sections: EditorSection[] = [
    { id: 'general', label: 'General', keywords: 'name description',
      content: (
        <Stack maw={640}>
          {builtIn && (
            <Alert variant="light" icon={<IconLock size={16} />} title="Built-in role">
              Its name and features are kept up to date by the platform. To change what it allows, duplicate it and edit the copy.
              <Button mt="sm" size="xs" variant="light" leftSection={<IconCopy size={14} />} onClick={duplicate}>Duplicate this role</Button>
            </Alert>
          )}
          <TextInput label="Name" withAsterisk disabled={builtIn} value={draft.name} onChange={(e) => set({ name: e.currentTarget.value })} data-autofocus />
          <Textarea label="Description" description="Shown when choosing roles for a user" autosize minRows={2} disabled={builtIn}
                    value={draft.description} onChange={(e) => set({ description: e.currentTarget.value })} />
        </Stack>
      ) },
    { id: 'features', label: 'Features', keywords: 'permissions access features',
      content: (
        <Stack>
          {role?.is_admin
            ? <Alert variant="light" icon={<IconInfoCircle size={16} />}>The User Group Administrator has every feature and sees every vehicle.</Alert>
            : <>
                <Text size="sm" c="dimmed">Tick what people with this role may do. Each feature says exactly what it allows.</Text>
                <Alert variant="light" color="gray" icon={<IconLock size={16} />} p="xs">
                  Configuration (users, roles, security, vehicle setup, notification rules, themes and the audit trail) is only for
                  User Group Administrators, so it can't be part of a role.
                </Alert>
              </>}
          <FeaturePicker permissions={permissions} value={role?.is_admin ? permissions.map((p) => p.key) : draft.permissions}
                         onChange={(v) => set({ permissions: v })} readOnly={builtIn} lockedReason={builtIn ? undefined : locked} />
        </Stack>
      ) },
    { id: 'users', label: 'Users', keywords: 'users members assigned',
      content: (
        <Stack maw={760}>
          <Text size="sm" c="dimmed">
            {canUsers ? 'Tick the users who hold this role. They keep their other roles.' : 'Users who hold this role. Changing who holds it needs “Add and edit users”.'}
          </Text>
          <CheckList value={draft.user_ids} onChange={(v) => set({ user_ids: v })} readOnly={!canUsers} height={420}
                     items={users.map((u) => ({
                       value: u.id, label: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email, description: u.email,
                       disabled: u.id === meId, extra: u.id === meId ? <Text span size="xs" c="dimmed">(you)</Text> : undefined,
                     }))} empty="No users." />
        </Stack>
      ) },
  ];

  return (
    <EditorShell opened={opened} onClose={onClose} title={role ? (builtIn ? role.name : 'Edit Role') : 'New Role'} sections={sections}
                 onSave={() => save(false)} onSaveAndNew={() => save(true)} saving={saving} />
  );
}
