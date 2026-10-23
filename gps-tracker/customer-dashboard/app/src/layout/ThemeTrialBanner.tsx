import { useState } from 'react';
import { Button, Group, Text, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPalette } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCan, useGroupTheme } from '../api/hooks';
import type { GroupTheme } from '../api/types';
import { setTrial, useThemeTrial } from '../utils/themeTrial';

/** Shown while a look is being tried in this browser: keep it for the whole user group, or go back. */
export function ThemeTrialBanner() {
  const trial = useThemeTrial();
  const { data: theme } = useGroupTheme();
  const can = useCan();
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  if (!trial) return null;

  const keep = async () => {
    if (!theme) return;
    setSaving(true);
    try {
      const saved = await api<GroupTheme>('/api/portal/theme', { method: 'PUT', json: {
        theme_primary: trial.theme_primary ?? '', theme_accent: trial.theme_accent ?? '',
        logo_data: theme.logo_data ?? '', report_logo_data: theme.report_logo_data ?? '', timezone: theme.timezone ?? '',
        theme_settings: trial.theme_settings ?? {},
        ...(theme.history_retention_days ? { history_retention_days: theme.history_retention_days } : {}),
      } });
      qc.setQueryData(['theme'], saved);
      setTrial(null);
      notifications.show({ color: 'green', message: `${trial.name} is now the look for everyone in ${saved.name ?? 'your user group'}` });
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Group className="vt-trial-banner" wrap="nowrap" gap="md" pl="md" pr={6} py={5}>
      <Group gap={8} wrap="nowrap">
        <IconPalette size={18} />
        <Tooltip label="Only you, in this browser, see this look. Everyone else still sees your saved theme." multiline w={240}>
          <Text size="sm" truncate>Trying <b>{trial.name}</b> in this browser only</Text>
        </Tooltip>
      </Group>
      <Group gap="xs">
        {can('theme.manage') && <Button size="compact-sm" loading={saving} onClick={keep}>Keep for everyone</Button>}
        <Button size="compact-sm" variant="default" onClick={() => setTrial(null)}>Stop trying</Button>
      </Group>
    </Group>
  );
}
