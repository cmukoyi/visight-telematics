import { useEffect, useState } from 'react';
import { Badge, Button, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Table, Text, TextInput, Textarea } from '@mantine/core';
import { DateInput, DateTimePicker } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconPlayerPlay, IconCheck, IconPlus } from '@tabler/icons-react';
import dayjs from 'dayjs';
import { api, qs } from '../../api/client';
import {
  STATUS_COLOR, mntApi, useMaintenanceCatalog, useMaintenanceRefresh, type CostRow, type JobRow, type JobStatus, type Named,
} from '../../api/maintenance';
import { EditorShell, firstError } from '../../components/EditorShell';
import { dateTime } from '../../utils/format';

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message });
export const money = (v: number | null | undefined) =>
  (v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
export const StatusBadge = ({ status }: { status: JobStatus }) => (
  <Badge component="span" size="sm" variant={status === 'Overdue' ? 'filled' : 'light'} color={STATUS_COLOR[status]}>{status}</Badge>
);

/** What's due, in words: "47 000 km (158 km ago) · 24 Apr 2027 (in 182 days)". */
export function dueText(j: JobRow): string {
  if (!j.due) return '';
  const parts: string[] = [];
  const left = j.left ?? { km: null, hours: null, days: null };
  if (j.due.km != null) parts.push(`${j.due.km.toLocaleString()} km${left.km != null ? (left.km <= 0 ? ` (${Math.abs(left.km).toLocaleString()} km over)` : ` (${left.km.toLocaleString()} km to go)`) : ''}`);
  if (j.due.hours != null) parts.push(`${j.due.hours.toLocaleString()} engine h${left.hours != null ? (left.hours <= 0 ? ` (${Math.abs(left.hours)} h over)` : ` (${left.hours} h to go)`) : ''}`);
  if (j.due.date) parts.push(`${dayjs(j.due.date).format('D MMM YYYY')}${left.days != null ? (left.days < 0 ? ` (${-left.days} days ago)` : ` (in ${left.days} days)`) : ''}`);
  return parts.join(' · ');
}

// ── Job editor: a new job, a saved one, or one projected from a schedule ──
type JobForm = {
  imei: string | null; description: string; type_id: string | null; schedule_id: string | null;
  planned_start: Date | null; planned_end: Date | null; actual_start: Date | null; actual_end: Date | null;
  odometer_km: number | ''; engine_hours: number | ''; workshop_id: string | null; reference: string; notes: string;
};

export function JobEditor({ job, imei, onClose, onCost }: {
  /** 'new', a saved job, or a projected one (saving books it). */
  job: JobRow | 'new' | null; imei?: string | null; onClose: () => void; onCost?: (job: JobRow) => void;
}) {
  const refresh = useMaintenanceRefresh();
  const { data: catalog } = useMaintenanceCatalog();
  const [costs, setCosts] = useState<CostRow[]>([]);
  const form = useForm<JobForm>({
    initialValues: {
      imei: null, description: '', type_id: null, schedule_id: null, planned_start: new Date(), planned_end: null,
      actual_start: null, actual_end: null, odometer_km: '', engine_hours: '', workshop_id: null, reference: '', notes: '',
    },
    validate: {
      imei: (v) => (v ? null : 'Choose a vehicle'),
      description: (v) => (v.trim() ? null : 'Enter a description'),
      planned_start: (v) => (v ? null : 'Set the planned start'),
    },
  });
  const saved = job && job !== 'new' && !job.projected ? job : null;
  useEffect(() => {
    if (!job) return;
    const d = (v: string | null | undefined) => (v ? dayjs(v).toDate() : null);
    if (job === 'new') {
      form.setValues({ imei: imei ?? null, description: '', type_id: null, schedule_id: null, planned_start: new Date(), planned_end: null,
                       actual_start: null, actual_end: null, odometer_km: '', engine_hours: '', workshop_id: null, reference: '', notes: '' });
    } else {
      form.setValues({
        imei: job.imei, description: job.description, type_id: job.type_id, schedule_id: job.schedule_id,
        // Booking an overdue one: plan it from now rather than from when it fell due
        planned_start: job.projected && (!job.planned_start || dayjs(job.planned_start).isBefore(dayjs())) ? new Date() : d(job.planned_start) ?? new Date(),
        planned_end: job.projected ? null : d(job.planned_end), actual_start: d(job.actual_start),
        actual_end: d(job.actual_end), odometer_km: job.projected ? '' : job.odometer_km ?? '',
        engine_hours: job.projected ? '' : job.engine_hours ?? '', workshop_id: job.workshop_id, reference: job.reference ?? '',
        notes: job.notes ?? '',
      });
    }
    setCosts([]);
    if (job !== 'new' && !job.projected) {
      api<CostRow[]>(`/api/portal/maintenance/costs${qs({ maintenance_id: job.id })}`).then(setCosts).catch(() => setCosts([]));
    }
  }, [job]); // eslint-disable-line react-hooks/exhaustive-deps

  // Meters at the job: fill from the vehicle when it starts
  const fillMeters = async () => {
    if (!form.values.imei) return;
    try {
      const m = await mntApi.meters(form.values.imei);
      if (form.values.odometer_km === '' && m.odometer_km != null) form.setFieldValue('odometer_km', Math.round(m.odometer_km));
      if (form.values.engine_hours === '' && m.engine_hours != null) form.setFieldValue('engine_hours', m.engine_hours);
    } catch { /* the server fills them on save */ }
  };

  const save = () => form.onSubmit(async (v) => {
    const iso = (x: Date | null) => (x ? x.toISOString() : null);
    const body = { ...v, planned_start: iso(v.planned_start), planned_end: iso(v.planned_end), actual_start: iso(v.actual_start),
                   actual_end: iso(v.actual_end), odometer_km: v.odometer_km === '' ? null : v.odometer_km,
                   engine_hours: v.engine_hours === '' ? null : v.engine_hours };
    try {
      await mntApi.save('jobs', saved ? saved.id : null, body);
      refresh();
      notifications.show({ color: 'green', message: `${v.description} saved` });
      onClose();
    } catch (e) { fail(e); }
  }, firstError)();

  const status: JobStatus | null = form.values.actual_end ? 'Completed' : form.values.actual_start ? 'In Progress'
    : saved || (job && job !== 'new') ? 'Booked' : null;
  const type = catalog?.types.find((t) => t.id === form.values.type_id);
  const itemName = new Map((catalog?.items ?? []).map((i) => [i.id, i.name]));
  const projected = job && job !== 'new' && job.projected ? job : null;

  return (
    <EditorShell opened={!!job} onClose={onClose} onSave={save}
                 title={<>{job === 'new' ? 'New Maintenance' : projected ? 'Book Maintenance' : 'Edit Maintenance'}{' '}
                   <span style={{ verticalAlign: 'middle' }}>{projected ? <StatusBadge status={projected.status} /> : status && <StatusBadge status={status} />}</span></>}
                 sections={[
      { id: 'general', label: 'General', keywords: 'description vehicle type schedule',
        content: (
          <Stack maw={680}>
            {projected && (
              <Paper withBorder p="sm" radius="md">
                <Text size="sm"><b>{projected.schedule}</b> is {projected.status.toLowerCase()} for {projected.vehicle}: {dueText(projected)}.</Text>
                <Text size="xs" c="dimmed">Saving books it. Set an actual start when the vehicle goes in, and an actual end when it’s done — the next one then counts from this job.</Text>
              </Paper>
            )}
            <TextInput label="Description" withAsterisk placeholder="e.g. 50 000 km service" {...form.getInputProps('description')} data-autofocus />
            <Select label="Vehicle" withAsterisk searchable placeholder="Choose…" disabled={!!projected || !!saved}
                    data={(catalog?.vehicles ?? []).map((v) => ({ value: v.imei, label: v.name }))}
                    value={form.values.imei} onChange={(v) => form.setFieldValue('imei', v)} error={form.errors.imei} />
            <Select label="Maintenance type" placeholder="None" clearable searchable
                    data={(catalog?.types ?? []).map((t) => ({ value: t.id, label: t.name }))}
                    value={form.values.type_id} onChange={(v) => {
                      form.setFieldValue('type_id', v);
                      const t = catalog?.types.find((x) => x.id === v);
                      if (t && !form.values.description) form.setFieldValue('description', t.name);
                    }} />
            {type && type.item_ids.length > 0 && (
              <Text size="xs" c="dimmed">Includes: {type.item_ids.map((i) => itemName.get(i)).filter(Boolean).join(', ')}</Text>
            )}
          </Stack>
        ) },
      { id: 'dates', label: 'Maintenance Dates', keywords: 'planned actual start end dates',
        content: (
          <Stack maw={680}>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <DateTimePicker label="Planned start" withAsterisk valueFormat="D MMM YYYY HH:mm" {...form.getInputProps('planned_start')} />
              <DateTimePicker label="Planned end" clearable valueFormat="D MMM YYYY HH:mm" placeholder={type ? 'From the type’s expected duration' : ''}
                              {...form.getInputProps('planned_end')} />
              <DateTimePicker label="Actual start" clearable valueFormat="D MMM YYYY HH:mm" maxDate={new Date()} placeholder="When it went in"
                              {...form.getInputProps('actual_start')} />
              <DateTimePicker label="Actual end" clearable valueFormat="D MMM YYYY HH:mm" maxDate={new Date()} placeholder="When it was done"
                              {...form.getInputProps('actual_end')} />
            </SimpleGrid>
            <Group gap="xs">
              {!form.values.actual_start && (
                <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />}
                        onClick={() => { form.setFieldValue('actual_start', new Date()); fillMeters(); }}>In the workshop now</Button>
              )}
              {form.values.actual_start && !form.values.actual_end && (
                <Button size="xs" variant="light" color="green" leftSection={<IconCheck size={14} />}
                        onClick={() => { form.setFieldValue('actual_end', new Date()); fillMeters(); }}>Completed now</Button>
              )}
            </Group>
            <Text size="xs" c="dimmed">Status follows the dates: no actual start → Booked, actual start → In Progress, actual end → Completed.</Text>
          </Stack>
        ) },
      { id: 'details', label: 'Details', keywords: 'odometer engine hours workshop reference notes',
        content: (
          <Stack maw={680}>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <NumberInput label="Odometer at the job" min={0} thousandSeparator=" " allowDecimal={false}
                           rightSection={<Text size="xs" c="dimmed">km</Text>} rightSectionWidth={40}
                           description="Filled from the vehicle when it starts; the next km threshold counts from it"
                           {...form.getInputProps('odometer_km')} />
              <NumberInput label="Engine hours at the job" min={0} decimalScale={1} rightSection={<Text size="xs" c="dimmed">h</Text>}
                           rightSectionWidth={32} {...form.getInputProps('engine_hours')} />
            </SimpleGrid>
            <Select label="Workshop" placeholder="None" clearable searchable data={(catalog?.workshops ?? []).map((w) => ({ value: w.id, label: w.name }))}
                    value={form.values.workshop_id} onChange={(v) => form.setFieldValue('workshop_id', v)} />
            <TextInput label="Reference number" placeholder="Job card or invoice number" {...form.getInputProps('reference')} />
            <Textarea label="Notes" autosize minRows={2} maxRows={6} {...form.getInputProps('notes')} />
          </Stack>
        ) },
      ...(saved ? [{ id: 'costs', label: 'Costs', keywords: 'costs amount cost items',
        content: (
          <Stack maw={680}>
            {costs.length ? (
              <Table fz="sm" striped>
                <Table.Thead><Table.Tr><Table.Th>Date</Table.Th><Table.Th>Item</Table.Th><Table.Th>Description</Table.Th><Table.Th ta="right">Cost</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {costs.map((c) => (
                    <Table.Tr key={c.id}><Table.Td>{dayjs(c.cost_date).format('D MMM YYYY')}</Table.Td><Table.Td>{c.item ?? '—'}</Table.Td>
                      <Table.Td>{c.description ?? '—'}</Table.Td><Table.Td ta="right">{money(c.amount)}</Table.Td></Table.Tr>
                  ))}
                  <Table.Tr><Table.Td colSpan={3} fw={600}>Total</Table.Td><Table.Td ta="right" fw={600}>{money(costs.reduce((a, c) => a + c.amount, 0))}</Table.Td></Table.Tr>
                </Table.Tbody>
              </Table>
            ) : <Text size="sm" c="dimmed">No costs recorded for this job yet.</Text>}
            {onCost && <Group><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => onCost(saved)}>Add cost item</Button></Group>}
          </Stack>
        ) }] : []),
    ]} />
  );
}

