import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Box, Button, Checkbox, ColorInput, FileButton, Group, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch,
  TagsInput, Text, TextInput, UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPhoto, IconTrash, IconUpload } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { api } from '../api/client';
import { useCan, useGroupTheme, useNotificationPrefs } from '../api/hooks';
import type { GroupTheme, NotificationPrefs, ThemeSettings } from '../api/types';
import { DEFAULT_MENU, FONTS, PRESETS, darkShadesOf, fontStack, isHex, isLight, loadFont } from '../theme';
import { ConfigHeader } from '../components/ConfigHeader';
import classes from './UserGroupPage.module.css';

const ACCEPT = 'image/png,image/jpeg,image/svg+xml';
const MAX_BYTES = 1024 * 1024;
const DEFAULT_PRIMARY = '#2468fb';
const DEFAULT_SECONDARY = '#f59e0b';
const DEFAULT_SURFACE = '#113356';
const RADII = { xs: 2, sm: 4, md: 8, lg: 16, xl: 24 } as const;

/** A small picture of the app in the (unsaved) look: menu, page, a card and a button. */
function ThemePreview({ primary, secondary, settings, name }: { primary: string; secondary: string; settings: ThemeSettings; name: string }) {
  const dark = (settings.color_scheme ?? 'dark') === 'dark';
  const shades = darkShadesOf(isHex(settings.surface) ? settings.surface : DEFAULT_SURFACE);
  const menu = isHex(settings.menu_bg) ? settings.menu_bg : dark ? shades[8] : DEFAULT_MENU;
  const menuInk = isLight(menu) ? '#1f2937' : '#ffffff';
  const r = RADII[settings.radius ?? 'md'];
  const page = dark ? shades[7] : isHex(settings.light_bg) ? settings.light_bg : '#ffffff';
  const card = dark ? shades[6] : '#ffffff';
  const ink = dark ? shades[0] : '#1f2937';
  const border = dark ? shades[4] : '#e5e7eb';
  return (
    <div className={classes.mock} style={{ fontFamily: fontStack(settings.font ?? 'Inter') }}>
      <div className={classes.mockMenu} style={{ background: menu, color: menuInk }}>
        <div className={classes.mockLogo}>{settings.brand_name || name}</div>
        {['Dashboard', 'Workspace', 'Reports', 'Inbox'].map((label, i) => (
          <div key={label} className={classes.mockItem}
               style={i === 0 ? { background: `color-mix(in srgb, ${primary} 30%, transparent)`, boxShadow: `inset 3px 0 0 ${secondary}` } : { opacity: 0.75 }}>
            {label}
          </div>
        ))}
      </div>
      <div className={classes.mockPage} style={{ background: page, color: ink }}>
        <div style={{ fontWeight: 650, fontSize: 16 }}>Where is my fleet</div>
        <div className={classes.mockCard} style={{ background: card, borderColor: border, borderRadius: r * 1.5 }}>
          <div style={{ fontSize: 11, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 0.4 }}>Current week</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>1 284 <span style={{ fontSize: 12, opacity: 0.7 }}>km</span></div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={classes.mockButton} style={{ background: primary, borderRadius: r, color: isLight(primary) ? '#1f2937' : '#fff' }}>Primary button</span>
          <span style={{ color: primary, fontSize: 12, fontWeight: 600 }}>A link</span>
        </div>
      </div>
    </div>
  );
}

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
  const settings: ThemeSettings = form.theme_settings ?? {};
  // Change white-label settings; unset values are dropped (back to the default)
  const setLook = (patch: Partial<ThemeSettings>) => setForm((f) => {
    if (!f) return f;
    const next = { ...(f.theme_settings ?? {}), ...patch } as Record<string, unknown>;
    Object.keys(next).forEach((k) => next[k] === undefined && delete next[k]);
    return { ...f, theme_settings: Object.keys(next).length ? next as ThemeSettings : null };
  });
  const save = async () => {
    setSaving(true);
    try {
      const saved = await api<GroupTheme>('/api/portal/theme', { method: 'PUT', json: {
        theme_primary: form.theme_primary ?? '', theme_accent: form.theme_accent ?? '',
        logo_data: form.logo_data ?? '', report_logo_data: form.report_logo_data ?? '', timezone: form.timezone ?? '',
        theme_settings: form.theme_settings ?? {},
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
                    description={mode === 'theme' ? `Your own look for everyone in ${form.name ?? 'this user group'}: colours, menu, font, logos and platform name.`
                      : `${form.name ?? 'Your user group'}: timezone, data retention and your notification preferences.`}>
        {canEdit && <Button onClick={save} loading={saving}>Save changes</Button>}
      </ConfigHeader>

      {mode === 'theme' && <>
      <Paper withBorder p="lg">
        <Text fw={650}>Ready-made looks</Text>
        <Text size="sm" c="dimmed" mb="md">Start from one of these, then adjust anything below.</Text>
        <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }} spacing="sm">
          {PRESETS.map((p) => (
            <UnstyledButton key={p.name} className={classes.preset} disabled={!canEdit}
                            onClick={() => {
                              // Colours and mode from the preset; keep the name, font and corners already chosen
                              set({ theme_primary: p.primary, theme_accent: p.secondary, theme_settings: null });
                              setLook({ ...p.settings, brand_name: settings.brand_name, font: settings.font, radius: settings.radius,
                                        lock_scheme: settings.lock_scheme });
                            }}>
              <div className={classes.presetSwatch}>
                <span style={{ flex: 2, background: p.settings.menu_bg ?? DEFAULT_MENU }} />
                <span style={{ flex: 3, background: p.settings.color_scheme === 'light' ? (p.settings.light_bg ?? '#fff') : (p.settings.surface ?? DEFAULT_SURFACE),
                               display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                  <span style={{ width: 14, height: 14, borderRadius: 4, background: p.primary }} />
                  <span style={{ width: 14, height: 14, borderRadius: 4, background: p.secondary }} />
                </span>
              </div>
              <Text size="xs" fw={600}>{p.name}</Text>
            </UnstyledButton>
          ))}
        </SimpleGrid>
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Paper withBorder p="lg">
          <Text fw={650} mb="md">Colours</Text>
          <Stack gap="sm">
            <ColorInput label="Primary colour" description="Buttons, links and highlights" format="hex" swatchesPerRow={8} disabled={!canEdit}
                        swatches={['#2468fb', '#0f766e', '#16a34a', '#7c3aed', '#db2777', '#dc2626', '#ea580c', '#0f172a']}
                        placeholder={DEFAULT_PRIMARY} value={form.theme_primary ?? ''} onChange={(v) => set({ theme_primary: v || null })} />
            <ColorInput label="Secondary colour" description="Accents, such as the selected menu item" format="hex" swatchesPerRow={8} disabled={!canEdit}
                        swatches={['#f59e0b', '#22c55e', '#06b6d4', '#a855f7', '#f43f5e', '#eab308', '#64748b', '#ffffff']}
                        placeholder={DEFAULT_SECONDARY} value={form.theme_accent ?? ''} onChange={(v) => set({ theme_accent: v || null })} />
            <ColorInput label="Menu colour" description="The side menu; its text turns dark or light to stay readable" format="hex" swatchesPerRow={8} disabled={!canEdit}
                        swatches={['#113356', '#0f172a', '#18181b', '#14532d', '#4c0519', '#083344', '#ffffff', '#f1f5f9']}
                        placeholder={`${DEFAULT_MENU} (default)`} value={settings.menu_bg ?? ''} onChange={(v) => setLook({ menu_bg: v || undefined })} />
            <ColorInput label="Dark mode background" description="Pages, panels and tables in dark mode are shades of this" format="hex" swatchesPerRow={8} disabled={!canEdit}
                        swatches={['#113356', '#0f172a', '#1e293b', '#27272a', '#1a2e22', '#2a1419', '#0c2a33', '#1f1f1f']}
                        placeholder={`${DEFAULT_SURFACE} (default)`} value={settings.surface ?? ''} onChange={(v) => setLook({ surface: v || undefined })} />
            <ColorInput label="Light mode background" description="The page behind cards in light mode" format="hex" swatchesPerRow={8} disabled={!canEdit}
                        swatches={['#ffffff', '#f8fafc', '#f5f7fb', '#f4f4f5', '#f7f7f2', '#fdf8f6', '#f0fdf4', '#eff6ff']}
                        placeholder="#ffffff (default)" value={settings.light_bg ?? ''} onChange={(v) => setLook({ light_bg: v || undefined })} />
          </Stack>
        </Paper>

        <Stack gap="lg">
          <Paper withBorder p="lg">
            <Text fw={650} mb="md">Look and feel</Text>
            <Stack gap="sm">
              <TextInput label="Platform name" description="Browser tab, sign-in page, and the menu when there's no logo" maxLength={60} disabled={!canEdit}
                         placeholder="ViSight Track" value={settings.brand_name ?? ''} onChange={(e) => setLook({ brand_name: e.currentTarget.value || undefined })} />
              <div>
                <Text size="sm" fw={500} mb={4}>Default mode</Text>
                <SegmentedControl size="xs" disabled={!canEdit} value={settings.color_scheme ?? 'dark'}
                                  onChange={(v) => setLook({ color_scheme: v as 'dark' | 'light' })}
                                  data={[{ value: 'dark', label: 'Dark' }, { value: 'light', label: 'Light' }]} />
                <Switch mt="xs" size="sm" disabled={!canEdit} label="Always use this mode (hide the light / dark switch)"
                        checked={!!settings.lock_scheme} onChange={(e) => setLook({ lock_scheme: e.currentTarget.checked || undefined })} />
              </div>
              <Select label="Font" allowDeselect={false} disabled={!canEdit} value={settings.font ?? 'Inter'}
                      data={FONTS.map((f) => ({ value: f, label: f === 'System' ? 'System (device default)' : f }))}
                      renderOption={({ option }) => <span style={{ fontFamily: fontStack(option.value) }}>{option.label}</span>}
                      onDropdownOpen={() => FONTS.forEach(loadFont)}
                      onChange={(v) => { loadFont(v ?? undefined); setLook({ font: v && v !== 'Inter' ? v : undefined }); }} />
              <div>
                <Text size="sm" fw={500} mb={4}>Corners</Text>
                <SegmentedControl size="xs" disabled={!canEdit} value={settings.radius ?? 'md'}
                                  onChange={(v) => setLook({ radius: v === 'md' ? undefined : v as ThemeSettings['radius'] })}
                                  data={[{ value: 'xs', label: 'Square' }, { value: 'sm', label: 'Slight' }, { value: 'md', label: 'Rounded' },
                                         { value: 'lg', label: 'More' }, { value: 'xl', label: 'Round' }]} />
              </div>
            </Stack>
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between" mb="sm">
              <Text fw={650}>Preview</Text>
              {(form.theme_primary || form.theme_accent || Object.keys(settings).length > 0) && canEdit &&
                <Button size="xs" variant="subtle" color="gray" onClick={() => set({ theme_primary: null, theme_accent: null, theme_settings: null })}>
                  Reset to default</Button>}
            </Group>
            <ThemePreview primary={form.theme_primary || DEFAULT_PRIMARY} secondary={form.theme_accent || DEFAULT_SECONDARY}
                          settings={settings} name={form.name ?? 'ViSight Track'} />
            <Text size="xs" c="dimmed" mt="xs">Saved changes apply to everyone in the user group the next time a page loads.</Text>
          </Paper>
        </Stack>
      </SimpleGrid>

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
