import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Anchor, Box, Breadcrumbs, Button, ColorInput, FileButton, Group, Paper, Select, SimpleGrid, Stack, Text, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPhoto, IconTrash, IconUpload } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { api } from '../api/client';
import { useGroupTheme } from '../api/hooks';
import type { GroupTheme } from '../api/types';
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

export function UserGroupPage() {
  const qc = useQueryClient();
  const { data: theme } = useGroupTheme();
  const [form, setForm] = useState<GroupTheme | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (theme && !form) setForm(theme); }, [theme, form]);

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
      <Stack gap={4}>
        <Breadcrumbs>
          <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
          <Text size="sm">User Group</Text>
        </Breadcrumbs>
        <Group justify="space-between">
          <div>
            <Title order={2}>{form.name ?? 'User Group'}</Title>
            <Text size="sm" c="dimmed">Theme, logos and timezone for everyone in this user group.</Text>
          </div>
          <Button onClick={save} loading={saving}>Save changes</Button>
        </Group>
      </Stack>

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

      <Paper withBorder p="lg">
        <Text fw={650} mb="md">Timezone</Text>
        <Select searchable clearable maw={420} data={zones} value={form.timezone} placeholder="Each user's own device timezone"
                description="Used to show times across the platform, for report periods and as the default for scheduled reports."
                onChange={(v) => set({ timezone: v })} nothingFoundMessage="No matching timezone" />
      </Paper>
    </Stack>
  );
}
