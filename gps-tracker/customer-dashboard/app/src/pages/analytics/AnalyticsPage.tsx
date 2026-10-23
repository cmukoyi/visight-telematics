import { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Button, Group, Loader, Menu, Modal, Paper, Select, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconArrowLeft, IconArrowRight, IconChartBar, IconCopy, IconDots, IconDownload, IconPencil, IconPlus, IconTable, IconTrash,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useAnalyticsPages, useAnalyticsQuery, useCan, useCategories, type Range } from '../../api/hooks';
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
  const head = [...(r.dimension ? [r.dimension_label] : []), ...r.columns.map((c) => (c.unit ? `${c.label} (${c.unit})` : c.label))];
  const lines = r.rows.map((row) => [...(r.dimension ? [esc(row.label)] : []), ...r.columns.map((c) => row.values[c.key] ?? '')].join(','));
  const blob = new Blob([[head.map(esc).join(','), ...lines].join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${title || 'visual'}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** One visual on the page: title, menu, and the chart (or its table). */
function VisualCard({ visual, range, category, manage, onEdit, onDuplicate, onMove, onDelete }: {
  visual: Visual; range: Range; category: string | null; manage: boolean;
  onEdit: () => void; onDuplicate: () => void; onMove: (d: number) => void; onDelete: () => void;
}) {
  const [asTable, setAsTable] = useState(false);
  const { data, isLoading, isError, error, isFetching } = useAnalyticsQuery(visual, range, category);
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
            {data && <Menu.Item leftSection={<IconDownload size={14} />} onClick={() => downloadCsv(visual.title, data)}>Download CSV</Menu.Item>}
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
        : showTable && data ? <ResultTable result={data} maxHeight={height} />
        : <VisualChart visual={visual} result={data} height={height} />}
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
  useEffect(() => { if (page) setPreset(page.date_preset); }, [page?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // A named period (saved as the page's default), or any two dates picked on the calendar
  const [custom, setCustom] = useState<Range | null>(null);
  const range = useMemo(() => (preset === 'custom' && custom ? custom : periodRange(preset)), [preset, custom]);
  const [editing, setEditing] = useState<Visual | 'new' | null>(null);
  const [naming, setNaming] = useState<{ mode: 'new' | 'rename'; name: string } | null>(null);

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
    children: <Text size="sm">Its {page.visuals.length} visuals are deleted with it. Expressions stay.</Text>,
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
            {manage && <Tooltip label="New page"><ActionIcon variant="default" radius="xl" size="lg" onClick={() => setNaming({ mode: 'new', name: '' })} aria-label="New page"><IconPlus size={16} /></ActionIcon></Tooltip>}
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
              <Select label="Vehicle group" w={260} placeholder="All vehicles" clearable data={categories.filter((c) => c.is_active).map((c) => c.name)}
                      value={category} onChange={setCategory} description=" " />
            </div>
          </Paper>
          {page && page.visuals.length === 0 && (
            <Paper withBorder p="xl" radius="lg"><Stack align="center" gap="xs">
              <Text c="dimmed">This page has no visuals yet.</Text>
              {manage && <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')}>Add visual</Button>}
            </Stack></Paper>
          )}
          {page && (
            <div className={classes.grid}>
              {page.visuals.map((v, i) => (
                <VisualCard key={v.id} visual={v} range={range} category={category} manage={manage}
                            onEdit={() => setEditing(v)} onMove={(d) => move(i, d)}
                            onDuplicate={() => setVisuals([...page.visuals.slice(0, i + 1), { ...v, id: Math.random().toString(36).slice(2, 14), title: `${v.title} (copy)` }, ...page.visuals.slice(i + 1)])}
                            onDelete={() => modals.openConfirmModal({
                              title: `Delete “${v.title || 'Untitled'}”?`, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
                              onConfirm: () => setVisuals(page.visuals.filter((x) => x.id !== v.id)),
                            })} />
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
