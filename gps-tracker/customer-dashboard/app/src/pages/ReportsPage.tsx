import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ActionIcon, Badge, Button, Drawer, Group, Menu, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Tabs, TagsInput,
  Text, TextInput, Title, Tooltip, UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconCalendarRepeat, IconDots, IconDownload, IconFileSpreadsheet, IconMailForward, IconPencil, IconPlayerPlay, IconPlus,
  IconReportAnalytics, IconSearch, IconStar, IconStarFilled, IconTrash,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api, download, qs } from '../api/client';
import { useCan, useCategories, useGroupTheme, useReports, useSchedules, useVehicles, type Range } from '../api/hooks';
import type { ReportDef, ReportResult, ReportSchedule } from '../api/types';
import { EditorShell, firstError } from '../components/EditorShell';
import { DataGrid } from '../components/DataGrid';
import { RangePicker, defaultRange } from '../components/RangePicker';
import { dateTime, vehicleName } from '../utils/format';
import classes from './ReportsPage.module.css';

const FAV_KEY = 'vt-report-favourites';
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Africa/Johannesburg';
/** Reports use the user group's timezone (Configuration → User Group), else the browser's. */
const useReportTz = () => useGroupTheme().data?.timezone || BROWSER_TZ;
const FREQ_LABEL = { daily: 'Daily', weekly: 'Weekly (Mondays)', monthly: 'Monthly (1st)' } as const;

function loadFavourites(): string[] {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]'); } catch { return []; }
}