// ── Cost item editor ──
type CostForm = {
  category: string; imei: string | null; cost_date: Date | null; maintenance_id: string | null; item_id: string | null; cost_centre_id: string | null;
  description: string; amount: number | ''; amortise_from: Date | null; amortise_to: Date | null;
};

export function CostEditor({ cost, job, onClose }: { cost: CostRow | 'new' | null; job?: JobRow | null; onClose: () => void }) {
  const refresh = useMaintenanceRefresh();
  const { data: catalog } = useMaintenanceCatalog();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const form = useForm<CostForm>({
    initialValues: { category: 'maintenance', imei: null, cost_date: new Date(), maintenance_id: null, item_id: null, cost_centre_id: null, description: '',
                     amount: '', amortise_from: null, amortise_to: null },
    validate: {
      imei: (v) => (v ? null : 'Choose a vehicle'), cost_date: (v) => (v ? null : 'Set the date'),
      amount: (v) => (v === '' || v < 0 ? 'Enter the cost' : null),
    },
  });
  useEffect(() => {
    if (!cost) return;
    const d = (v: string | null) => (v ? dayjs(v).toDate() : null);
    form.setValues(cost === 'new'
      ? { category: 'maintenance', imei: job?.imei ?? null, cost_date: new Date(), maintenance_id: job && !job.projected ? job.id : null, item_id: null,
          cost_centre_id: null, description: '', amount: '', amortise_from: null, amortise_to: null }
      : { category: cost.category ?? 'maintenance', imei: cost.imei, cost_date: d(cost.cost_date), maintenance_id: cost.maintenance_id, item_id: cost.item_id,
          cost_centre_id: cost.cost_centre_id, description: cost.description ?? '', amount: cost.amount,
          amortise_from: d(cost.amortise_from), amortise_to: d(cost.amortise_to) });
  }, [cost]); // eslint-disable-line react-hooks/exhaustive-deps

  // The chosen vehicle's saved jobs, to link the cost to one
  useEffect(() => {
    const imei = form.values.imei;
    if (!imei) { setJobs([]); return; }
    const from = dayjs().subtract(3, 'year').toISOString(), to = dayjs().add(1, 'year').toISOString();
    api<JobRow[]>(`/api/portal/maintenance/jobs${qs({ imei, date_from: from, date_to: to })}`)
      .then((rows) => setJobs(rows.filter((r) => !r.projected))).catch(() => setJobs([]));
  }, [form.values.imei]);

  const linked = jobs.find((j) => j.id === form.values.maintenance_id);
  const linkedType = catalog?.types.find((t) => t.id === linked?.type_id);
  // With a job chosen, only the items of its maintenance type (when the type has any)
  const limited = !!linkedType && linkedType.item_ids.length > 0;
  const grouped = (catalog?.items ?? []).filter((i) => !limited || linkedType!.item_ids.includes(i.id)).map((i) => ({ value: i.id, label: i.name }));
  const [newCentre, setNewCentre] = useState('');
  const addCentre = async () => {
    if (!newCentre.trim()) return;
    try {
      const c = await mntApi.save<Named>('lookups/cost_centre', null, { name: newCentre.trim() });
      form.setFieldValue('cost_centre_id', c.id);
      setNewCentre('');
      refresh();
    } catch (e) { fail(e); }
  };

  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    const day = (x: Date | null) => (x ? dayjs(x).format('YYYY-MM-DD') : null);
    try {
      await mntApi.save('costs', cost && cost !== 'new' ? cost.id : null, {
        ...v, cost_date: day(v.cost_date), amortise_from: day(v.amortise_from), amortise_to: day(v.amortise_to), amount: String(v.amount) });
      refresh();
      notifications.show({ color: 'green', message: 'Cost item saved' });
      if (andNew) form.setValues({ ...v, item_id: null, description: '', amount: '' }); else onClose();
    } catch (e) { fail(e); }
  }, firstError)();

  return (
    <EditorShell opened={!!cost} onClose={onClose} onSave={() => save(false)} onSaveAndNew={() => save(true)}
                 title={cost === 'new' ? 'New Cost Item' : 'Edit Cost Item'} sections={[
      { id: 'general', label: 'General', keywords: 'vehicle date maintenance item description cost centre',
        content: (
          <Stack maw={680}>
            <Select label="Category" allowDeselect={false} data={(catalog?.cost_categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
                    description="Maintenance, or another running cost (fines, tracking, licence…) for the fleet cost dashboards"
                    value={form.values.category} onChange={(v) => form.setFieldValue('category', v ?? 'maintenance')} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select label="Vehicle" withAsterisk searchable placeholder="Choose…" data={(catalog?.vehicles ?? []).map((v) => ({ value: v.imei, label: v.name }))}
                      value={form.values.imei} onChange={(v) => { form.setFieldValue('imei', v); form.setFieldValue('maintenance_id', null); }}
                      error={form.errors.imei} data-autofocus />
              <DateInput label="Date" withAsterisk valueFormat="D MMM YYYY" {...form.getInputProps('cost_date')} />
            </SimpleGrid>
            <Select label="Maintenance" placeholder={form.values.imei ? 'Not linked to a job' : 'Choose a vehicle first'} clearable searchable
                    disabled={!form.values.imei}
                    data={jobs.map((j) => ({ value: j.id, label: `${j.description} · ${dateTime(j.actual_start ?? j.planned_start)} · ${j.status}` }))}
                    value={form.values.maintenance_id} onChange={(v) => form.setFieldValue('maintenance_id', v)} />
            <Select label="Maintenance item" placeholder="None" clearable searchable data={grouped}
                    description={limited ? `Items of ${linkedType!.name}` : undefined}
                    value={form.values.item_id} onChange={(v) => {
                      form.setFieldValue('item_id', v);
                      const it = catalog?.items.find((i) => i.id === v);
                      if (it && !form.values.description) form.setFieldValue('description', it.name);
                    }} />
            <TextInput label="Description" placeholder="e.g. 5 L engine oil" {...form.getInputProps('description')} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <NumberInput label="Cost" withAsterisk min={0} decimalScale={2} fixedDecimalScale thousandSeparator=" " {...form.getInputProps('amount')} />
              <Select label="Cost centre" placeholder="None" clearable searchable data={(catalog?.cost_centre ?? []).map((c: Named) => ({ value: c.id, label: c.name }))}
                      value={form.values.cost_centre_id} onChange={(v) => form.setFieldValue('cost_centre_id', v)} />
            </SimpleGrid>
            <Group gap={6} wrap="nowrap" justify="flex-end">
              <TextInput size="xs" w={240} placeholder="New cost centre" value={newCentre} onChange={(e) => setNewCentre(e.currentTarget.value)}
                         onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCentre(); } }} />
              <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={addCentre} disabled={!newCentre.trim()}>Add</Button>
            </Group>
          </Stack>
        ) },
      { id: 'amortisation', label: 'Amortisation', keywords: 'amortisation spread period',
        content: (
          <Stack maw={680}>
            <Text size="sm" c="dimmed">Optional: spread the cost over a period (e.g. a set of tyres over a year).</Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <DateInput label="Amortisation start" clearable valueFormat="D MMM YYYY" {...form.getInputProps('amortise_from')} />
              <DateInput label="Amortisation end" clearable valueFormat="D MMM YYYY" {...form.getInputProps('amortise_to')} />
            </SimpleGrid>
          </Stack>
        ) },
    ]} />
  );
}
