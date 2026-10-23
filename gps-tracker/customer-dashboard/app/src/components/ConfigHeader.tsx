import { Link } from 'react-router-dom';
import { Anchor, Breadcrumbs, Group, Stack, Text, Title } from '@mantine/core';

/** "Configuration / <section> / <page>" breadcrumbs (or another root, e.g. Reports), the title and optional actions. */
export function ConfigHeader({ section, title, description, children, root = '/configuration', rootLabel = 'Configuration' }: {
  section?: string; title: string; description?: string; children?: React.ReactNode; root?: string; rootLabel?: string;
}) {
  return (
    <Stack gap={4} mb="md">
      <Breadcrumbs>
        <Anchor component={Link} to={root} size="sm">{rootLabel}</Anchor>
        {section && section !== rootLabel && <Text size="sm" c="dimmed">{section}</Text>}
        <Text size="sm">{title}</Text>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={1} size="h2">{title}</Title>
          {description && <Text size="sm" c="dimmed">{description}</Text>}
        </div>
        {children && <Group gap="xs">{children}</Group>}
      </Group>
    </Stack>
  );
}
