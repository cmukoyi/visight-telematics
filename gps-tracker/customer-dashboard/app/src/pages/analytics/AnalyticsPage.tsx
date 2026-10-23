import { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Anchor, Breadcrumbs, Button, Group, Loader, Menu, Modal, Paper, Select, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconArrowLeft, IconArrowRight, IconCalendarRepeat, IconChartBar, IconCopy, IconDots, IconDownload, IconFileSpreadsheet,
  IconFileTypePdf, IconLayoutDashboard, IconPencil, IconPlus, IconRestore, IconTable, IconTrash, IconTrashX,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, download } from '../../api/client';
import { analyticsBody, useAnalyticsPages, useAnalyticsQuery, useCan, useCategories, useVehicles, type Range } from '../../api/hooks';
import { vehicleName } from '../../utils/format';
import { ScheduleModal, type NewSchedule } from '../ReportsPage';
import type { AnalyticsPageDef, AnalyticsResult, Visual } from '../../api/types';
import dayjs from 'dayjs';
import { ConfigHeader } from '../../components/ConfigHeader';
import { RangePicker } from '../../components/RangePicker';
import { HEIGHTS, ResultTable, VisualChart } from '../../components/VisualChart';
import { PERIODS, periodLabel, periodRange } from '../../utils/periods';
import classes from './Analytics.module.css';
import { VisualEditor } from './VisualEditor';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });

