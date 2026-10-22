import { Navigate, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
import { SimpleGrid, Stack, Text, Title, UnstyledButton } from '@mantine/core';
import { IconChartPie, IconFileAnalytics, IconMathFunction } from '@tabler/icons-react';
import { ReportsPage } from '../ReportsPage';
import { AnalyticsPage } from './AnalyticsPage';
import { ExpressionsPage } from './ExpressionsPage';
import { msg, useT } from '../../i18n';
import classes from './ReportsHub.module.css';

const TILES = [
  { to: 'reports', title: msg('app.reports.reports', 'Reports'), description: msg('app.reports.reports_desc', 'Run, download and schedule reports'), icon: IconFileAnalytics },
  { to: 'expressions', title: msg('app.reports.expressions', 'Expressions'), description: msg('app.reports.expressions_desc', 'Your own calculations, e.g. exceptions per 100 km'), icon: IconMathFunction },
  { to: 'analytics', title: msg('app.reports.analytics', 'Analytics'), description: msg('app.reports.analytics_desc', 'Charts, tables and figures about your fleet'), icon: IconChartPie },
];

function Hub() {
  const navigate = useNavigate();
  const tr = useT();
  const [params] = useSearchParams();
  if (params.get('run')) return <Navigate to={`reports?run=${params.get('run')}`} replace />;   // older links
  return (
    <Stack p="lg" gap="lg">
      <Title order={2}>{tr('app.nav.reports', 'Reports')}</Title>
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="lg" maw={980}>
        {TILES.map((t) => (
          <UnstyledButton key={t.to} className={classes.tile} onClick={() => navigate(t.to)}>
            <span className={classes.icon}><t.icon size={44} stroke={1.3} /></span>
            <Text fw={600} mt="sm">{tr(t.title)}</Text>
            <Text size="xs" c="dimmed" ta="center">{tr(t.description)}</Text>
          </UnstyledButton>
        ))}
      </SimpleGrid>
    </Stack>
  );
}

/** Reports: a hub of Reports, Expressions and Analytics. */
export function ReportsSection() {
  return (
    <Routes>
      <Route index element={<Hub />} />
      <Route path="reports" element={<ReportsPage />} />
      <Route path="expressions" element={<ExpressionsPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="*" element={<Navigate to="/reports" replace />} />
    </Routes>
  );
}
