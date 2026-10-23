import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Badge, Button, Checkbox, ColorInput, Group, Modal, MultiSelect, NumberInput, Paper, ScrollArea, SegmentedControl,
  Select, SimpleGrid, Stack, Stepper, Switch, Table, TagsInput, Text, TextInput, Textarea, Tooltip, UnstyledButton,
} from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconArrowDown, IconArrowUp, IconCalendarRepeat, IconChevronDown, IconChevronUp, IconCopy, IconDownload, IconFileReport,
  IconPencil, IconPlayerPlay, IconPlus, IconRefresh, IconSearch, IconTrash, IconX,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import { api, download } from '../../api/client';
import {
  CR, useCrCategories, useCrColumns, useCrMeta, useCrRefresh, useCrReports, useCrRuns, useCrSchedules,
  type CrColumn, type CrColumnDef, type CrFormat, type CrPreview, type CrReport, type CrReportDef, type CrRun, type CrSchedule,
  type CrValues,
} from '../../api/customReports';
import { useCan, useCategories, useDrivers, useEventTypes, usePlaces, useVehicles, type Range } from '../../api/hooks';
import { ConfigHeader } from '../../components/ConfigHeader';
import { RangePicker, defaultRange } from '../../components/RangePicker';
import { ago, vehicleName } from '../../utils/format';
import classes from './CustomReports.module.css';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
const kb = (n: number | null) => (n == null ? '' : n < 1024 ? `${n} B` : `${(n / 1024).toFixed(0)} kB`);
const FREQ = { daily: 'Daily (yesterday)', weekly: 'Weekly (last Monday–Sunday)', monthly: 'Monthly (last month)' };
const JOB_STATUSES = ['Overdue', 'Due', 'Recommended', 'Booked', 'In Progress', 'Completed'];
const COST_CATEGORIES = [['maintenance', 'Maintenance'], ['fuel', 'Fuel'], ['tracking', 'Tracking'], ['licence', 'Licence'],
  ['fines', 'Fines'], ['insurance', 'Insurance'], ['other', 'Other']].map(([value, label]) => ({ value, label }));

const emptyDef = (): CrReportDef => ({ title: '', description: '', category_id: null, row_entity: '', top_n: null, columns: [],
  parameters: [{ key: 'date_range', required: true }], column_filters: [], file: { format: 'xlsx', orientation: 'landscape', csv_separator: 'comma' } });
const toValues = (r: Range, v: Partial<CrValues> = {}): CrValues => ({ ...v, date_from: r.from.toISOString(), date_to: r.to.toISOString() });

// ── Parameter inputs (run dialog, preview, schedule) ──
function ParamInputs({ def, columns, values, onChange, range, onRange }: {
  def: CrReportDef; columns: CrColumnDef[]; values: Partial<CrValues>; onChange: (v: Partial<CrValues>) => void;
  range?: Range; onRange?: (r: Range) => void;
}) {
  const { data: meta } = useCrMeta();
  const { data: vehicles = [] } = useVehicles();
  const { data: categories = [] } = useCategories();
  const { data: drivers = [] } = useDrivers();
  const { data: places = [] } = usePlaces();
  const { data: eventTypes } = useEventTypes();
  const label = (k: string) => meta?.parameters.find((p) => p.key === k)?.label ?? k;
  const set = (patch: Partial<CrValues>) => onChange({ ...values, ...patch });
  const op = (k: string) => meta?.operators.find((o) => o.key === k)?.label ?? k;
  return (
    <Stack gap="xs">
      {def.parameters.map((p) => {
        const req = p.required || p.key === 'date_range';
        const common = { label: label(p.key), withAsterisk: req, size: 'xs' as const };
        switch (p.key) {
          case 'date_range':
            return range && onRange ? <div key={p.key}><Text size="xs" fw={500} mb={2}>{label(p.key)} <Text span c="red">*</Text></Text><RangePicker value={range} onChange={onRange} /></div>
              : <Text key={p.key} size="xs" c="dimmed">Date range: follows the schedule (yesterday / last week / last month)</Text>;
          case 'vehicle':
            return <Select key={p.key} {...common} clearable searchable placeholder="All vehicles" data={vehicles.map((v) => ({ value: v.imei, label: vehicleName(v) }))}
                           value={values.vehicle ?? null} onChange={(v) => set({ vehicle: v })} />;
          case 'vehicle_group':
            return <Select key={p.key} {...common} clearable placeholder="All vehicle groups" data={categories.map((c) => c.name)}
                           value={values.vehicle_group ?? null} onChange={(v) => set({ vehicle_group: v })} />;
          case 'driver':
            return <Select key={p.key} {...common} clearable searchable placeholder="All drivers" data={drivers.map((d) => ({ value: d.id, label: d.name }))}
                           value={values.driver ?? null} onChange={(v) => set({ driver: v })} />;
          case 'event_type':
            return <MultiSelect key={p.key} {...common} clearable searchable placeholder="All events" data={(eventTypes?.events ?? []).map((e) => ({ value: e.code, label: e.label }))}
                                value={values.event_type ?? []} onChange={(v) => set({ event_type: v })} />;
          case 'trip_events_only':
            return <Switch key={p.key} size="xs" label={label(p.key)} checked={!!values.trip_events_only} onChange={(e) => set({ trip_events_only: e.currentTarget.checked })} />;
          case 'place':
            return <Select key={p.key} {...common} clearable searchable placeholder="All places" data={places.map((x) => ({ value: String(x.id), label: x.name }))}
                           value={values.place ?? null} onChange={(v) => set({ place: v })} />;
          case 'alert_type':
            return <TextInput key={p.key} {...common} placeholder="All, or e.g. geofence_entry" value={values.alert_type ?? ''} onChange={(e) => set({ alert_type: e.currentTarget.value || null })} />;
          case 'job_status':
            return <Select key={p.key} {...common} clearable placeholder="All" data={JOB_STATUSES} value={values.job_status ?? null} onChange={(v) => set({ job_status: v })} />;
          case 'cost_category':
            return <Select key={p.key} {...common} clearable placeholder="All" data={COST_CATEGORIES} value={values.cost_category ?? null} onChange={(v) => set({ cost_category: v })} />;
          default:
            return null;
        }
      })}
      {def.column_filters.map((f) => {
        const col = columns.find((c) => c.key === f.column);
        const cur = values.filters?.[f.column] ?? {};
        const setF = (patch: object) => set({ filters: { ...(values.filters ?? {}), [f.column]: { ...cur, ...patch } } });
        return (
          <Group key={f.column} gap={6} align="flex-end" wrap="nowrap">
            <NumberInput size="xs" style={{ flex: 1 }} withAsterisk={f.required} label={`${col?.label ?? f.column}: ${op(f.op)}`}
                         value={cur.value ?? ''} onChange={(v) => setF({ value: v === '' ? null : v })} />
            {f.op === 'between' && <NumberInput size="xs" style={{ flex: 1 }} label="and" value={cur.value2 ?? ''} onChange={(v) => setF({ value2: v === '' ? null : v })} />}
          </Group>
        );
      })}
    </Stack>
  );
}