// ── Run a report ──
function RunDrawer({ report, onClose, onSchedule }: { report: ReportDef | null; onClose: () => void; onSchedule: ((key: string) => void) | null }) {
  const tz = useReportTz();
  const { data: vehicles = [] } = useVehicles();
  const { data: categories = [] } = useCategories();
  const [range, setRange] = useState<Range>(defaultRange);
  const [imei, setImei] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [result, setResult] = useState<ReportResult | null>(null);
  const [loading, setLoading] = useState(false);

  const params = (format: string) => qs({ date_from: range.from.toISOString(), date_to: range.to.toISOString(), imei, category, format, tz });
  const run = async () => {
    if (!report) return;
    setLoading(true);
    try { setResult(await api<ReportResult>(`/api/portal/reports/${report.key}${params('json')}`)); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
    finally { setLoading(false); }
  };
  const save = async (format: 'xlsx' | 'csv') => {
    try { await download(`/api/portal/reports/${report!.key}${params(format)}`, `${report!.key}.${format}`); }
    catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  const close = () => { setResult(null); onClose(); };

  const cols: ColDef<(string | number | null)[]>[] = (result?.columns ?? []).map((c, i) => ({
    headerName: c, valueGetter: (p) => p.data?.[i], minWidth: 110, flex: 1,
    type: typeof result?.rows[0]?.[i] === 'number' ? 'numericColumn' : undefined,
  }));

  return (
    <Drawer opened={!!report} onClose={close} position="right" size="80%" title={<Title order={3}>{report?.title}</Title>}>
      <Text size="sm" c="dimmed" mb="md">{report?.description}</Text>
      <Group gap="xs" mb="md" wrap="wrap">
        <RangePicker value={range} onChange={setRange} />
        <Select w={210} placeholder="All vehicles" clearable searchable value={imei} onChange={setImei} aria-label="Vehicle"
                data={vehicles.map((v) => ({ value: v.imei, label: vehicleName(v) }))} />
        <Select w={180} placeholder="All groups" clearable value={category} onChange={setCategory} aria-label="Vehicle group"
                data={categories.map((c) => c.name)} />
        <Button leftSection={<IconPlayerPlay size={16} />} onClick={run} loading={loading}>Run report</Button>
        <Group gap="xs" ml="auto">
          <Button variant="default" leftSection={<IconFileSpreadsheet size={16} />} onClick={() => save('xlsx')}>Excel</Button>
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => save('csv')}>CSV</Button>
          {onSchedule && <Button variant="light" leftSection={<IconCalendarRepeat size={16} />} onClick={() => report && onSchedule(report.key)}>Schedule</Button>}
        </Group>
      </Group>
      <Paper withBorder className={classes.result}>
        {result
          ? <DataGrid rowData={result.rows} columnDefs={cols} />
          : <Stack align="center" justify="center" h="100%" gap={4}><IconReportAnalytics size={40} opacity={0.4} />
              <Text c="dimmed" size="sm">Choose a period and press Run report.</Text></Stack>}
      </Paper>
      {result && <Text size="xs" c="dimmed" mt={6}>{result.rows.length} rows</Text>}
    </Drawer>
  );
}

// ── Create / edit a schedule ──
type ScheduleForm = { report_key: string; name: string; frequency: string; file_format: string; recipients: string[];
  imei: string | null; category: string | null; send_hour: number; is_active: boolean };

function ScheduleModal({ editing, onClose }: { editing: ReportSchedule | { report_key: string } | null; onClose: () => void }) {
  const qc = useQueryClient();
  const tz = useReportTz();
  const { data: reports = [] } = useReports();
  const { data: vehicles = [] } = useVehicles();
  const { data: categories = [] } = useCategories();
  const existing = editing && 'id' in editing ? editing : null;
  const form = useForm<ScheduleForm>({
    initialValues: {
      report_key: editing?.report_key ?? 'trips', name: existing?.name ?? '', frequency: existing?.frequency ?? 'daily',
      file_format: existing?.file_format ?? 'xlsx', recipients: existing?.recipients ?? [], imei: existing?.imei ?? null,
      category: existing?.category ?? null, send_hour: existing?.send_hour ?? 6, is_active: existing?.is_active ?? true,
    },
    validate: {
      recipients: (v) => (v.length === 0 ? 'Add at least one email address'
        : v.some((e) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) ? 'One of the addresses is not valid' : v.length > 20 ? 'At most 20 recipients' : null),
    },
  });
  const submit = form.onSubmit(async (values) => {
    try {
      const json = { ...values, name: values.name || null, timezone: existing?.timezone ?? tz };
      if (existing) await api(`/api/portal/report-schedules/${existing.id}`, { method: 'PUT', json });
      else await api('/api/portal/report-schedules', { method: 'POST', json });
      qc.invalidateQueries({ queryKey: ['schedules'] });
      notifications.show({ color: 'green', message: existing ? 'Schedule saved' : 'Report scheduled' });
      onClose();
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  }, firstError);

  return (
    <EditorShell opened={!!editing} onClose={onClose} title={existing ? 'Edit Scheduled Report' : 'Schedule a Report'} onSave={() => submit()}
                 sections={[
      { id: 'general', label: 'General', keywords: 'report name active',
        content: (
          <Stack maw={620}>
            <Select label="Report" data={reports.map((r) => ({ value: r.key, label: r.title }))} allowDeselect={false} {...form.getInputProps('report_key')} />
            <TextInput label="Name" placeholder="Optional, used as the email subject" {...form.getInputProps('name')} />
            <Switch label="Active" {...form.getInputProps('is_active', { type: 'checkbox' })} />
          </Stack>
        ) },
      { id: 'vehicles', label: 'Vehicles', keywords: 'vehicle group',
        content: (
          <Stack maw={620}>
            <Select label="Vehicle" placeholder="All vehicles" clearable searchable data={vehicles.map((v) => ({ value: v.imei, label: vehicleName(v) }))} {...form.getInputProps('imei')} />
            <Select label="Vehicle group" placeholder="All groups" clearable data={categories.map((c) => c.name)} {...form.getInputProps('category')} />
          </Stack>
        ) },
      { id: 'schedule', label: 'Schedule', keywords: 'frequency daily weekly monthly hour time',
        content: (
          <Stack maw={620}>
            <Select label="Frequency" allowDeselect={false} data={Object.entries(FREQ_LABEL).map(([value, label]) => ({ value, label }))} {...form.getInputProps('frequency')} />
            <NumberInput label={`Send at (hour, ${existing?.timezone ?? tz})`} min={0} max={23} clampBehavior="strict" {...form.getInputProps('send_hour')} />
            <Text size="sm" c="dimmed">Daily reports cover the previous day, weekly reports the previous Monday–Sunday, monthly reports the previous month.</Text>
          </Stack>
        ) },
      { id: 'delivery', label: 'Delivery', keywords: 'recipients email format excel csv',
        content: (
          <Stack maw={620}>
            <TagsInput label="Recipients" withAsterisk description="Press Enter after each email address" placeholder="name@company.co.za"
                       splitChars={[',', ' ', ';']} clearable {...form.getInputProps('recipients')} />
            <Select label="File format" allowDeselect={false} data={[{ value: 'xlsx', label: 'Excel (.xlsx)' }, { value: 'csv', label: 'CSV' }]} {...form.getInputProps('file_format')} />
          </Stack>
        ) },
    ]} />
  );
}

function Scheduled({ onEdit }: { onEdit: (s: ReportSchedule | { report_key: string }) => void }) {
  const qc = useQueryClient();
  const { data: schedules = [], isFetching } = useSchedules();
  const sendNow = async (s: ReportSchedule) => {
    try {
      await api(`/api/portal/report-schedules/${s.id}/send-now`, { method: 'POST' });
      qc.invalidateQueries({ queryKey: ['schedules'] });
      notifications.show({ color: 'green', message: `Sent to ${s.recipients.length} recipient(s)` });
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  const remove = (s: ReportSchedule) => modals.openConfirmModal({
    title: 'Delete scheduled report?', children: <Text size="sm">{s.name || s.report_title} will no longer be emailed.</Text>,
    labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => { await api(`/api/portal/report-schedules/${s.id}`, { method: 'DELETE' }); qc.invalidateQueries({ queryKey: ['schedules'] }); },
  });

  const cols: ColDef<ReportSchedule>[] = [
    { headerName: 'Name', valueGetter: (p) => p.data?.name || p.data?.report_title, flex: 1.2 },
    { headerName: 'Report', field: 'report_title', flex: 1 },
    { headerName: 'Frequency', field: 'frequency', valueFormatter: (p) => FREQ_LABEL[p.value as keyof typeof FREQ_LABEL], width: 160 },
    { headerName: 'Recipients', valueGetter: (p) => p.data?.recipients.join(', '), flex: 1.4, tooltipValueGetter: (p) => p.data?.recipients.join('\n') },
    { headerName: 'Next send', field: 'next_run_at', valueFormatter: (p) => dateTime(p.value), width: 170 },
    { headerName: 'Last result', field: 'last_status', flex: 1,
      cellRenderer: (p: ICellRendererParams<ReportSchedule>) => p.data && (p.data.last_run_at
        ? <Text size="sm" c={p.data.last_status?.startsWith('sent') ? undefined : 'red'} truncate>{dateTime(p.data.last_run_at)} · {p.data.last_status}</Text>
        : <Text size="sm" c="dimmed">Not sent yet</Text>) },
    { headerName: 'Active', field: 'is_active', width: 100,
      cellRenderer: (p: ICellRendererParams<ReportSchedule>) => p.data && <Badge size="sm" variant="light" color={p.data.is_active ? 'green' : 'gray'}>{p.data.is_active ? 'Active' : 'Paused'}</Badge> },
    { headerName: '', width: 60, minWidth: 60, sortable: false, filter: false, pinned: 'right',
      cellRenderer: (p: ICellRendererParams<ReportSchedule>) => p.data && (
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label="Actions"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => onEdit(p.data!)}>Edit</Menu.Item>
            <Menu.Item leftSection={<IconMailForward size={14} />} onClick={() => sendNow(p.data!)}>Send now</Menu.Item>
            <Menu.Divider />
            <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => remove(p.data!)}>Delete</Menu.Item>
          </Menu.Dropdown>
        </Menu>) },
  ];

  return (
    <Paper withBorder className={classes.scheduled}>
      <DataGrid rowData={schedules} columnDefs={cols} loading={isFetching && !schedules.length} getRowId={(p) => p.data.id} tooltipShowDelay={300}
                overlayNoRowsTemplate='<span style="opacity:.7">No scheduled reports yet — open a report and press Schedule.</span>' />
    </Paper>
  );
}

export function ReportsPage() {
  const canSchedule = useCan()('reports.schedule');
  const { data: reports = [] } = useReports();
  const [tab, setTab] = useState<string | null>('reports');
  const [search, setSearch] = useState('');
  const [favourites, setFavourites] = useState<string[]>(loadFavourites);
  const [running, setRunning] = useState<ReportDef | null>(null);
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    const r = reports.find((x) => x.key === params.get('run'));
    if (r) { setRunning(r); setParams({}, { replace: true }); }
  }, [reports, params]); // eslint-disable-line react-hooks/exhaustive-deps
  const [scheduling, setScheduling] = useState<ReportSchedule | { report_key: string } | null>(null);

  const toggleFav = (key: string) => setFavourites((f) => {
    const next = f.includes(key) ? f.filter((k) => k !== key) : [...f, key];
    try { localStorage.setItem(FAV_KEY, JSON.stringify(next)); } catch { /* storage blocked */ }
    return next;
  });

  const grouped = useMemo(() => {
    const q = search.toLowerCase();
    const list = reports.filter((r) => !q || `${r.title} ${r.description}`.toLowerCase().includes(q));
    const out: [string, ReportDef[]][] = [];
    const favs = list.filter((r) => favourites.includes(r.key));
    if (favs.length) out.push(['Favourites', favs]);
    for (const cat of [...new Set(list.map((r) => r.category))]) out.push([cat, list.filter((r) => r.category === cat)]);
    return out;
  }, [reports, search, favourites]);

  return (
    <Stack p="lg" gap="md" className={classes.root}>
      <Group justify="space-between">
        <Title order={2}>Reports</Title>
        {canSchedule && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setScheduling({ report_key: 'trips' })}>Schedule a report</Button>}
      </Group>
      <Tabs value={tab} onChange={setTab} className={classes.tabs}>
        <Tabs.List mb="md">
          <Tabs.Tab value="reports" leftSection={<IconReportAnalytics size={16} />}>All reports</Tabs.Tab>
          {canSchedule && <Tabs.Tab value="scheduled" leftSection={<IconCalendarRepeat size={16} />}>Scheduled</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="reports">
          <TextInput placeholder="Search reports" leftSection={<IconSearch size={16} />} value={search} w={320} mb="md"
                     onChange={(e) => setSearch(e.currentTarget.value)} />
          {grouped.map(([cat, list]) => (
            <div key={cat}>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="xs" mt="md">{cat}</Text>
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
                {list.map((r) => (
                  <Paper key={`${cat}-${r.key}`} withBorder className={classes.card}>
                    <UnstyledButton className={classes.cardBody} onClick={() => setRunning(r)}>
                      <Text fw={650}>{r.title}</Text>
                      <Text size="sm" c="dimmed" mt={4} lineClamp={2}>{r.description}</Text>
                    </UnstyledButton>
                    <Group gap={2} className={classes.cardActions}>
                      {canSchedule && <Tooltip label="Schedule"><ActionIcon variant="subtle" color="gray" onClick={() => setScheduling({ report_key: r.key })} aria-label="Schedule"><IconCalendarRepeat size={16} /></ActionIcon></Tooltip>}
                      <Tooltip label={favourites.includes(r.key) ? 'Remove favourite' : 'Add to favourites'}>
                        <ActionIcon variant="subtle" color={favourites.includes(r.key) ? 'yellow' : 'gray'} onClick={() => toggleFav(r.key)} aria-label="Favourite">
                          {favourites.includes(r.key) ? <IconStarFilled size={16} /> : <IconStar size={16} />}
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Paper>
                ))}
              </SimpleGrid>
            </div>
          ))}
        </Tabs.Panel>

        <Tabs.Panel value="scheduled" className={classes.panel}>
          {canSchedule && <Scheduled onEdit={setScheduling} />}
        </Tabs.Panel>
      </Tabs>

      <RunDrawer report={running} onClose={() => setRunning(null)}
                 onSchedule={canSchedule ? (key) => { setRunning(null); setScheduling({ report_key: key }); } : null} />
      {scheduling && <ScheduleModal editing={scheduling} onClose={() => setScheduling(null)} />}
    </Stack>
  );
}
