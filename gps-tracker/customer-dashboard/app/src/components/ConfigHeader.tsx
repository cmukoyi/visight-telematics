import { Link } from 'react-router-dom';
import { Anchor, Breadcrumbs, Group, Stack, Text, Title } from '@mantine/core';

/** "Configuration / <section> / <page>" breadcrumbs, the page title and optional actions on the right. */
export function ConfigHeader({ section, title, description, children }: {
  section?: string; title: string; description?: string; children?: React.ReactNode;
}) {
  return (
    <Stack gap={4} mb="md">
      <Breadcrumbs>
        <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
        {section && <Text size="sm" c="dimmed">{section}</Text>}
        <Text size="sm">{title}</Text>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>{title}</Title>
          {description && <Text size="sm" c="dimmed">{description}</Text>}
        </div>
        {children && <Group gap="xs">{children}</Group>}
      </Group>
    </Stack>
  );
}