// ── Column picker: categories → columns ──
function ColumnPicker({ opened, columns, chosen, onPick, onClose }: {
  opened: boolean; columns: CrColumnDef[]; chosen: string[]; onPick: (key: string) => void; onClose: () => void;
}) {
  const [search, setSearch] = useState('');
  const [cat, setCat] = useState<string | null>(null);
  const cats = useMemo(() => {
    const m = new Map<string, number>();
    columns.forEach((c) => m.set(c.category, (m.get(c.category) ?? 0) + 1));
    return [...m];
  }, [columns]);
  const q = search.trim().toLowerCase();
  const shown = columns.filter((c) => (!q || c.label.toLowerCase().includes(q)) && (q || !cat || c.category === cat));
  return (
    <Modal opened={opened} onClose={onClose} title="Add column" size="xl">
      <TextInput mb="sm" placeholder="Search" leftSection={<IconSearch size={14} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} data-autofocus />
      <div className={classes.picker}>
        <ScrollArea h={400} type="auto" className={classes.pickerCats}>
          <UnstyledButton className={classes.cat} data-active={!cat || undefined} onClick={() => setCat(null)}><span>All</span><span>{columns.length}</span></UnstyledButton>
          {cats.map(([c, n]) => (
            <UnstyledButton key={c} className={classes.cat} data-active={cat === c || undefined} onClick={() => setCat(c)}><span>{c}</span><span>{n}</span></UnstyledButton>
          ))}
        </ScrollArea>
        <ScrollArea h={400} type="auto">
          {shown.map((c) => (
            <UnstyledButton key={c.key} className={classes.colRow} disabled={chosen.includes(c.key)} data-chosen={chosen.includes(c.key) || undefined}
                            onClick={() => onPick(c.key)}>
              <Group gap={6} wrap="nowrap">
                {c.expression && <Badge size="xs" variant="light">fx</Badge>}
                <Text size="sm">{c.label}</Text>
                {c.unit && <Text size="xs" c="dimmed">({c.unit})</Text>}
              </Group>
              <Text size="xs" c="dimmed">{c.category}</Text>
            </UnstyledButton>
          ))}
          {!shown.length && <Text size="sm" c="dimmed" p="sm">Nothing matches.</Text>}
        </ScrollArea>
      </div>
    </Modal>
  );
}

// ── One column: title, sort, decimals, unit, conditional colours ──
function ColumnOptions({ col, def, onChange }: { col: CrColumn; def?: CrColumnDef; onChange: (c: CrColumn) => void }) {
  const fmt: CrFormat = { apply_to: 'cell_bg', compare: 'absolute', empty_color: null, ranges: [], ...(col.format ?? {}) };
  const setFmt = (f: Partial<CrFormat> | null) => onChange({ ...col, format: f === null ? null : { ...fmt, ...f } });
  const numeric = def?.type === 'number';
  return (
    <Stack gap="xs" p="sm" className={classes.options}>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <TextInput size="xs" label="Title" placeholder={def?.label} value={col.title ?? ''} onChange={(e) => onChange({ ...col, title: e.currentTarget.value || null })} />
        <Select size="xs" label="Sort order" allowDeselect={false} value={col.sort ?? 'none'}
                data={[{ value: 'none', label: '–' }, { value: 'asc', label: 'Ascending' }, { value: 'desc', label: 'Descending' }]}
                onChange={(v) => onChange({ ...col, sort: v === 'asc' || v === 'desc' ? v : null })} />
        {numeric && <NumberInput size="xs" label="Decimal places" placeholder="Auto" min={0} max={6} value={col.decimals ?? ''}
                                 onChange={(v) => onChange({ ...col, decimals: v === '' ? null : Number(v) })} />}
      </SimpleGrid>
      {numeric && (
        <Group gap="lg">
          <Checkbox size="xs" label="Unit of measure in each value" checked={!!col.show_unit} onChange={(e) => onChange({ ...col, show_unit: e.currentTarget.checked })} />
          <Checkbox size="xs" label="Conditional format" checked={!!col.format} onChange={(e) => setFmt(e.currentTarget.checked ? { ranges: [{ min: null, max: null, color: '#fca5a5' }] } : null)} />
        </Group>
      )}
      {numeric && col.format && (
        <Paper withBorder p="xs" radius="sm">
          <SimpleGrid cols={{ base: 1, sm: 3 }} mb="xs">
            <Select size="xs" label="Apply colours to" allowDeselect={false} value={fmt.apply_to} onChange={(v) => setFmt({ apply_to: (v ?? 'cell_bg') as CrFormat['apply_to'] })}
                    data={[{ value: 'cell_bg', label: 'Cell background' }, { value: 'cell_text', label: 'Cell text' },
                           { value: 'row_bg', label: 'Row background' }, { value: 'row_text', label: 'Row text' }]} />
            <Select size="xs" label="Compare to" allowDeselect={false} value={fmt.compare} onChange={(v) => setFmt({ compare: (v ?? 'absolute') as CrFormat['compare'] })}
                    data={[{ value: 'absolute', label: 'Absolute value' }, { value: 'percentage', label: 'Percentage of the highest' }]} />
            <ColorInput size="xs" label="Empty field colour" placeholder="None" value={fmt.empty_color ?? ''} onChange={(v) => setFmt({ empty_color: v || null })} />
          </SimpleGrid>
          {fmt.ranges.map((r, i) => (
            <Group key={i} gap={6} mb={4} wrap="nowrap">
              <NumberInput size="xs" placeholder="Min" value={r.min ?? ''} onChange={(v) => setFmt({ ranges: fmt.ranges.map((x, j) => (j === i ? { ...x, min: v === '' ? null : Number(v) } : x)) })} />
              <NumberInput size="xs" placeholder="Max" value={r.max ?? ''} onChange={(v) => setFmt({ ranges: fmt.ranges.map((x, j) => (j === i ? { ...x, max: v === '' ? null : Number(v) } : x)) })} />
              <ColorInput size="xs" value={r.color} onChange={(v) => setFmt({ ranges: fmt.ranges.map((x, j) => (j === i ? { ...x, color: v } : x)) })} />
              <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => setFmt({ ranges: fmt.ranges.filter((_, j) => j !== i) })} aria-label="Remove range"><IconX size={14} /></ActionIcon>
            </Group>
          ))}
          <Button size="compact-xs" variant="subtle" leftSection={<IconPlus size={12} />}
                  onClick={() => setFmt({ ranges: [...fmt.ranges, { min: null, max: null, color: '#fde68a' }] })}>Add condition</Button>
        </Paper>
      )}
    </Stack>
  );
}