function downloadCsv(title: string, r: AnalyticsResult) {
  const esc = (s: string) => `"${s.replace(/"/g, '""')}"`;
  const label = r.dimension !== '' && r.kind !== 'record';
  const info = r.info_columns ?? [];
  const head = [...(label ? [r.dimension_label] : []), ...info.map((c) => c.label), ...r.columns.map((c) => (c.unit ? `${c.label} (${c.unit})` : c.label))];
  const lines = r.rows.map((row) => [...(label ? [esc(row.label)] : []), ...info.map((c) => esc(row.info?.[c.key] ?? '')),
                                     ...r.columns.map((c) => row.values[c.key] ?? '')].join(','));
  const blob = new Blob([[head.map(esc).join(','), ...lines].join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${title || 'visual'}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

interface Template { key: string; name: string; date_preset: string; visuals: number; description: string }
type DeletedPage = AnalyticsPageDef & { deleted_at: string; purge_at: string };

/** The starting pages, to add again (with any expressions they need). */
function TemplatesModal({ opened, onClose, onAdded }: { opened: boolean; onClose: () => void; onAdded: (p: AnalyticsPageDef) => void }) {
  const { data: templates = [] } = useQuery({ queryKey: ['analytics-templates'], queryFn: () => api<Template[]>('/api/portal/analytics/templates'), enabled: opened });
  const [busy, setBusy] = useState<string | null>(null);
  const add = async (t: Template) => {
    setBusy(t.key);
    try { onAdded(await api<AnalyticsPageDef>('/api/portal/analytics/pages/from-template', { method: 'POST', json: { key: t.key } })); }
    catch (e) { fail(e); } finally { setBusy(null); }
  };
  return (
    <Modal opened={opened} onClose={onClose} title="New page from a template" size="lg">
      <Text size="sm" c="dimmed" mb="sm">The starting pages — add any of them again, as often as you like. Expressions they use that were deleted come back too.</Text>
      <Stack gap="xs">
        {templates.map((t) => (
          <Paper key={t.key} withBorder p="sm" radius="md">
            <Group justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                <IconLayoutDashboard size={22} opacity={0.6} />
                <div style={{ minWidth: 0 }}>
                  <Text fw={600}>{t.name}</Text>
                  <Text size="xs" c="dimmed">{t.description} · {t.visuals} visuals</Text>
                </div>
              </Group>
              <Button size="xs" variant="light" style={{ flexShrink: 0 }} loading={busy === t.key} onClick={() => add(t)}>Add page</Button>
            </Group>
          </Paper>
        ))}
      </Stack>
    </Modal>
  );
}

/** Pages deleted in the last 30 days: restore, or delete for good. */
function DeletedModal({ opened, onClose, onRestored }: { opened: boolean; onClose: () => void; onRestored: (p: AnalyticsPageDef) => void }) {
  const qc = useQueryClient();
  const { data: rows = [], isFetching } = useQuery({ queryKey: ['analytics-deleted'], queryFn: () => api<DeletedPage[]>('/api/portal/analytics/pages-deleted'), enabled: opened });
  const refresh = () => qc.invalidateQueries({ queryKey: ['analytics-deleted'] });
  const restore = async (p: DeletedPage) => {
    try {
      const r = await api<AnalyticsPageDef & { dropped_values: number }>(`/api/portal/analytics/pages/${p.id}/restore`, { method: 'POST' });
      refresh();
      notifications.show({ color: 'green', message: `${p.name} restored${r.dropped_values ? ` — ${r.dropped_values} value(s) used a deleted expression and were left out` : ''}` });
      onRestored(r);
    } catch (e) { fail(e); }
  };
  const purge = (p: DeletedPage) => modals.openConfirmModal({
    title: `Delete “${p.name}” for good?`, children: <Text size="sm">It can't be restored after this.</Text>,
    labels: { confirm: 'Delete for good', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => { try { await api(`/api/portal/analytics/pages/${p.id}/permanent`, { method: 'DELETE' }); refresh(); } catch (e) { fail(e); } },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Recently deleted pages" size="lg">
      <Text size="sm" c="dimmed" mb="sm">Deleted pages are kept for 30 days.</Text>
      {!rows.length && <Text size="sm" c="dimmed">{isFetching ? 'Loading…' : 'Nothing deleted recently.'}</Text>}
      <Stack gap="xs">
        {rows.map((p) => (
          <Paper key={p.id} withBorder p="sm" radius="md">
            <Group justify="space-between" wrap="nowrap">
              <div>
                <Text fw={600}>{p.name}</Text>
                <Text size="xs" c="dimmed">{p.visuals.length} visuals · deleted {dayjs(p.deleted_at).format('D MMM YYYY HH:mm')} · kept until {dayjs(p.purge_at).format('D MMM')}</Text>
              </div>
              <Group gap={6} wrap="nowrap">
                <Button size="xs" variant="light" leftSection={<IconRestore size={14} />} onClick={() => restore(p)}>Restore</Button>
                <Tooltip label="Delete for good"><ActionIcon variant="subtle" color="red" onClick={() => purge(p)} aria-label="Delete for good"><IconTrashX size={16} /></ActionIcon></Tooltip>
              </Group>
            </Group>
          </Paper>
        ))}
      </Stack>
    </Modal>
  );
}

/** One visual on the page: title, menu, and the chart (or its table). Clicking a vehicle group or vehicle drills into it. */
function VisualCard({ visual, range, category, imei, manage, onEdit, onDuplicate, onMove, onDelete, onDrill, onSchedule }: {
  visual: Visual; range: Range; category: string | null; imei: string | null; manage: boolean;
  onEdit: () => void; onDuplicate: () => void; onMove: (d: number) => void; onDelete: () => void;
  onDrill: (dimension: string, key: string, label: string) => void; onSchedule: (() => void) | null;
}) {
  const [asTable, setAsTable] = useState(false);
  const { data, isLoading, isError, error, isFetching } = useAnalyticsQuery(visual, range, category, imei);
  const drillable = visual.dimension === 'vehicle_group' || visual.dimension === 'vehicle';
  const rowClick = drillable ? (r: { key: string; label: string }) => onDrill(visual.dimension, r.key, r.label) : undefined;
  const save = (format: 'xlsx' | 'pdf' | 'csv') =>
    download('/api/portal/analytics/export', `${visual.title || 'analytics'}.${format}`,
             { ...analyticsBody(visual, range, category, imei), title: visual.title || 'Analytics', format }).catch(fail);
  const height = HEIGHTS[visual.height];
  const showTable = asTable && visual.type !== 'kpi' && visual.type !== 'text' && visual.type !== 'table';
  return (
    <Paper withBorder radius="lg" p="md" className={classes.card} style={{ gridColumn: `span ${visual.width}` }}>
      <div className={classes.cardHead}>
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text fw={650} truncate>{visual.title || 'Untitled'}</Text>
          {isFetching && !isLoading && <Loader size={12} />}
        </Group>
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" size="sm" aria-label="Visual options"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            {visual.type !== 'kpi' && visual.type !== 'text' && visual.type !== 'table' && (
              <Menu.Item leftSection={showTable ? <IconChartBar size={14} /> : <IconTable size={14} />} onClick={() => setAsTable(!asTable)}>
                {showTable ? 'View as chart' : 'View as table'}</Menu.Item>
            )}
            {data && visual.type !== 'text' && <>
              <Menu.Label>Download</Menu.Label>
              <Menu.Item leftSection={<IconFileSpreadsheet size={14} />} onClick={() => save('xlsx')}>Excel (.xlsx)</Menu.Item>
              <Menu.Item leftSection={<IconFileTypePdf size={14} />} onClick={() => save('pdf')}>PDF</Menu.Item>
              <Menu.Item leftSection={<IconDownload size={14} />} onClick={() => downloadCsv(visual.title, data)}>CSV</Menu.Item>
            </>}
            {onSchedule && visual.type !== 'text' && (
              <Menu.Item leftSection={<IconCalendarRepeat size={14} />} onClick={onSchedule}>Schedule by email…</Menu.Item>
            )}
            {manage && <>
              <Menu.Divider />
              <Menu.Item leftSection={<IconPencil size={14} />} onClick={onEdit}>Edit</Menu.Item>
              <Menu.Item leftSection={<IconCopy size={14} />} onClick={onDuplicate}>Duplicate</Menu.Item>
              <Menu.Item leftSection={<IconArrowLeft size={14} />} onClick={() => onMove(-1)}>Move earlier</Menu.Item>
              <Menu.Item leftSection={<IconArrowRight size={14} />} onClick={() => onMove(1)}>Move later</Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={onDelete}>Delete</Menu.Item>
            </>}
          </Menu.Dropdown>
        </Menu>
      </div>
      {isError ? <Text size="sm" c="red">{(error as Error).message}</Text>
        : isLoading && visual.type !== 'text' ? <Group h={height} justify="center"><Loader size="sm" /></Group>
        : showTable && data ? <ResultTable result={data} maxHeight={height} onRowClick={rowClick} />
        : <VisualChart visual={visual} result={data} height={height} onRowClick={rowClick} />}
    </Paper>
  );
}

/** Reports → Analytics: pages of charts, tables and figures over the fleet's data. */
export function AnalyticsPage() {
  const qc = useQueryClient();
  const manage = useCan()('analytics.manage');
  const { data: pages = [], isLoading } = useAnalyticsPages();
  const { data: categories = [] } = useCategories();
  const [pageId, setPageId] = useState<string | null>(null);
  const page = pages.find((p) => p.id === pageId) ?? pages[0];
  const [preset, setPreset] = useState<string>('this_month');
  const [category, setCategory] = useState<string | null>(null);
  const [imei, setImei] = useState<string | null>(null);
  const { data: vehicles = [] } = useVehicles();
  const canSchedule = useCan()('reports.schedule');
  const [scheduling, setScheduling] = useState<NewSchedule | null>(null);
  useEffect(() => { if (page) setPreset(page.date_preset); }, [page?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // Drill down: a vehicle group, then a vehicle — the whole page follows
  const drill = (dimension: string, key: string) => {
    if (dimension === 'vehicle_group') { setCategory(key === 'No group' ? null : key); setImei(null); }
    if (dimension === 'vehicle') setImei(key);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const vehicleOptions = vehicles.filter((v) => !category || v.category_name === category).map((v) => ({ value: v.imei, label: vehicleName(v) }));
  // A named period (saved as the page's default), or any two dates picked on the calendar
  const [custom, setCustom] = useState<Range | null>(null);
  const range = useMemo(() => (preset === 'custom' && custom ? custom : periodRange(preset)), [preset, custom]);
  const [editing, setEditing] = useState<Visual | 'new' | null>(null);
  const [naming, setNaming] = useState<{ mode: 'new' | 'rename'; name: string } | null>(null);
  const [dialog, setDialog] = useState<'templates' | 'deleted' | null>(null);
  const opened = (p: AnalyticsPageDef) => {
    qc.invalidateQueries({ queryKey: ['analytics-pages'] });
    qc.invalidateQueries({ queryKey: ['analytics-expressions'] });
    setPageId(p.id);
    setDialog(null);
  };

  const savePage = async (p: AnalyticsPageDef) => {
    qc.setQueryData<AnalyticsPageDef[]>(['analytics-pages'], (old) => old?.map((x) => (x.id === p.id ? p : x)));
    try { await api(`/api/portal/analytics/pages/${p.id}`, { method: 'PUT', json: p }); }
    catch (e) { fail(e); }
    qc.invalidateQueries({ queryKey: ['analytics-pages'] });
    qc.invalidateQueries({ queryKey: ['analytics-expressions'] });
  };
  const setVisuals = (visuals: Visual[]) => page && savePage({ ...page, visuals });
  const saveVisual = (v: Visual) => {
    if (!page) return;
    const exists = page.visuals.some((x) => x.id === v.id);
    setVisuals(exists ? page.visuals.map((x) => (x.id === v.id ? v : x)) : [...page.visuals, v]);
    setEditing(null);
  };
  const move = (i: number, d: number) => {
    if (!page) return;
    const list = [...page.visuals];
    const j = i + d;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    setVisuals(list);
  };
  const submitName = async () => {
    if (!naming?.name.trim()) return;
    try {
      if (naming.mode === 'new') {
        const p = await api<AnalyticsPageDef>('/api/portal/analytics/pages', { method: 'POST', json: { name: naming.name.trim(), date_preset: preset, visuals: [] } });
        await qc.invalidateQueries({ queryKey: ['analytics-pages'] });
        setPageId(p.id);
      } else if (page) await savePage({ ...page, name: naming.name.trim() });
      setNaming(null);
    } catch (e) { fail(e); }
  };
  const duplicatePage = async () => {
    if (!page) return;
    try {
      const p = await api<AnalyticsPageDef>('/api/portal/analytics/pages', { method: 'POST', json: {
        name: `${page.name} (copy)`, date_preset: page.date_preset,
        visuals: page.visuals.map((v) => ({ ...v, id: Math.random().toString(36).slice(2, 14) })) } });
      await qc.invalidateQueries({ queryKey: ['analytics-pages'] });
      setPageId(p.id);
    } catch (e) { fail(e); }
  };
  const deletePage = () => page && modals.openConfirmModal({
    title: `Delete page “${page.name}”?`, labels: { confirm: 'Delete page', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">It goes to Recently deleted (+ → Recently deleted…), where you can restore it for 30 days.</Text>,
    onConfirm: async () => { try { await api(`/api/portal/analytics/pages/${page.id}`, { method: 'DELETE' }); setPageId(null); qc.invalidateQueries({ queryKey: ['analytics-pages'] }); } catch (e) { fail(e); } },
  });

  return (
    <Stack p="lg" gap="md" pb={100}>
      <ConfigHeader section="Reports" title="Analytics" description="Charts, tables and figures from your fleet's trips, events and alerts." root="/reports" rootLabel="Reports" />
      {isLoading ? <Loader /> : (
        <>
          <div className={classes.pills}>
            {pages.map((p) => (
              <UnstyledButton key={p.id} className={classes.pill} data-active={page?.id === p.id || undefined} onClick={() => setPageId(p.id)}>{p.name}</UnstyledButton>
            ))}
            {manage && (
              <Menu position="bottom-start" withinPortal>
                <Menu.Target><Tooltip label="New page"><ActionIcon variant="default" radius="xl" size="lg" aria-label="New page"><IconPlus size={16} /></ActionIcon></Tooltip></Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item leftSection={<IconPlus size={14} />} onClick={() => setNaming({ mode: 'new', name: '' })}>Blank page</Menu.Item>
                  <Menu.Item leftSection={<IconLayoutDashboard size={14} />} onClick={() => setDialog('templates')}>From a template…</Menu.Item>
                  <Menu.Divider />
                  <Menu.Item leftSection={<IconRestore size={14} />} onClick={() => setDialog('deleted')}>Recently deleted…</Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
            {manage && page && (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target><ActionIcon variant="subtle" color="gray" radius="xl" size="lg" aria-label="Page options" ml="auto"><IconDots size={18} /></ActionIcon></Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => setNaming({ mode: 'rename', name: page.name })}>Rename page</Menu.Item>
                  <Menu.Item leftSection={<IconCopy size={14} />} onClick={duplicatePage}>Duplicate page</Menu.Item>
                  {preset !== 'custom' && (
                    <Menu.Item onClick={() => savePage({ ...page, date_preset: preset })}>Make “{PERIODS.find((p) => p.value === preset)?.label}” this page’s default period</Menu.Item>
                  )}
                  <Menu.Divider />
                  <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={deletePage}>Delete page</Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </div>
          <Paper withBorder radius="lg" p="md">
            <div className={classes.filters}>
              <Select label="Date range" w={260} allowDeselect={false} value={preset}
                      data={[...PERIODS, { value: 'custom', label: 'Custom range…' }]}
                      onChange={(v) => {
                        if (v === 'custom' && !custom) setCustom({ from: range.from, to: dayjs(range.to).subtract(1, 'second').toDate() });
                        setPreset(v ?? 'this_month');
                      }}
                      description={preset === 'custom' ? 'Pick the dates on the right' : periodLabel(preset, range)} />
              {preset === 'custom' && custom && (
                <Stack gap={4} justify="flex-end">
                  <Text size="sm" fw={500}>From – to</Text>
                  <RangePicker value={custom} onChange={setCustom} />
                  <Text size="xs" c="dimmed">&nbsp;</Text>
                </Stack>
              )}
              <Select label="Vehicle group" w={240} placeholder="All vehicles" clearable data={categories.filter((c) => c.is_active).map((c) => c.name)}
                      value={category} onChange={(c) => { setCategory(c); setImei(null); }} description="Or click a group in a chart" />
              <Select label="Vehicle" w={240} placeholder="All vehicles" clearable searchable data={vehicleOptions}
                      value={imei} onChange={setImei} description="Or click a vehicle in a chart" />
            </div>
            {(category || imei) && (
              <Breadcrumbs mt="sm" separator="›">
                <Anchor size="sm" onClick={() => { setCategory(null); setImei(null); }}>All vehicles</Anchor>
                {category && (imei ? <Anchor size="sm" onClick={() => setImei(null)}>{category}</Anchor> : <Text size="sm" fw={600}>{category}</Text>)}
                {imei && <Text size="sm" fw={600}>{vehicleOptions.find((v) => v.value === imei)?.label ?? vehicles.find((v) => v.imei === imei)?.description ?? imei}</Text>}
              </Breadcrumbs>
            )}
          </Paper>
          {!page && (
            <Paper withBorder p="xl" radius="lg"><Stack align="center" gap="xs">
              <Text c="dimmed">There are no Analytics pages.</Text>
              {manage && <Group>
                <Button leftSection={<IconLayoutDashboard size={16} />} onClick={() => setDialog('templates')}>Add a starting page</Button>
                <Button variant="default" leftSection={<IconRestore size={16} />} onClick={() => setDialog('deleted')}>Recently deleted</Button>
              </Group>}
            </Stack></Paper>
          )}
          {page && page.visuals.length === 0 && (
            <Paper withBorder p="xl" radius="lg"><Stack align="center" gap="xs">
              <Text c="dimmed">This page has no visuals yet.</Text>
              {manage && <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')}>Add visual</Button>}
            </Stack></Paper>
          )}
          {page && (
            <div className={classes.grid}>
              {page.visuals.map((v, i) => (
                <VisualCard key={v.id} visual={v} range={range} category={category} imei={imei} manage={manage} onDrill={drill}
                            onSchedule={canSchedule ? () => setScheduling({ report_key: 'analytics', page_id: page.id, visual_id: v.id,
                                                                            report_title: `${page.name} · ${v.title || 'Chart'}` }) : null}
                            onEdit={() => setEditing(v)} onMove={(d) => move(i, d)}
                            onDuplicate={() => setVisuals([...page.visuals.slice(0, i + 1), { ...v, id: Math.random().toString(36).slice(2, 14), title: `${v.title} (copy)` }, ...page.visuals.slice(i + 1)])}
                            onDelete={() => {
                              const before = page.visuals;
                              setVisuals(before.filter((x) => x.id !== v.id));
                              const id = `undo-${v.id}`;
                              notifications.show({ id, autoClose: 8000, message: (
                                <Group justify="space-between" wrap="nowrap">
                                  <Text size="sm">“{v.title || 'Untitled'}” deleted</Text>
                                  <Button size="compact-xs" variant="light" onClick={() => { setVisuals(before); notifications.hide(id); }}>Undo</Button>
                                </Group>) });
                            }} />
              ))}
            </div>
          )}
          {manage && page && (
            <Tooltip label="Add visual" position="left">
              <ActionIcon className={classes.fab} size={56} radius="xl" onClick={() => setEditing('new')} aria-label="Add visual"><IconPlus size={26} /></ActionIcon>
            </Tooltip>
          )}
        </>
      )}
      <TemplatesModal opened={dialog === 'templates'} onClose={() => setDialog(null)} onAdded={opened} />
      <DeletedModal opened={dialog === 'deleted'} onClose={() => setDialog(null)} onRestored={opened} />
      {scheduling && <ScheduleModal key={scheduling.visual_id} editing={scheduling} onClose={() => setScheduling(null)} />}
      <VisualEditor opened={!!editing} visual={editing === 'new' ? null : editing} range={range} category={category}
                    onSave={saveVisual} onClose={() => setEditing(null)} />
      <Modal opened={!!naming} onClose={() => setNaming(null)} title={naming?.mode === 'new' ? 'New page' : 'Rename page'}>
        <Stack>
          <TextInput label="Page name" data-autofocus value={naming?.name ?? ''} onChange={(e) => { const v = e.currentTarget.value; setNaming((n) => n && { ...n, name: v }); }}
                     onKeyDown={(e) => e.key === 'Enter' && submitName()} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setNaming(null)}>Cancel</Button><Button onClick={submitName}>Save</Button></Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
