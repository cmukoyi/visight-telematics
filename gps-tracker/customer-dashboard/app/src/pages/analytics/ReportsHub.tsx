import { Navigate, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
import { SimpleGrid, Stack, Text, Title, UnstyledButton } from '@mantine/core';
import { IconChartPie, IconFileAnalytics, IconMathFunction } from '@tabler/icons-react';
import { ReportsPage } from '../ReportsPage';
import { AnalyticsPage } from './AnalyticsPage';
import { ExpressionsPage } from './ExpressionsPage';
import classes from './ReportsHub.module.css';

const TILES = [
  { to: 'reports', title: 'Reports', description: 'Run, download and schedule reports', icon: IconFileAnalytics },
  { to: 'expressions', title: 'Expressions', description: 'Your own calculations, e.g. exceptions per 100 km', icon: IconMathFunction },
  { to: 'analytics', title: 'Analytics', description: 'Charts, tables and figures about your fleet', icon: IconChartPie },
];

function Hub() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  if (params.get('run')) return <Navigate to={`reports?run=${params.get('run')}`} replace />;   // older links
  return (
    <Stack p="lg" gap="lg">
      <Title order={2}>Reports</Title>
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="lg" maw={980}>
        {TILES.map((t) => (
          <UnstyledButton key={t.to} className={classes.tile} onClick={() => navigate(t.to)}>
            <span className={classes.icon}><t.icon size={44} stroke={1.3} /></span>
            <Text fw={600} mt="sm">{t.title}</Text>
            <Text size="xs" c="dimmed" ta="center">{t.description}</Text>
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