// ── The wizard ──
function Wizard({ editing, onClose, onSaved }: { editing: CrReport | 'new' | null; onClose: () => void; onSaved: (r: CrReport) => void }) {
  const mobile = useMediaQuery('(max-width: 48em)');
  const { data: meta } = useCrMeta();
  const { data: categories = [] } = useCrCategories();
  const [def, setDef] = useState<CrReportDef>(emptyDef);
  const [step, setStep] = useState(0);
  const [picking, setPicking] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [range, setRange] = useState<Range>(defaultRange);
  const [values, setValues] = useState<Partial<CrValues>>({});
  const [preview, setPreview] = useState<CrPreview | null>(null);
  const [saving, setSaving] = useState(false);
  const { data: columns = [] } = useCrColumns(def.row_entity || null);
  const entity = meta?.entities.find((e) => e.key === def.row_entity);
  useEffect(() => {
    if (!editing) return;
    setDef(editing === 'new' ? emptyDef() : { ...editing });
    setStep(editing === 'new' ? 0 : 1);
    setValues({});
    setPreview(null);
  }, [editing]);
  const set = (patch: Partial<CrReportDef>) => setDef((d) => ({ ...d, ...patch }));
  const colDef = (key: string) => columns.find((c) => c.key === key);
  const pickEntity = (key: string) => {
    const e = meta?.entities.find((x) => x.key === key);
    set({ row_entity: key, columns: (e?.default_columns ?? []).map((k) => ({ key: k })), column_filters: [],
          parameters: [{ key: 'date_range', required: true }, ...(e?.parameters ?? []).filter((p) => p !== 'date_range').map((p) => ({ key: p, required: false }))] });
  };
  const moveCol = (i: number, d: number) => {
    const c = [...def.columns]; const j = i + d;
    if (j < 0 || j >= c.length) return;
    [c[i], c[j]] = [c[j], c[i]];
    set({ columns: c });
  };
  // Live preview: the first rows, once the required parameters have values
  const [debounced] = useDebouncedValue({ def, values, range }, 500);
  useEffect(() => {
    if (!editing || !debounced.def.row_entity || !debounced.def.columns.length) { setPreview(null); return; }
    api<CrPreview>(`${CR}/preview`, { method: 'POST', json: { report: { ...debounced.def, title: debounced.def.title || 'Preview' },
                                                            values: toValues(debounced.range, debounced.values) } })
      .then(setPreview).catch((e) => setPreview({ ready: false, message: (e as Error).message, columns: [], rows: [] }));
  }, [debounced, editing]);
  const save = async () => {
    if (!def.title.trim()) { setStep(4); notifications.show({ color: 'orange', message: 'Give the report a title' }); return; }
    setSaving(true);
    try {
      const r = await api<CrReport>(`${CR}${editing && editing !== 'new' ? `/${editing.id}` : ''}`,
                                    { method: editing && editing !== 'new' ? 'PUT' : 'POST', json: def });
      notifications.show({ color: 'green', message: `${r.title} saved` });
      onSaved(r);
    } catch (e) { fail(e); } finally { setSaving(false); }
  };
  const numericCols = def.columns.filter((c) => colDef(c.key)?.type === 'number');

  return (
    <Modal opened={!!editing} onClose={onClose} fullScreen={mobile} size="min(1500px, 97vw)" padding={0} withCloseButton={false}
           classNames={{ content: classes.wizardContent, body: classes.wizardBody }}>
      <div className={classes.wizard}>
        <section className={classes.wizardMain}>
          <Group justify="space-between" mb="md">
            <Text fz={22} fw={600}>{editing === 'new' ? 'New report' : `Edit “${def.title}”`}</Text>
          </Group>
          <Stepper active={step} onStepClick={(s) => (def.row_entity || s === 0) && setStep(s)} size="sm" mb="md" allowNextStepsSelect={!!def.row_entity}>
            <Stepper.Step label="Report type" />
            <Stepper.Step label="Columns" />
            <Stepper.Step label="Parameters" />
            <Stepper.Step label="File" />
            <Stepper.Step label="Summary" />
          </Stepper>
          <ScrollArea className={classes.stepBody} type="auto" offsetScrollbars>
            {step === 0 && (
              <Stack>
                <Text size="sm" c="dimmed">What is one row of the report? Its columns and parameters depend on this.</Text>
                <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="xs">
                  {(meta?.entities ?? []).map((e) => (
                    <UnstyledButton key={e.key} className={classes.entity} data-active={def.row_entity === e.key || undefined} onClick={() => pickEntity(e.key)}>
                      <Text fw={600} size="sm">{e.label}</Text>
                      <Text size="xs" c="dimmed">{e.kind === 'aggregate' ? 'One row per ' + e.label.toLowerCase().replace('date - ', '') + ', with totals' : 'One row per ' + e.label.toLowerCase()}</Text>
                    </UnstyledButton>
                  ))}
                </SimpleGrid>
              </Stack>
            )}
            {step === 1 && (
              <Stack gap="sm">
                <Group align="flex-end">
                  <NumberInput label="Top N rows" placeholder="All" min={1} w={160} value={def.top_n ?? ''} onChange={(v) => set({ top_n: v === '' ? null : Number(v) })} />
                  <Button leftSection={<IconPlus size={16} />} onClick={() => setPicking(true)}>Add column</Button>
                </Group>
                {def.columns.map((c, i) => {
                  const d = colDef(c.key);
                  return (
                    <Paper key={c.key} withBorder radius="md">
                      <Group justify="space-between" p={6} wrap="nowrap" className={classes.chip} onClick={() => setOpen(open === c.key ? null : c.key)}>
                        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                          {d?.expression && <Badge size="xs" variant="light">fx</Badge>}
                          <Text size="sm" fw={500} truncate>{c.title || d?.label || c.key}</Text>
                          {c.sort && (c.sort === 'asc' ? <IconArrowUp size={14} /> : <IconArrowDown size={14} />)}
                          {c.format && <Badge size="xs" variant="dot">colours</Badge>}
                          {c.title && d && <Text size="xs" c="dimmed" truncate>({d.label})</Text>}
                        </Group>
                        <Group gap={2} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                          <ActionIcon size="sm" variant="subtle" color="gray" disabled={i === 0} onClick={() => moveCol(i, -1)} aria-label="Move up"><IconChevronUp size={14} /></ActionIcon>
                          <ActionIcon size="sm" variant="subtle" color="gray" disabled={i === def.columns.length - 1} onClick={() => moveCol(i, 1)} aria-label="Move down"><IconChevronDown size={14} /></ActionIcon>
                          <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Remove column"
                                      onClick={() => set({ columns: def.columns.filter((x) => x.key !== c.key), column_filters: def.column_filters.filter((f) => f.column !== c.key) })}><IconX size={14} /></ActionIcon>
                        </Group>
                      </Group>
                      {open === c.key && <ColumnOptions col={c} def={d} onChange={(n) => set({ columns: def.columns.map((x) => (x.key === c.key ? n : x)) })} />}
                    </Paper>
                  );
                })}
                {!def.columns.length && <Text size="sm" c="dimmed">Add the columns the report shows.</Text>}
                <ColumnPicker opened={picking} columns={columns} chosen={def.columns.map((c) => c.key)} onClose={() => setPicking(false)}
                              onPick={(k) => set({ columns: [...def.columns, { key: k }] })} />
              </Stack>
            )}
            {step === 2 && (
              <Stack gap="md">
                <div>
                  <Text fw={600} mb={4}>Parameters</Text>
                  <Text size="xs" c="dimmed" mb="xs">What the person running the report chooses. Required ones must be filled in.</Text>
                  {(entity?.parameters ?? []).map((k) => {
                    const p = def.parameters.find((x) => x.key === k);
                    const always = k === 'date_range';
                    return (
                      <Group key={k} justify="space-between" py={4} className={classes.paramRow}>
                        <Checkbox label={meta?.parameters.find((x) => x.key === k)?.label ?? k} checked={!!p || always} disabled={always}
                                  onChange={(e) => set({ parameters: e.currentTarget.checked ? [...def.parameters, { key: k, required: false }] : def.parameters.filter((x) => x.key !== k) })} />
                        {(p || always) && <Switch size="xs" label="Required" checked={always || !!p?.required} disabled={always}
                                                  onChange={(e) => set({ parameters: def.parameters.map((x) => (x.key === k ? { ...x, required: e.currentTarget.checked } : x)) })} />}
                      </Group>
                    );
                  })}
                </div>
                <div>
                  <Text fw={600} mb={4}>Column filters</Text>
                  <Text size="xs" c="dimmed" mb="xs">Keep only rows whose number column meets a condition, e.g. Top speed greater than 120. The value is entered when the report runs.</Text>
                  {def.column_filters.map((f, i) => (
                    <Group key={f.column} gap="xs" mb={6} wrap="nowrap">
                      <Text size="sm" style={{ flex: 1 }}>{def.columns.find((c) => c.key === f.column)?.title || colDef(f.column)?.label}</Text>
                      <Select size="xs" w={190} allowDeselect={false} value={f.op} data={(meta?.operators ?? []).map((o) => ({ value: o.key, label: o.label }))}
                              onChange={(v) => set({ column_filters: def.column_filters.map((x, j) => (j === i ? { ...x, op: v ?? 'gt' } : x)) })} />
                      <Switch size="xs" label="Required" checked={f.required} onChange={(e) => set({ column_filters: def.column_filters.map((x, j) => (j === i ? { ...x, required: e.currentTarget.checked } : x)) })} />
                      <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => set({ column_filters: def.column_filters.filter((_, j) => j !== i) })} aria-label="Remove filter"><IconX size={14} /></ActionIcon>
                    </Group>
                  ))}
                  <Select size="xs" w={300} placeholder="+ Add filter" value={null} searchable
                          data={numericCols.filter((c) => !def.column_filters.some((f) => f.column === c.key)).map((c) => ({ value: c.key, label: c.title || colDef(c.key)?.label || c.key }))}
                          onChange={(v) => v && set({ column_filters: [...def.column_filters, { column: v, op: 'gt', required: false }] })}
                          nothingFoundMessage="Add number columns first" />
                </div>
              </Stack>
            )}
            {step === 3 && (
              <Stack gap="md" maw={560}>
                <SegmentedControl value={def.file.format} onChange={(v) => set({ file: { ...def.file, format: v as CrReportDef['file']['format'] } })}
                                  data={[{ value: 'xlsx', label: 'Excel' }, { value: 'csv', label: 'CSV' }, { value: 'pdf', label: 'PDF' }]} />
                {def.file.format === 'xlsx' && <Checkbox label="Include parameter values (under the title)" checked={!!def.file.include_parameters}
                                                         onChange={(e) => set({ file: { ...def.file, include_parameters: e.currentTarget.checked } })} />}
                {def.file.format === 'csv' && <Select label="Column separator" allowDeselect={false} value={def.file.csv_separator ?? 'comma'}
                                                      data={[{ value: 'comma', label: 'Comma' }, { value: 'semicolon', label: 'Semicolon' }, { value: 'tab', label: 'Tab' }]}
                                                      onChange={(v) => set({ file: { ...def.file, csv_separator: (v ?? 'comma') as 'comma' } })} />}
                {def.file.format === 'pdf' && <>
                  <Select label="Orientation" allowDeselect={false} value={def.file.orientation ?? 'landscape'}
                          data={[{ value: 'landscape', label: 'Landscape' }, { value: 'portrait', label: 'Portrait' }]}
                          onChange={(v) => set({ file: { ...def.file, orientation: (v ?? 'landscape') as 'landscape' } })} />
                  <Checkbox label="Include parameter values (under the title)" checked={!!def.file.include_parameters}
                            onChange={(e) => set({ file: { ...def.file, include_parameters: e.currentTarget.checked } })} />
                </>}
                <Text size="xs" c="dimmed">Excel and PDF files carry your report logo (Configuration → User Groups) and the conditional colours.</Text>
              </Stack>
            )}
            {step === 4 && (
              <Stack gap="sm" maw={620}>
                <TextInput label="Title" withAsterisk value={def.title} onChange={(e) => set({ title: e.currentTarget.value })} data-autofocus />
                <Textarea label="Description" autosize minRows={2} value={def.description ?? ''} onChange={(e) => set({ description: e.currentTarget.value })} />
                <Select label="Report category" clearable placeholder="None" data={categories.map((c) => ({ value: c.id, label: c.name }))}
                        value={def.category_id ?? null} onChange={(v) => set({ category_id: v })} />
                <Paper withBorder p="sm" radius="md">
                  <Text size="sm"><b>Rows:</b> {entity?.label}{def.top_n ? ` (top ${def.top_n})` : ''}</Text>
                  <Text size="sm"><b>Columns:</b> {def.columns.map((c) => c.title || colDef(c.key)?.label).join(', ')}</Text>
                  <Text size="sm"><b>Parameters:</b> {def.parameters.map((p) => `${meta?.parameters.find((x) => x.key === p.key)?.label}${p.required ? ' (required)' : ''}`).join(', ')}</Text>
                  {def.column_filters.length > 0 && <Text size="sm"><b>Column filters:</b> {def.column_filters.map((f) => colDef(f.column)?.label).join(', ')}</Text>}
                  <Text size="sm"><b>File:</b> {{ xlsx: 'Excel', csv: 'CSV', pdf: 'PDF' }[def.file.format]}</Text>
                </Paper>
              </Stack>
            )}
          </ScrollArea>
          <Group justify="space-between" mt="md">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Group gap="xs">
              <Button variant="default" disabled={step === 0} onClick={() => setStep(step - 1)}>« Previous</Button>
              {step < 4 ? <Button disabled={!def.row_entity || (step === 1 && !def.columns.length)} onClick={() => setStep(step + 1)}>Next »</Button>
                : <Button loading={saving} onClick={save}>Save</Button>}
            </Group>
          </Group>
        </section>
        <aside className={classes.previewPane}>
          <Text fw={600} mb="xs">Report preview</Text>
          {def.row_entity ? (
            <Stack gap="sm">
              <ParamInputs def={def} columns={columns} values={values} onChange={setValues} range={range} onRange={setRange} />
              {preview && !preview.ready && <Text size="sm" c="dimmed">{preview.message}</Text>}
              {preview?.ready && (
                <ScrollArea type="auto">
                  <Table fz="xs" striped withTableBorder>
                    <Table.Thead><Table.Tr>{preview.columns.map((c) => <Table.Th key={c.key}>{c.title}{c.unit && c.type === 'number' ? ` (${c.unit})` : ''}</Table.Th>)}</Table.Tr></Table.Thead>
                    <Table.Tbody>
                      {preview.rows.map((r, i) => (
                        <Table.Tr key={i} style={{ background: preview.styles?.[i]?.row?.[0] ?? undefined, color: preview.styles?.[i]?.row?.[1] ?? undefined }}>
                          {r.map((v, j) => {
                            const st = preview.styles?.[i]?.cells?.[String(j)];
                            return <Table.Td key={j} style={{ background: st?.[0] ?? undefined, color: st?.[1] ?? (st?.[0] ? '#111' : undefined), whiteSpace: 'nowrap' }}>{String(v)}</Table.Td>;
                          })}
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                  {!preview.rows.length && <Text size="sm" c="dimmed">No rows for these parameters.</Text>}
                  <Text size="xs" c="dimmed" mt={4}>First {preview.rows.length} rows</Text>
                </ScrollArea>
              )}
            </Stack>
          ) : <Text size="sm" c="dimmed">Choose the report type.</Text>}
        </aside>
      </div>
    </Modal>
  );
}

// ── Generate a file ──
function GenerateModal({ report, onClose }: { report: CrReport | null; onClose: () => void }) {
  const refresh = useCrRefresh();
  const { data: columns = [] } = useCrColumns(report?.row_entity ?? null);
  const [range, setRange] = useState<Range>(defaultRange);
  const [values, setValues] = useState<Partial<CrValues>>({});
  const [fileName, setFileName] = useState('');
  const [compress, setCompress] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (report) { setValues({}); setFileName(`${report.title.replace(/\s+/g, '_')}_{StartDate}_{EndDate}`); setCompress(false); } }, [report]);
  const go = async () => {
    if (!report) return;
    setBusy(true);
    try {
      const run = await api<CrRun>(`${CR}/${report.id}/runs`, { method: 'POST', json: { values: toValues(range, values), file_name: fileName, compress } });
      refresh();
      notifications.show({ color: 'green', message: `${run.file_name} ready (${run.rows} rows)` });
      await download(`${CR}/runs/${run.id}/file`, run.file_name ?? 'report');
      onClose();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  return (
    <Modal opened={!!report} onClose={onClose} title={`Generate “${report?.title}”`} size="lg">
      {report && (
        <Stack>
          <ParamInputs def={report} columns={columns} values={values} onChange={setValues} range={range} onRange={setRange} />
          <TextInput label="File name" description="{StartDate}, {EndDate} and {ReportDate}, optionally with a format, e.g. {ReportDate:dd.mm.yyyy}"
                     value={fileName} onChange={(e) => setFileName(e.currentTarget.value)} />
          <Checkbox label="Use compression (zip)" checked={compress} onChange={(e) => setCompress(e.currentTarget.checked)} />
          <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button>
            <Button leftSection={<IconPlayerPlay size={16} />} loading={busy} onClick={go}>Generate file</Button></Group>
        </Stack>
      )}
    </Modal>
  );
}

// ── A schedule ──
function ScheduleEditor({ report, schedule, onClose }: { report: CrReport; schedule: CrSchedule | 'new' | null; onClose: () => void }) {
  const refresh = useCrRefresh();
  const { data: columns = [] } = useCrColumns(report.row_entity);
  const blank = { name: report.title, is_active: true, frequency: 'monthly' as CrSchedule['frequency'], send_hour: 6, values: {} as Partial<CrValues>,
                  file_name: '', compress: false, recipients: [] as string[], subject: '', body: '' };
  const [f, setF] = useState(blank);
  useEffect(() => {
    if (!schedule) return;
    setF(schedule === 'new' ? blank : { name: schedule.name ?? '', is_active: schedule.is_active, frequency: schedule.frequency, send_hour: schedule.send_hour,
      values: schedule.values, file_name: schedule.file_name ?? '', compress: schedule.compress, recipients: schedule.recipients,
      subject: schedule.subject ?? '', body: schedule.body ?? '' });
  }, [schedule]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    try {
      await api(`${CR}/${report.id}/schedules${schedule && schedule !== 'new' ? `/${schedule.id}` : ''}`,
                { method: schedule && schedule !== 'new' ? 'PUT' : 'POST', json: f });
      refresh();
      notifications.show({ color: 'green', message: 'Schedule saved' });
      onClose();
    } catch (e) { fail(e); }
  };
  return (
    <Modal opened={!!schedule} onClose={onClose} title={schedule === 'new' ? 'New schedule' : 'Edit schedule'} size="lg">
      <Stack gap="sm">
        <Group grow>
          <TextInput label="Description" value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
          <Switch label="Active" mt={24} checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.currentTarget.checked })} />
        </Group>
        <Group grow>
          <Select label="Frequency" allowDeselect={false} value={f.frequency} data={Object.entries(FREQ).map(([value, label]) => ({ value, label }))}
                  onChange={(v) => setF({ ...f, frequency: (v ?? 'monthly') as CrSchedule['frequency'] })} />
          <NumberInput label="Send at (hour)" min={0} max={23} value={f.send_hour} onChange={(v) => setF({ ...f, send_hour: Number(v) || 0 })} />
        </Group>
        <Text size="xs" c="dimmed">The date range follows the frequency: daily reports cover yesterday, weekly ones last Monday–Sunday, monthly ones last month.</Text>
        <Paper withBorder p="sm" radius="md"><Text size="sm" fw={600} mb={4}>Parameters</Text>
          <ParamInputs def={report} columns={columns} values={f.values} onChange={(v) => setF({ ...f, values: v })} /></Paper>
        <TextInput label="File name" placeholder="Title_{StartDate}_{EndDate}" value={f.file_name} onChange={(e) => setF({ ...f, file_name: e.currentTarget.value })} />
        <Checkbox label="Use compression (zip)" checked={f.compress} onChange={(e) => setF({ ...f, compress: e.currentTarget.checked })} />
        <TagsInput label="E-mail to" withAsterisk placeholder="name@company.co.za, Enter after each" splitChars={[',', ' ', ';']} value={f.recipients}
                   onChange={(v) => setF({ ...f, recipients: v })} />
        <TextInput label="E-mail subject" placeholder={`${report.title} — <period>`} value={f.subject} onChange={(e) => setF({ ...f, subject: e.currentTarget.value })} />
        <Textarea label="E-mail text" autosize minRows={2} value={f.body} onChange={(e) => setF({ ...f, body: e.currentTarget.value })} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button onClick={save}>Save</Button></Group>
      </Stack>
    </Modal>
  );
}

