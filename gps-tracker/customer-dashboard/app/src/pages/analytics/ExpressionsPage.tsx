import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Anchor, Autocomplete, Badge, Button, Group, NumberInput, Paper, ScrollArea, SimpleGrid, Stack, Text, TextInput, Textarea, Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconMathFunction, IconPlayerPlay, IconPlus, IconSearch } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useAnalyticsCatalog, useCan, useExpressions } from '../../api/hooks';
import type { AnalyticsExpression } from '../../api/types';
import { ConfigHeader } from '../../components/ConfigHeader';
import { EditorShell } from '../../components/EditorShell';
import classes from './Analytics.module.css';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
type Draft = { name: string; category: string; expression: string; description: string; unit: string; decimals: number };
const EMPTY: Draft = { name: '', category: '', expression: '', description: '', unit: '', decimals: 2 };

/** New / edit expression: General, the formula (click measures to insert, test it), and where it's used. */
function ExpressionEditor({ expr, opened, onClose, categories }: {
  expr: AnalyticsExpression | null; opened: boolean; onClose: () => void; categories: string[];
}) {
  const qc = useQueryClient();
  const { data: catalog } = useAnalyticsCatalog();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [current, setCurrent] = useState<AnalyticsExpression | null>(null);
  const [test, setTest] = useState<{ value: number | null; measures: Record<string, number> } | null>(null);
  const [saving, setSaving] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!opened) return;
    setCurrent(expr);
    setTest(null);
    setDraft(expr ? { name: expr.name, category: expr.category ?? '', expression: expr.expression, description: expr.description ?? '',
                      unit: expr.unit ?? '', decimals: expr.decimals } : EMPTY);
  }, [opened, expr]);
  const set = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); if ('expression' in patch) setTest(null); };
  const insert = (text: string) => {
    const el = box.current;
    const at = el?.selectionStart ?? draft.expression.length;
    const end = el?.selectionEnd ?? at;
    const next = `${draft.expression.slice(0, at)}${text}${draft.expression.slice(end)}`;
    set({ expression: next });
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + text.length, at + text.length); });
  };
  const runTest = async () => {
    try {
      setTest(await api('/api/portal/analytics/expressions/test', { method: 'POST', json: {
        expression: draft.expression, date_from: dayjs().subtract(30, 'day').startOf('day').toISOString(), date_to: dayjs().toISOString() } }));
    } catch (e) { fail(e); }
  };
  const save = async (andNew: boolean) => {
    if (!draft.name.trim() || !draft.expression.trim()) { notifications.show({ color: 'orange', message: 'Give the expression a name and a formula' }); return; }
    setSaving(true);
    try {
      const body = { ...draft, name: draft.name.trim(), category: draft.category.trim() || null, unit: draft.unit.trim() || null,
                     description: draft.description.trim() || null };
      if (current) await api(`/api/portal/analytics/expressions/${current.id}`, { method: 'PUT', json: body });
      else await api('/api/portal/analytics/expressions', { method: 'POST', json: body });
      ['analytics-expressions', 'analytics-catalog', 'analytics-query'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      notifications.show({ color: 'green', message: `${body.name} saved` });
      if (andNew) { setCurrent(null); setDraft(EMPTY); setTest(null); } else onClose();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };
  const measureLabel = (k: string) => catalog?.measures.find((m) => m.key === k)?.label ?? k;
  const groups = useMemo(() => {
    const by = new Map<string, NonNullable<typeof catalog>['measures']>();
    (catalog?.measures ?? []).forEach((m) => by.set(m.category, [...(by.get(m.category) ?? []), m]));
    return [...by];
  }, [catalog]);

  return (
    <EditorShell opened={opened} onClose={onClose} title={current ? 'Edit Expression' : 'New Expression'}
                 onSave={() => save(false)} onSaveAndNew={() => save(true)} saving={saving} sections={[
      { id: 'general', label: 'General', keywords: 'name category unit decimals description',
        content: (
          <Stack maw={640}>
            <TextInput label="Name" withAsterisk placeholder="e.g. Exceptions per 100 km" value={draft.name} onChange={(e) => set({ name: e.currentTarget.value })} data-autofocus />
            <Autocomplete label="Category" placeholder="e.g. Exceptions" data={categories} value={draft.category} onChange={(v) => set({ category: v })} />
            <SimpleGrid cols={2}>
              <TextInput label="Unit" placeholder="e.g. km, %, R" maxLength={20} value={draft.unit} onChange={(e) => set({ unit: e.currentTarget.value })} />
              <NumberInput label="Decimals" min={0} max={4} value={draft.decimals} onChange={(v) => set({ decimals: Number(v) || 0 })} />
            </SimpleGrid>
            <TextInput label="Description" placeholder="Shown under the formula" value={draft.description} onChange={(e) => set({ description: e.currentTarget.value })} />
          </Stack>
        ) },
      { id: 'formula', label: 'Expression', keywords: 'formula measures expression test',
        content: (
          <Stack maw={900}>
            <Textarea ref={box} label="Formula" withAsterisk autosize minRows={2} styles={{ input: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' } }}
                      placeholder="m.Trip_distance_km / m.Trip_count" value={draft.expression} onChange={(e) => set({ expression: e.currentTarget.value })}
                      description="Measures are written m.<name>. Use numbers, + − × ÷ and brackets. Dividing by zero gives no value." />
            <Group gap={6}>
              {['+', '-', '*', '/', '(', ')', '* 100'].map((op) => (
                <Button key={op} size="compact-sm" variant="default" ff="monospace" onClick={() => insert(` ${op} `.replace('  ', ' '))}>{op}</Button>
              ))}
              <Button size="compact-sm" ml="auto" leftSection={<IconPlayerPlay size={14} />} onClick={runTest} disabled={!draft.expression.trim()}>Test (last 30 days)</Button>
            </Group>
            {test && (
              <Alert variant="light" icon={<IconMathFunction size={16} />}>
                <Text fw={650}>= {test.value === null ? 'no value (divides by zero)' : `${test.value.toLocaleString(undefined, { maximumFractionDigits: draft.decimals })}${draft.unit ? ` ${draft.unit}` : ''}`}</Text>
                <Text size="xs" c="dimmed">{Object.entries(test.measures).map(([k, v]) => `${measureLabel(k)} ${v.toLocaleString()}`).join(' · ')} — whole fleet you can see</Text>
              </Alert>
            )}
            <Text size="sm" fw={500} mt="xs">Measures — click to insert</Text>
            <ScrollArea.Autosize mah={320} type="auto">
              <Stack gap="sm">
                {groups.map(([cat, items]) => (
                  <div key={cat}>
                    <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb={4}>{cat}</Text>
                    <Group gap={6}>
                      {items.map((m) => (
                        <Tooltip key={m.key} label={`${m.label}${m.unit ? ` (${m.unit})` : ''}`} withinPortal>
                          <Badge component="button" type="button" variant="outline" tt="none" fw={500} ff="monospace" style={{ cursor: 'pointer' }}
                                 onClick={() => insert(`m.${m.key}`)}>m.{m.key}</Badge>
                        </Tooltip>
                      ))}
                    </Group>
                  </div>
                ))}
              </Stack>
            </ScrollArea.Autosize>
          </Stack>
        ) },
      ...(current ? [{ id: 'used', label: 'Used in', keywords: 'used visuals pages',
        content: (
          <Stack gap={4} maw={640}>
            {(current.used_in ?? []).length ? (current.used_in ?? []).map((u) => <Text key={u} size="sm">{u}</Text>)
              : <Text size="sm" c="dimmed">Not used in any Analytics visual yet.</Text>}
          </Stack>
        ) }] : []),
    ]} />
  );
}

/** Reports → Expressions: calculations over the measures we collect, usable as values in Analytics visuals. */
export function ExpressionsPage() {
  const qc = useQueryClient();
  const manage = useCan()('analytics.manage');
  const { data: exprs = [], isLoading } = useExpressions();
  const [search, setSearch] = useState('');
  const [cat, setCat] = useState<string | null>(null);
  const [editing, setEditing] = useState<AnalyticsExpression | 'new' | null>(null);
  const categories = useMemo(() => [...new Set(exprs.map((e) => e.category || 'Other'))].sort(), [exprs]);
  const q = search.trim().toLowerCase();
  const shown = exprs.filter((e) => (!cat || (e.category || 'Other') === cat)
    && (!q || `${e.name} ${e.expression} ${e.description ?? ''}`.toLowerCase().includes(q)));
  const copy = async (e: AnalyticsExpression) => {
    let n = 2;
    while (exprs.some((x) => x.name === `${e.name} (${n})`)) n++;
    try {
      await api('/api/portal/analytics/expressions', { method: 'POST', json: { ...e, name: `${e.name} (${n})` } });
      ['analytics-expressions', 'analytics-catalog'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (err) { fail(err); }
  };
  const remove = (e: AnalyticsExpression) => modals.openConfirmModal({
    title: `Delete “${e.name}”?`, labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">{(e.used_in ?? []).length ? `It's used in ${e.used_in!.join(', ')} — remove it there first.` : 'It isn’t used in any visual.'}</Text>,
    onConfirm: async () => {
      try { await api(`/api/portal/analytics/expressions/${e.id}`, { method: 'DELETE' }); ['analytics-expressions', 'analytics-catalog'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); }
      catch (err) { fail(err); }
    },
  });

  return (
    <Stack p="lg" gap={0}>
      <ConfigHeader section="Reports" title="Expressions" root="/reports" rootLabel="Reports"
                    description="Your own calculations over the data we collect, e.g. exceptions per 100 km. Use them as values in Analytics.">
        {manage && <Button size="xs" variant="default" onClick={async () => {
          try {
            const r = await api<{ added: number }>('/api/portal/analytics/expressions/restore', { method: 'POST' });
            qc.invalidateQueries({ queryKey: ['analytics-expressions'] });
            notifications.show({ message: r.added ? `${r.added} starting expression(s) restored` : 'All the starting expressions are here' });
          } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
        }}>Restore starting expressions</Button>}
        {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>New expression</Button>}
      </ConfigHeader>
      <div className={classes.exprLayout}>
        <Paper withBorder radius="lg" style={{ overflow: 'hidden' }}>
          <TextInput m="sm" radius="xl" placeholder="Search…" leftSection={<IconSearch size={15} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <UnstyledButton className={classes.cat} data-active={!cat || undefined} onClick={() => setCat(null)}><span>All</span><span>{exprs.length}</span></UnstyledButton>
          {categories.map((c) => (
            <UnstyledButton key={c} className={classes.cat} data-active={cat === c || undefined} onClick={() => setCat(c)}>
              <span>{c}</span><Text span c="dimmed" size="sm">{exprs.filter((e) => (e.category || 'Other') === c).length}</Text>
            </UnstyledButton>
          ))}
        </Paper>
        <Paper withBorder radius="lg">
          {!isLoading && shown.length === 0 && <Text c="dimmed" size="sm" p="lg">No expressions match.</Text>}
          {shown.map((e) => (
            <div key={e.id} className={classes.exprRow}>
              <div>
                <Text fw={600}>{e.name}{e.unit ? <Text span c="dimmed" size="sm"> ({e.unit})</Text> : null}</Text>
                {(e.used_in ?? []).length > 0 && <Text size="xs" c="dimmed">Used in {e.used_in!.length} visual{e.used_in!.length === 1 ? '' : 's'}</Text>}
              </div>
              <div style={{ minWidth: 0 }}>
                <div className={classes.code}>{e.expression}</div>
                {e.description && <Text size="sm" c="dimmed" mt={4}>{e.description}</Text>}
              </div>
              {manage && (
                <Group gap={6} wrap="nowrap">
                  <Anchor size="sm" component="button" onClick={() => setEditing(e)}>Edit</Anchor><Text c="dimmed">|</Text>
                  <Anchor size="sm" component="button" onClick={() => copy(e)}>Copy</Anchor><Text c="dimmed">|</Text>
                  <Anchor size="sm" component="button" c="red" onClick={() => remove(e)}>Delete</Anchor>
                </Group>
              )}
            </div>
          ))}
        </Paper>
      </div>
      <ExpressionEditor opened={!!editing} expr={editing === 'new' ? null : editing} onClose={() => setEditing(null)} categories={categories} />
    </Stack>
  );
}
