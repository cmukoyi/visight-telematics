import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Button, Group, Modal, MultiSelect, NumberInput, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Switch,
  Tabs, Text, TextInput, Textarea, Tooltip, UnstyledButton,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import {
  IconArrowDown, IconArrowUp, IconChartArea, IconChartBar, IconChartDonut, IconChartLine, IconChartPie, IconNumber123, IconStack2,
  IconTable, IconTypography, IconX,
} from '@tabler/icons-react';
import { useAnalyticsCatalog, useAnalyticsQuery, useCategories, useVehicles, type Range } from '../../api/hooks';
import type { Visual, VisualType } from '../../api/types';
import { HEIGHTS, VisualChart } from '../../components/VisualChart';
import { vehicleName } from '../../utils/format';
import classes from './Analytics.module.css';

export const VISUAL_TYPES: { type: VisualType; label: string; icon: typeof IconTable; hint: string; rotate?: boolean }[] = [
  { type: 'kpi', label: 'Number', icon: IconNumber123, hint: 'One headline figure' },
  { type: 'table', label: 'Table', icon: IconTable, hint: 'Rows and columns' },
  { type: 'column', label: 'Column chart', icon: IconChartBar, hint: 'Compare values, or show them over time' },
  { type: 'bar', label: 'Bar chart', icon: IconChartBar, hint: 'Compare and rank many vehicles or drivers', rotate: true },
  { type: 'stacked', label: 'Stacked columns', icon: IconStack2, hint: 'Parts of a total, e.g. exception types' },
  { type: 'line', label: 'Line chart', icon: IconChartLine, hint: 'A trend over days, weeks or months' },
  { type: 'area', label: 'Area chart', icon: IconChartArea, hint: 'A trend, with its volume' },
  { type: 'pie', label: 'Pie chart', icon: IconChartPie, hint: 'Share of a whole (up to 5 parts + Other)' },
  { type: 'donut', label: 'Donut chart', icon: IconChartDonut, hint: 'Share of a whole (up to 5 parts + Other)' },
  { type: 'text', label: 'Text', icon: IconTypography, hint: 'A heading or note' },
];
const WIDTHS = [{ value: '3', label: '¼' }, { value: '4', label: '⅓' }, { value: '6', label: '½' }, { value: '8', label: '⅔' }, { value: '12', label: 'Full' }];

export const newVisual = (): Visual => ({
  id: Math.random().toString(36).slice(2, 14), type: 'column', title: '', dimension: 'day', measures: [], width: 6, height: 'm',
  descending: true, show_values: false,
});