// ── Report detail: definition, schedules, history ──
function Detail({ report, onEdit, onDeleted }: { report: CrReport; onEdit: () => void; onDeleted: () => void }) {
  const can = useCan();
  const design = can('reports.design'), schedule = can('reports.schedule');
  const refresh = useCrRefresh();
  const { data: meta } = useCrMeta();
  const { data: columns = [] } = useCrColumns(report.row_entity);
  const { data: runs = [], isFetching, refetch } = useCrRuns(report.id);
  const { data: schedules = [] } = useCrSchedules(report.id);
  const [generating, setGenerating] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<CrSchedule | 'new' | null>(null);
  const [more, setMore] = useState(false);
  const label = (k: string) => meta?.parameters.find((p) => p.key === k)?.label ?? k;
  const colLabel = (c: CrColumn) => c.title || columns.find((x) => x.key === c.key)?.label || c.key;
  const copy = async () => { try { await api(`${CR}/${report.id}/copy`, { method: 'POST' }); refresh(); notifications.show({ message: 'Report copied' }); } catch (e) { fail(e); } };
  const del = () => modals.openConfirmModal({
    title: `Delete “${report.title}”?`, children: <Text size="sm">Its schedules and file history go too.</Text>,
    labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => { try { await api(`${CR}/${report.id}`, { method: 'DELETE' }); refresh(); onDeleted(); } catch (e) { fail(e); } },
  });
  const delSchedule = (s: CrSchedule) => modals.openConfirmModal({
    title: 'Delete this schedule?', labels: { confirm: 'Delete', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    onConfirm: async () => { try { await api(`${CR}/${report.id}/schedules/${s.id}`, { method: 'DELETE' }); refresh(); } catch (e) { fail(e); } },
  });
  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div><Text fz={22} fw={600}>{report.title}</Text>{report.description && <Text size="sm" c="dimmed">{report.description}</Text>}</div>
        {design && <Group gap={6}>
          <Button size="xs" variant="default" leftSection={<IconPencil size={14} />} onClick={onEdit}>Edit</Button>
          <Button size="xs" variant="default" leftSection={<IconCopy size={14} />} onClick={copy}>Copy</Button>
          <Button size="xs" variant="default" color="red" leftSection={<IconTrash size={14} />} onClick={del}>Delete</Button>
        </Group>}
      </Group>
      <Paper withBorder p="sm" radius="md">
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          <Text size="sm"><b>Rows:</b> {report.row_entity_label}{report.top_n ? ` (top ${report.top_n})` : ''}</Text>
          <Text size="sm"><b>File type:</b> {{ xlsx: 'Excel', csv: 'CSV', pdf: 'PDF' }[report.file.format]}</Text>
          <Text size="sm"><b>Parameters:</b> {report.parameters.map((p) => `${label(p.key)}${p.required ? ' (Required)' : ''}`).join(', ')}</Text>
          <Text size="sm" lineClamp={more ? undefined : 2}><b>Columns:</b> {report.columns.map((c) => `${colLabel(c)}${c.sort === 'asc' ? ' ▲' : c.sort === 'desc' ? ' ▼' : ''}`).join(', ')}</Text>
        </SimpleGrid>
        <Button size="compact-xs" variant="subtle" mt={4} onClick={() => setMore(!more)}>{more ? 'View less' : 'View more'}</Button>
      </Paper>
      <div>
        <Group justify="space-between" mb={6}><Text fw={600}>Schedules</Text>
          {schedule && <Button size="xs" variant="light" leftSection={<IconCalendarRepeat size={14} />} onClick={() => setEditingSchedule('new')}>Add new schedule</Button>}</Group>
        <Table fz="sm" withTableBorder striped>
          <Table.Thead><Table.Tr><Table.Th>Description</Table.Th><Table.Th>Frequency</Table.Th><Table.Th>Delivery</Table.Th><Table.Th>Next</Table.Th><Table.Th>Status</Table.Th><Table.Th w={70} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {schedules.map((s) => (
              <Table.Tr key={s.id}>
                <Table.Td>{s.name}{!s.is_active && <Badge size="xs" ml={6} color="gray">paused</Badge>}</Table.Td>
                <Table.Td>{s.frequency} at {String(s.send_hour).padStart(2, '0')}:00</Table.Td>
                <Table.Td>E-mail · {s.recipients.join(', ')}</Table.Td>
                <Table.Td>{s.next_run_at ? dayjs(s.next_run_at).format('D MMM HH:mm') : '—'}</Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{s.last_status ?? 'not run yet'}</Text></Table.Td>
                <Table.Td>{schedule && <Group gap={2} wrap="nowrap">
                  <ActionIcon size="sm" variant="subtle" onClick={() => setEditingSchedule(s)} aria-label="Edit schedule"><IconPencil size={14} /></ActionIcon>
                  <ActionIcon size="sm" variant="subtle" color="red" onClick={() => delSchedule(s)} aria-label="Delete schedule"><IconTrash size={14} /></ActionIcon></Group>}</Table.Td>
              </Table.Tr>
            ))}
            {!schedules.length && <Table.Tr><Table.Td colSpan={6}><Text size="sm" c="dimmed">Not scheduled.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </div>
      <div>
        <Group justify="space-between" mb={6}><Text fw={600}>History</Text>
          <Group gap={6}>
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} loading={isFetching} onClick={() => refetch()}>Refresh</Button>
            <Button size="xs" leftSection={<IconPlayerPlay size={14} />} onClick={() => setGenerating(true)}>Generate new file</Button>
          </Group></Group>
        <Table fz="sm" withTableBorder striped>
          <Table.Thead><Table.Tr><Table.Th>Created</Table.Th><Table.Th>By</Table.Th><Table.Th>Parameters</Table.Th><Table.Th>Status</Table.Th><Table.Th>Download</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {runs.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td><Tooltip label={dayjs(r.created_at).format('D MMM YYYY HH:mm')}><span>{ago(r.created_at)}</span></Tooltip></Table.Td>
                <Table.Td>{r.schedule ? <Badge size="xs" variant="light">{r.schedule}</Badge> : r.created_by}</Table.Td>
                <Table.Td><Text size="xs">{r.parameters}</Text></Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>{r.status === 'done' ? <Text size="xs" c="green">✓ {r.rows} rows</Text>
                  : <Tooltip label={r.error}><Badge size="sm" color="red" variant="light">failed</Badge></Tooltip>}</Table.Td>
                <Table.Td>{r.status === 'done' && <Button size="compact-xs" variant="subtle" leftSection={<IconDownload size={12} />}
                                                          onClick={() => download(`${CR}/runs/${r.id}/file`, r.file_name ?? 'report').catch(fail)}>{kb(r.size_bytes)}</Button>}</Table.Td>
              </Table.Tr>
            ))}
            {!runs.length && <Table.Tr><Table.Td colSpan={5}><Text size="sm" c="dimmed">No files yet — Generate new file.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </div>
      <GenerateModal report={generating ? report : null} onClose={() => setGenerating(false)} />
      <ScheduleEditor report={report} schedule={editingSchedule} onClose={() => setEditingSchedule(null)} />
    </Stack>
  );
}

