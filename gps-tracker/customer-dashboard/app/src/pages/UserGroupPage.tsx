import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Box, Button, Checkbox, ColorInput, FileButton, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, TagsInput, Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPhoto, IconTrash, IconUpload } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { api } from '../api/client';
import { useCan, useGroupTheme, useNotificationPrefs } from '../api/hooks';
import type { GroupTheme, NotificationPrefs } from '../api/types';
import { ConfigHeader } from '../components/ConfigHeader';
import classes from './UserGroupPage.module.css';

const ACCEPT = 'image/png,image/jpeg,image/svg+xml';
const MAX_BYTES = 1024 * 1024;
const DEFAULT_PRIMARY = '#2468fb';
const DEFAULT_SECONDARY = '#f59e0b';

function readImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!ACCEPT.split(',').includes(file.type)) return reject(new Error('Use a PNG, JPEG or SVG image'));
    if (file.size > MAX_BYTES) return reject(new Error('The image is larger than 1 MB'));
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('Could not read the file'));
    reader.readAsDataURL(file);
  });
}

function LogoField({ label, hint, value, onChange, width, height }: {
  label: string; hint: string; value: string | null; onChange: (v: string | null) => void; width: number; height: number;
}) {
  const pick = async (file: File | null) => {
    if (!file) return;
    try { onChange(await readImage(file)); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  return (
    <Stack gap={6}>
      <Text fw={600} size="sm">{label}</Text>
      <Box className={classes.logoBox} style={{ width, height }}>
        {value ? <img src={value} alt={label} className={classes.logo} />
          : <Stack align="center" gap={4}><IconPhoto size={28} opacity={0.4} /><Text size="xs" c="dimmed">{width} × {height}</Text></Stack>}
      </Box>
      <Text size="xs" c="dimmed">{hint}</Text>
      <Group gap="xs">
        <FileButton onChange={pick} accept={ACCEPT}>
          {(props) => <Button {...props} size="xs" variant="light" leftSection={<IconUpload size={14} />}>{value ? 'Replace' : 'Upload'}</Button>}
        </FileButton>
        {value && <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} onClick={() => onChange(null)}>Remove</Button>}
      </Group>
    </Stack>
  );
}

/** My own alert preferences (email on/off, which alerts, extra addresses). */
function MyNotificationPrefs() {
  const qc = useQueryClient();
  const { data } = useNotificationPrefs();
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  useEffect(() => { if (data && !prefs) setPrefs(data); }, [data, prefs]);
  if (!prefs) return null;
  const set = (patch: Partial<NotificationPrefs>) => setPrefs((p) => p && { ...p, ...patch });
  const save = async () => {
    try {
      const saved = await api<NotificationPrefs>('/api/portal/notifications', { method: 'PUT', json: { ...prefs, notification_emails: prefs.notification_emails ?? [] } });
      qc.setQueryData(['notification-prefs'], saved);
      notifications.show({ color: 'green', message: 'Your notification preferences are saved' });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="md">
        <div><Text fw={650}>My notification preferences</Text><Text size="sm" c="dimmed">Which alerts you are emailed about (alerts always show in the Inbox).</Text></div>
        <Button size="xs" variant="light" onClick={save}>Save preferences</Button>
      </Group>
      <Stack gap="sm">
        <Switch label="Alerts on" checked={prefs.alerts_enabled} onChange={(e) => set({ alerts_enabled: e.currentTarget.checked })} />
        <Switch label="Email me alerts" checked={prefs.notify_via_email} disabled={!prefs.alerts_enabled}
                onChange={(e) => set({ notify_via_email: e.currentTarget.checked })} />
        <Group gap="xl" ml="xl">
          <Checkbox label="Place entry / exit" checked={prefs.notify_geofence_exit} disabled={!prefs.alerts_enabled || !prefs.notify_via_email}
                    onChange={(e) => set({ notify_geofence_exit: e.currentTarget.checked })} />
          <Checkbox label="Vehicle offline" checked={prefs.notify_offline} disabled={!prefs.alerts_enabled || !prefs.notify_via_email}
                    onChange={(e) => set({ notify_offline: e.currentTarget.checked })} />
          <Checkbox label="Low battery" checked={prefs.notify_battery_low} disabled={!prefs.alerts_enabled || !prefs.notify_via_email}
                    onChange={(e) => set({ notify_battery_low: e.currentTarget.checked })} />
        </Group>
        <TagsInput label="Also email" placeholder="Extra addresses — press Enter after each" splitChars={[',', ' ', ';']} clearable maw={560}
                   value={prefs.notification_emails ?? []} onChange={(v) => set({ notification_emails: v })} />
      </Stack>
    </Paper>
  );
}

export function UserGroupPage({ mode }: { mode: 'theme' | 'preferences' }) {
  const qc = useQueryClient();
  const canEdit = useCan()('settings.manage');
  const { data: theme } = useGroupTheme();
  const [form, setForm] = useState<GroupTheme | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (theme && !form) setForm(theme); }, [theme, form]);
  const { hash } = useLocation();
  useEffect(() => {
    if (form && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [form !== null, hash]); // eslint-disable-line react-hooks/exhaustive-deps

  const zones = useMemo(() => {
    let list: string[] = [];
    try { list = (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone'); } catch { /* old browser */ }
    if (!list.includes('UTC')) list = ['UTC', ...list];
    return list.map((z) => ({ value: z, label: `${z.replace(/_/g, ' ')} (UTC${dayjs().tz(z).format('Z')})` }));
  }, []);

  if (!form) return null;
  const set = (patch: Partial<GroupTheme>) => setForm((f) => f && { ...f, ...patch });
  const save = async () => {
    setSaving(true);
    try {
      const saved = await api<GroupTheme>('/api/portal/theme', { method: 'PUT', json: {
        theme_primary: form.theme_primary ?? '', theme_accent: form.theme_accent ?? '',
        logo_data: form.logo_data ?? '', report_logo_data: form.report_logo_data ?? '', timezone: form.timezone ?? '',
        ...(form.history_retention_days ? { history_retention_days: form.history_retention_days } : {}),
      } });
      qc.setQueryData(['theme'], saved);
      setForm(saved);
      notifications.show({ color: 'green', message: 'User group settings saved' });
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack p="lg" gap="lg" maw={1040}>
      <ConfigHeader section="Users" title={mode === 'theme' ? 'Custom Themes' : 'User Groups'}
                    description={mode === 'theme' ? `Colours and logos for everyone in ${form.name ?? 'this user group'}.`
                      : `${form.name ?? 'Your user group'}: timezone, data retention and your notification preferences.`}>
        {canEdit && <Button onClick={save} loading={saving}>Save changes</Button>}
      </ConfigHeader>

      {mode === 'theme' && <>
      <Paper withBorder p="lg">
        <Text fw={650} mb="md">Theme</Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
          <ColorInput label="Primary colour" description="Buttons, links and highlights" format="hex" swatchesPerRow={8}
                      swatches={['#2468fb', '#0f766e', '#16a34a', '#7c3aed', '#db2777', '#dc2626', '#ea580c', '#0f172a']}
                      placeholder={DEFAULT_PRIMARY} value={form.theme_primary ?? ''} onChange={(v) => set({ theme_primary: v || null })} />
          <ColorInput label="Secondary colour" description="Accents, such as the selected menu item" format="hex" swatchesPerRow={8}
                      swatches={['#f59e0b', '#22c55e', '#06b6d4', '#a855f7', '#f43f5e', '#eab308', '#64748b', '#ffffff']}
                      placeholder={DEFAULT_SECONDARY} value={form.theme_accent ?? ''} onChange={(v) => set({ theme_accent: v || null })} />
        </SimpleGrid>
        <Group gap="sm" mt="md">
          <Text size="sm" c="dimmed">Preview:</Text>
          <Button size="xs" color={form.theme_primary || DEFAULT_PRIMARY}>Primary button</Button>
          <Box className={classes.accentPreview} style={{ boxShadow: `inset 3px 0 0 ${form.theme_accent || DEFAULT_SECONDARY}` }}>
            Selected menu item
          </Box>
          {(form.theme_primary || form.theme_accent) &&
            <Button size="xs" variant="subtle" color="gray" onClick={() => set({ theme_primary: null, theme_accent: null })}>Reset to default</Button>}
        </Group>
      </Paper>

      <Paper withBorder p="lg">
        <Text fw={650} mb="md">Logos</Text>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl">
          <LogoField label="Platform logo" width={280} height={150} value={form.logo_data}
                     hint="Shown at the top of the menu. 280 × 150 px, PNG, JPEG or SVG, up to 1 MB. A transparent PNG or SVG works best on the dark menu."
                     onChange={(v) => set({ logo_data: v })} />
          <LogoField label="Report logo" width={220} height={60} value={form.report_logo_data}
                     hint="Printed at the top of Excel reports, including scheduled emails. PNG or JPEG (SVG can't be placed in Excel), up to 1 MB."
                     onChange={(v) => set({ report_logo_data: v })} />
        </SimpleGrid>
      </Paper>

      </>}

      {mode === 'preferences' && <>
      <Paper withBorder p="lg">
        <Text fw={650} mb={4}>{form.name}</Text>
        <Text size="sm" c="dimmed" mb="md">Settings for everyone in this user group{canEdit ? '' : ' (ask a User Group Administrator to change them)'}.</Text>
        <NumberInput label="Keep history for (days)" description="Positions and events older than this are removed" min={7} max={3650} maw={260}
                     disabled={!canEdit} value={form.history_retention_days ?? 365}
                     onChange={(v) => set({ history_retention_days: Number(v) || 365 })} />
      </Paper>
      <Paper withBorder p="lg" id="timezone">
        <Text fw={650} mb="md">Timezone</Text>
        <Select searchable clearable maw={420} data={zones} value={form.timezone} placeholder="Each user's own device timezone" disabled={!canEdit}
                description="Used to show times across the platform, for report periods and as the default for scheduled reports."
                onChange={(v) => set({ timezone: v })} nothingFoundMessage="No matching timezone" />
      </Paper>
      <MyNotificationPrefs />
      </>}
    </Stack>
  );
}