/** Add / edit one visual: type, fields (breakdown + values), filters and format, with a live preview. */
export function VisualEditor({ visual, opened, range, category, onSave, onClose }: {
  visual: Visual | null; opened: boolean; range: Range; category: string | null;
  onSave: (v: Visual) => void; onClose: () => void;
}) {
  const mobile = useMediaQuery('(max-width: 48em)');
  const { data: catalog } = useAnalyticsCatalog();
  const { data: categories = [] } = useCategories();
  const { data: vehicles = [] } = useVehicles();
  const [v, setV] = useState<Visual>(newVisual);
  useEffect(() => { if (opened) setV(visual ? { ...visual } : newVisual()); }, [opened, visual]);
  const set = (patch: Partial<Visual>) => setV((x) => ({ ...x, ...patch }));
  const preview = useAnalyticsQuery(opened ? v : null, range, category);

  // Values to pick: measures by category, then the group's expressions
  const valueOptions = useMemo(() => {
    if (!catalog) return [];
    const by = new Map<string, { value: string; label: string }[]>();
    catalog.measures.forEach((m) => by.set(m.category, [...(by.get(m.category) ?? []), { value: m.key, label: m.unit ? `${m.label} (${m.unit})` : m.label }]));
    const out = [...by].map(([group, items]) => ({ group, items }));
    if (catalog.expressions.length) out.push({ group: 'Expressions', items: catalog.expressions.map((e) => ({ value: e.key, label: `ƒ ${e.name}` })) });
    return out;
  }, [catalog]);
  const labelOf = (key: string) => valueOptions.flatMap((g) => g.items).find((i) => i.value === key)?.label ?? key;
  const move = (i: number, d: number) => {
    const m = [...v.measures];
    const j = i + d;
    if (j < 0 || j >= m.length) return;
    [m[i], m[j]] = [m[j], m[i]];
    set({ measures: m });
  };
  const single = v.type === 'pie' || v.type === 'donut';
  const valid = v.type === 'text' ? !!(v.title || v.text) : v.measures.length > 0;
  const height = HEIGHTS[v.height];

  return (
    <Modal opened={opened} onClose={onClose} size="min(1400px, 96vw)" padding={0} withCloseButton={false} fullScreen={mobile}
           classNames={{ content: classes.editorContent, body: classes.editorBody }}>
      <div className={classes.editor}>
        <aside className={classes.editorSide}>
          <Text fw={650} mb="sm">Visualization</Text>
          <SimpleGrid cols={5} spacing={6} mb="md">
            {VISUAL_TYPES.map((t) => (
              <Tooltip key={t.type} label={<><b>{t.label}</b><br />{t.hint}</>} withinPortal multiline w={200}>
                <UnstyledButton className={classes.typeBtn} data-active={v.type === t.type || undefined} aria-label={t.label}
                                onClick={() => set({ type: t.type, ...(t.type === 'pie' || t.type === 'donut' ? { measures: v.measures.slice(0, 1) } : {}),
                                                     ...(t.type === 'kpi' && !v.title ? { dimension: '' } : {}) })}>
                  <t.icon size={22} style={t.rotate ? { transform: 'rotate(90deg) scaleX(-1)' } : undefined} />
                </UnstyledButton>
              </Tooltip>
            ))}
          </SimpleGrid>
          <Tabs defaultValue="fields" variant="pills" radius="xl">
            <Tabs.List grow mb="md">
              <Tabs.Tab value="fields">Fields</Tabs.Tab>
              <Tabs.Tab value="filters">Filters</Tabs.Tab>
              <Tabs.Tab value="format">Format</Tabs.Tab>
            </Tabs.List>
            <ScrollArea.Autosize mah="calc(min(860px, 92dvh) - 300px)" type="auto" offsetScrollbars>
              <Tabs.Panel value="fields">
                {v.type === 'text' ? <Text size="sm" c="dimmed">A text visual has no data — write it under Format.</Text> : (
                  <Stack gap="md">
                    <Select label={v.type === 'kpi' ? 'Total, or add up a breakdown' : 'Rows (breakdown)'} allowDeselect={false}
                            description={v.type === 'kpi' ? undefined : 'What each bar, slice or row is'}
                            data={(catalog?.dimensions ?? []).map((d) => ({ value: d.key, label: d.key === '' ? 'Total (no breakdown)' : d.label }))}
                            value={v.dimension} onChange={(d) => set({ dimension: d ?? '' })} />
                    <MultiSelect label={single ? 'Value' : 'Values (columns)'} searchable placeholder={v.measures.length ? '' : '+ Add data'}
                                 description="Measures we collect, and your Expressions (ƒ)" maxDropdownHeight={360}
                                 data={valueOptions} value={v.measures} maxValues={single ? 1 : 12}
                                 onChange={(m) => set({ measures: m })} hidePickedOptions />
                    {v.measures.length > 1 && (
                      <Stack gap={4}>
                        <Text size="xs" c="dimmed">Order (first = first colour / column)</Text>
                        {v.measures.map((m, i) => (
                          <Group key={m} gap={4} wrap="nowrap" className={classes.measureRow}>
                            <span className={classes.swatch} style={{ background: `var(--viz-${(i % 8) + 1})` }} />
                            <Text size="sm" truncate style={{ flex: 1 }}>{labelOf(m)}</Text>
                            <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => move(i, -1)} aria-label="Move up" disabled={i === 0}><IconArrowUp size={14} /></ActionIcon>
                            <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => move(i, 1)} aria-label="Move down" disabled={i === v.measures.length - 1}><IconArrowDown size={14} /></ActionIcon>
                            <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => set({ measures: v.measures.filter((x) => x !== m) })} aria-label="Remove"><IconX size={14} /></ActionIcon>
                          </Group>
                        ))}
                      </Stack>
                    )}
                    {v.measures.length > 8 && <Text size="xs" c="orange">Past 8 values the colours repeat — consider a table or two visuals.</Text>}
                  </Stack>
                )}
              </Tabs.Panel>
              <Tabs.Panel value="filters">
                <Stack gap="md">
                  <Select label="Vehicle group" placeholder={category ? `Page filter (${category})` : 'Page filter (all vehicles)'} clearable
                          data={categories.map((c) => c.name)} value={v.category ?? null} onChange={(c) => set({ category: c })} />
                  <Select label="Vehicle" placeholder="All vehicles" clearable searchable data={vehicles.map((x) => ({ value: x.imei, label: vehicleName(x) }))}
                          value={v.imei ?? null} onChange={(c) => set({ imei: c })} />
                  {!['day', 'week', 'month', 'hour', 'weekday', ''].includes(v.dimension) && (
                    <>
                      <Select label="Sort by" placeholder="First value" clearable data={v.measures.map((m) => ({ value: m, label: labelOf(m) }))}
                              value={v.sort ?? null} onChange={(s) => set({ sort: s })} />
                      <SegmentedControl size="xs" value={v.descending === false ? 'asc' : 'desc'} onChange={(d) => set({ descending: d !== 'asc' })}
                                        data={[{ value: 'desc', label: 'Highest first' }, { value: 'asc', label: 'Lowest first' }]} />
                      <NumberInput label="Show the top" placeholder="All" min={1} max={500} suffix=" rows" value={v.limit ?? ''}
                                   onChange={(n) => set({ limit: typeof n === 'number' ? n : null })} />
                    </>
                  )}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="format">
                <Stack gap="md">
                  <TextInput label="Title" placeholder="e.g. Distance per day" value={v.title} onChange={(e) => set({ title: e.currentTarget.value })} />
                  {v.type === 'text' && <Textarea label="Text" autosize minRows={4} value={v.text ?? ''} onChange={(e) => set({ text: e.currentTarget.value })} />}
                  <div><Text size="sm" fw={500} mb={4}>Width</Text>
                    <SegmentedControl fullWidth size="xs" data={WIDTHS} value={String(v.width)} onChange={(w) => set({ width: Number(w) })} /></div>
                  <div><Text size="sm" fw={500} mb={4}>Height</Text>
                    <SegmentedControl fullWidth size="xs" value={v.height} onChange={(h) => set({ height: h as Visual['height'] })}
                                      data={[{ value: 's', label: 'Small' }, { value: 'm', label: 'Medium' }, { value: 'l', label: 'Large' }]} /></div>
                  {(v.type === 'column' || v.type === 'bar') && (
                    <Switch label="Show values on the bars" checked={!!v.show_values} onChange={(e) => set({ show_values: e.currentTarget.checked })} />
                  )}
                </Stack>
              </Tabs.Panel>
            </ScrollArea.Autosize>
          </Tabs>
        </aside>
        <section className={classes.editorMain}>
          <div className={classes.previewArea}>
            <Paper withBorder radius="lg" p="md" className={classes.previewCard}
                   style={{ width: `${Math.max(34, (v.width / 12) * 100)}%` }}>
              <TextInput variant="filled" placeholder="Title" value={v.title} onChange={(e) => set({ title: e.currentTarget.value })} mb="sm" />
              {v.type !== 'text' && !v.measures.length
                ? <Stack h={height} align="center" justify="center" gap={4}><Text c="dimmed" size="sm">Add a value under Fields to see the chart.</Text></Stack>
                : <VisualChart visual={v} result={preview.data} height={height} />}
              {preview.isError && <Text size="sm" c="red">{(preview.error as Error).message}</Text>}
            </Paper>
          </div>
          <Group justify="flex-end" className={classes.editorFoot}>
            <Button radius="xl" size="md" onClick={() => onSave(v)} disabled={!valid}>Save & close</Button>
            <Button radius="xl" size="md" variant="default" onClick={onClose}>Cancel</Button>
          </Group>
        </section>
      </div>
    </Modal>
  );
}