/** Reports → Custom Reports: a library of the group's own reports (categories → reports → detail). */
export function CustomReportsPage() {
  const can = useCan();
  const design = can('reports.design');
  const refresh = useCrRefresh();
  const { data: reports = [] } = useCrReports();
  const { data: categories = [] } = useCrCategories();
  const [cat, setCat] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<CrReport | 'new' | null>(null);
  const [catEdit, setCatEdit] = useState(false);
  const [newCat, setNewCat] = useState('');
  const shown = reports.filter((r) => (!cat || (cat === 'none' ? !r.category_id : r.category_id === cat))
    && (!search || r.title.toLowerCase().includes(search.toLowerCase())));
  const current = reports.find((r) => r.id === selected) ?? null;
  const addCat = async () => {
    if (!newCat.trim()) return;
    try { await api(`${CR}/categories`, { method: 'POST', json: { name: newCat.trim() } }); setNewCat(''); refresh(); } catch (e) { fail(e); }
  };
  const renameCat = async (id: string, name: string) => { try { await api(`${CR}/categories/${id}`, { method: 'PUT', json: { name } }); refresh(); } catch (e) { fail(e); } };
  const deleteCat = async (id: string) => { try { await api(`${CR}/categories/${id}`, { method: 'DELETE' }); refresh(); } catch (e) { fail(e); } };
  return (
    <Stack p="lg" gap="md">
      <ConfigHeader section="Reports" title="Custom Reports" root="/reports" rootLabel="Reports"
                    description="Your own reports: choose the rows, columns and parameters, then generate a file or e-mail it on a schedule.">
        {design && <Button size="xs" variant="default" onClick={() => setCatEdit(true)}>Edit report categories</Button>}
        {design && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing('new')}>Add new report</Button>}
      </ConfigHeader>
      <div className={classes.library}>
        <Paper withBorder radius="md" className={classes.pane}>
          <TextInput size="xs" m="xs" placeholder="Search" leftSection={<IconSearch size={13} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <UnstyledButton className={classes.cat} data-active={!cat || undefined} onClick={() => setCat(null)}><span>All reports</span><span>{reports.length}</span></UnstyledButton>
          {categories.map((c) => (
            <UnstyledButton key={c.id} className={classes.cat} data-active={cat === c.id || undefined} onClick={() => setCat(c.id)}><span>{c.name}</span><span>{c.reports}</span></UnstyledButton>
          ))}
          {reports.some((r) => !r.category_id) && categories.length > 0 && (
            <UnstyledButton className={classes.cat} data-active={cat === 'none' || undefined} onClick={() => setCat('none')}><span>No category</span><span>{reports.filter((r) => !r.category_id).length}</span></UnstyledButton>
          )}
        </Paper>
        <Paper withBorder radius="md" className={classes.pane}>
          {shown.map((r) => (
            <UnstyledButton key={r.id} className={classes.report} data-active={selected === r.id || undefined} onClick={() => setSelected(r.id)}>
              <Text size="sm" fw={500}>{r.title}</Text>
              <Text size="xs" c="dimmed">{r.row_entity_label} · {{ xlsx: 'Excel', csv: 'CSV', pdf: 'PDF' }[r.file.format]}</Text>
            </UnstyledButton>
          ))}
          {!shown.length && <Stack align="center" p="lg" gap={4}><IconFileReport size={32} opacity={0.4} />
            <Text size="sm" c="dimmed" ta="center">{reports.length ? 'No reports here.' : 'No custom reports yet.'}</Text>
            {design && !reports.length && <Button size="xs" mt="xs" onClick={() => setEditing('new')}>Add new report</Button>}</Stack>}
        </Paper>
        <Paper withBorder radius="md" p="md" className={classes.detail}>
          {current ? <Detail report={current} onEdit={() => setEditing(current)} onDeleted={() => setSelected(null)} />
            : <Text size="sm" c="dimmed">Choose a report.</Text>}
        </Paper>
      </div>
      <Wizard editing={editing} onClose={() => setEditing(null)} onSaved={(r) => { refresh(); setSelected(r.id); setEditing(null); }} />
      <Modal opened={catEdit} onClose={() => setCatEdit(false)} title="Report categories">
        <Stack gap="xs">
          {categories.map((c) => (
            <Group key={c.id} gap={6} wrap="nowrap">
              <TextInput size="xs" style={{ flex: 1 }} defaultValue={c.name} onBlur={(e) => e.currentTarget.value !== c.name && renameCat(c.id, e.currentTarget.value)} />
              <Text size="xs" c="dimmed" w={70}>{c.reports} reports</Text>
              <ActionIcon size="sm" variant="subtle" color="red" onClick={() => deleteCat(c.id)} aria-label="Delete category"><IconTrash size={14} /></ActionIcon>
            </Group>
          ))}
          <Group gap={6} wrap="nowrap">
            <TextInput size="xs" style={{ flex: 1 }} placeholder="New category" value={newCat} onChange={(e) => setNewCat(e.currentTarget.value)}
                       onKeyDown={(e) => e.key === 'Enter' && addCat()} />
            <Button size="xs" variant="light" onClick={addCat} disabled={!newCat.trim()}>Add</Button>
          </Group>
          <Text size="xs" c="dimmed">Deleting a category keeps its reports, without a category.</Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
