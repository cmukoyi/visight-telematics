import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Checkbox, Group, MultiSelect, Paper, Select,
  Stack, Switch, TagsInput, Text, TextInput, Textarea, Title, Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconBellRinging, IconInfoCircle, IconMail, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { api } from '../api/client';
import { useCan, useCategories, useEventTypeGroups, useEventTypeList, usePlaceGroups, usePlaces, useRules, useRulesMeta, useVehicles } from '../api/hooks';
import { detail, type NotificationRule } from '../api/types';
import { EditorShell, firstError } from '../components/EditorShell';
import { DataGrid } from '../components/DataGrid';
import { dateTime, vehicleName } from '../utils/format';
import classes from './NotificationRulesPage.module.css';

const ALL = '__all__';
type RuleForm = {
  name: string; rule_type: string; category: string; place_ids: string[]; place_group_ids: string[]; event_group_id: string | null; event_codes: string[];
  on_entry: boolean; on_exit: boolean;
  email_enabled: boolean; email_recipients: string[]; email_message: string; is_active: boolean;
};
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function NotificationRulesPage() {
  const qc = useQueryClient();
  const manage = useCan()('rules.manage');
  const { data: rules = [], isFetching } = useRules();
  const { data: meta } = useRulesMeta();
  const { data: categories = [] } = useCategories();
  const { data: places = [] } = usePlaces();
  const { data: placeGroups = [] } = usePlaceGroups();
  const { data: eventGroups = [] } = useEventTypeGroups();
  const eventGroupName = useMemo(() => new Map(eventGroups.map((g) => [g.id, g.name])), [eventGroups]);
  const { data: eventTypes = [] } = useEventTypeList();
  const eventName = useMemo(() => new Map(eventTypes.map((t) => [t.code, t.label])), [eventTypes]);
  // Events to pick from, grouped like Configuration → Events → Event Types
  const eventOptions = useMemo(() => {
    const by = new Map<string, { value: string; label: string }[]>();
    eventTypes.forEach((t) => by.set(t.category_label, [...(by.get(t.category_label) ?? []), { value: t.code, label: t.label }]));
    return [...by].map(([group, items]) => ({ group, items }));
  }, [eventTypes]);
  const placeGroupName = useMemo(() => new Map(placeGroups.map((g) => [g.id, g.name])), [placeGroups]);
  const { data: vehicles = [] } = useVehicles();
  const [editing, setEditing] = useState<NotificationRule | 'new' | null>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const placeName = useMemo(() => new Map(places.map((p) => [p.id, p.name])), [places]);

  const form = useForm<RuleForm>({
    initialValues: { name: '', rule_type: 'geofence', category: ALL, place_ids: [], place_group_ids: [], event_group_id: null, event_codes: [],
                     on_entry: true, on_exit: true,
                     email_enabled: false, email_recipients: [], email_message: '', is_active: true },
    validate: {
      name: (v) => (v.trim() ? null : 'Enter a name'),
      on_exit: (v, all) => (all.rule_type !== 'geofence' || v || all.on_entry ? null : 'Choose entry, exit or both'),
      event_codes: (v, all) => (all.rule_type !== 'event' || v.length || all.event_group_id ? null : 'Choose at least one event'),
      email_recipients: (v, all) => (!all.email_enabled ? null : v.length === 0 ? 'Add at least one email address'
        : v.some((e) => !EMAIL.test(e)) ? 'One of the addresses is not valid' : v.length > 20 ? 'At most 20 addresses' : null),
    },
  });

  const open = (r: NotificationRule | 'new') => {
    form.reset();
    if (r === 'new') form.setFieldValue('email_message', meta?.default_message ?? '');
    else form.setValues({
      name: r.name, rule_type: r.rule_type, category: r.category ?? ALL, place_ids: r.place_ids,
      place_group_ids: r.place_group_ids ?? [], event_group_id: r.event_group_id, event_codes: r.event_codes ?? [], on_entry: r.on_entry,
      on_exit: r.on_exit, email_enabled: r.email_enabled, email_recipients: r.email_recipients,
      email_message: r.email_message ?? meta?.default_message ?? '', is_active: r.is_active,
    });
    setEditing(r);
  };
  const toJson = (v: RuleForm) => ({ ...v, category: v.category === ALL ? null : v.category, email_message: v.email_message || null });
  const refresh = () => qc.invalidateQueries({ queryKey: ['notification-rules'] });
  const save = (andNew: boolean) => form.onSubmit(async (v) => {
    try {
      if (editing === 'new') await api('/api/portal/notification-rules', { method: 'POST', json: toJson(v) });
      else if (editing) await api(`/api/portal/notification-rules/${editing.id}`, { method: 'PUT', json: toJson(v) });
      refresh();
      notifications.show({ color: 'green', message: 'Notification rule saved' });
      if (andNew) open('new'); else setEditing(null);
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  }, firstError)();
  const toggleActive = async (r: NotificationRule) => {
    try {
      await api(`/api/portal/notification-rules/${r.id}`, { method: 'PUT', json: {
        ...r, category: r.category, place_ids: r.place_ids, is_active: !r.is_active } });
      refresh();
    } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
  };
  const remove = (r: NotificationRule) => modals.openConfirmModal({
    title: `Delete “${r.name}”?`, labels: { confirm: 'Delete rule', cancel: 'Cancel' }, confirmProps: { color: 'red' },
    children: <Text size="sm">No more alerts or emails will be sent for this rule. Past alerts stay in the Inbox.</Text>,
    onConfirm: async () => { try { await api(`/api/portal/notification-rules/${r.id}`, { method: 'DELETE' }); refresh(); } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); } },
  });

  // Insert {placeholder} at the cursor in the message box
  const insert = (key: string) => {
    const el = messageRef.current;
    const text = form.values.email_message;
    const at = el?.selectionStart ?? text.length;
    form.setFieldValue('email_message', `${text.slice(0, at)}{${key}}${text.slice(el?.selectionEnd ?? at)}`);
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + key.length + 2, at + key.length + 2); });
  };
  // Preview with a vehicle from the chosen group
  const sample = vehicles.find((v) => form.values.category === ALL || v.category_name === form.values.category) ?? vehicles[0];
  const preview = (form.values.email_message || meta?.default_message || '').replace(/\{(\w+)\}/g, (m, k: string) => {
    const values: Record<string, string> = {
      vehicle: sample ? vehicleName(sample) : 'Truck 12', imei: sample?.imei ?? '861327083699665',
      place: placeName.get(form.values.place_ids[0]) ?? places[0]?.name ?? 'Head office',
      event: form.values.rule_type === 'event' ? (eventName.get(form.values.event_codes[0]) ?? 'Harsh braking') : form.values.on_entry ? 'entered' : 'left',
      time: dateTime(new Date().toISOString()), speed: '42',
      registration: (sample && detail(sample, 'registration')) || 'CA 123-456', make: (sample && detail(sample, 'make')) || '—',
      model: (sample && detail(sample, 'model')) || '—', year: (sample && detail(sample, 'year')) || '—',
      driver: (sample && detail(sample, 'driver')) || '—',
    };
    return values[k] ?? m;
  });

  const cols: ColDef<NotificationRule>[] = [
    { headerName: 'Rule', field: 'name', flex: 1.2, minWidth: 180 },
    { headerName: 'Type', field: 'rule_type_label', width: 150 },
    { headerName: 'Vehicles', valueGetter: (p) => p.data?.category ?? 'All vehicles', width: 150 },
    { headerName: 'Watches', flex: 1, minWidth: 180,
      valueGetter: (p) => {
        const r = p.data;
        if (!r) return '';
        if (r.rule_type === 'event') return [...(r.event_codes ?? []).map((c) => eventName.get(c) ?? c),
          ...(r.event_group_id ? [`${eventGroupName.get(r.event_group_id) ?? '?'} (group)`] : [])].join(', ');
        const names = [...r.place_ids.map((id) => placeName.get(id) ?? '?'), ...(r.place_group_ids ?? []).map((id) => `${placeGroupName.get(id) ?? '?'} (group)`)];
        return names.length ? names.join(', ') : 'All places';
      } },
    { headerName: 'Notify on', width: 150, sortable: false,
      cellRenderer: (p: ICellRendererParams<NotificationRule>) => p.data && (p.data.rule_type === 'event'
        ? <Badge size="sm" color="violet" variant="light">Each event</Badge>
        : <Group gap={4} wrap="nowrap">
            {p.data.on_entry && <Badge size="sm" color="green" variant="light">Entry</Badge>}
            {p.data.on_exit && <Badge size="sm" color="red" variant="light">Exit</Badge>}
          </Group>) },
    { headerName: 'Email', width: 140,
      valueGetter: (p) => (p.data?.email_enabled ? p.data.email_recipients.length : 0),
      cellRenderer: (p: ICellRendererParams<NotificationRule>) => p.data && (p.data.email_enabled
        ? <Tooltip label={p.data.email_recipients.join(', ')} withinPortal><Badge size="sm" variant="light" leftSection={<IconMail size={12} />}>
            {p.data.email_recipients.length} recipient{p.data.email_recipients.length === 1 ? '' : 's'}</Badge></Tooltip>
        : <Text size="sm" c="dimmed">Inbox only</Text>) },
    { headerName: 'Active', field: 'is_active', width: 100,
      cellRenderer: (p: ICellRendererParams<NotificationRule>) => p.data && (
        <Switch size="xs" checked={p.data.is_active} disabled={!manage} onChange={() => toggleActive(p.data!)} aria-label="Active" />) },
    ...(manage ? [{ headerName: '', width: 90, minWidth: 90, sortable: false, filter: false, pinned: 'right' as const,
      cellRenderer: (p: ICellRendererParams<NotificationRule>) => p.data && (
        <Group gap={2} wrap="nowrap">
          <ActionIcon size="sm" variant="subtle" onClick={() => open(p.data!)} aria-label="Edit rule"><IconPencil size={15} /></ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" onClick={() => remove(p.data!)} aria-label="Delete rule"><IconTrash size={15} /></ActionIcon>
        </Group>) }] : []),
  ];

  return (
    <Stack p="lg" gap="md" className={classes.root}>
      <Stack gap={4}>
        <Breadcrumbs>
          <Anchor component={Link} to="/configuration" size="sm">Configuration</Anchor>
          <Anchor component={Link} to="/configuration/misc" size="sm">Misc</Anchor>
          <Text size="sm">Notification Rules</Text>
        </Breadcrumbs>
        <Group justify="space-between">
          <div>
            <Title order={1} size="h2">Notification Rules</Title>
            <Text size="sm" c="dimmed">Alert when a vehicle enters or leaves a place, or reports an event such as speeding or harsh braking. Alerts appear in the Inbox; rules can also email.</Text>
          </div>
          {manage && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => open('new')}>Add rule</Button>}
        </Group>
      </Stack>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rules} columnDefs={cols} loading={isFetching && !rules.length} getRowId={(p) => p.data.id}
                  onRowDoubleClicked={(e) => manage && e.data && open(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">No rules yet — add one to get place entry and exit alerts.</span>' />
      </Paper>

      <EditorShell opened={!!editing} onClose={() => setEditing(null)}
                   title={<Group gap="sm"><IconBellRinging size={24} />{editing === 'new' ? 'New Notification Rule' : 'Edit Notification Rule'}</Group>}
                   onSave={manage ? () => save(false) : undefined} onSaveAndNew={manage ? () => save(true) : undefined} sections={[
        { id: 'general', label: 'General', keywords: 'name rule type vehicle group active',
          content: (
            <Stack maw={640}>
              <TextInput label="Rule name" withAsterisk placeholder="e.g. Depot arrivals and departures" {...form.getInputProps('name')} data-autofocus />
              <Select label="Rule type" allowDeselect={false} data={meta?.rule_types ?? [{ value: 'geofence', label: 'Place entry / exit' }]}
                      {...form.getInputProps('rule_type')} />
              <Select label="Vehicle group" allowDeselect={false} description="Which vehicles the rule covers"
                      data={[{ value: ALL, label: 'All vehicles' }, ...categories.map((c) => ({ value: c.name, label: c.name }))]}
                      {...form.getInputProps('category')} />
              <Switch label="Rule is active" {...form.getInputProps('is_active', { type: 'checkbox' })} />
            </Stack>
          ) },
        { id: 'watch', label: form.values.rule_type === 'event' ? 'Events' : 'Places', keywords: 'places place groups events entry exit notify',
          content: form.values.rule_type === 'event' ? (
            <Stack maw={720}>
              <Text size="sm" c="dimmed">An alert is raised every time a vehicle in the chosen vehicle group reports one of these events.
                Speeding and harsh driving come from the unit's own settings (overspeed limit, green driving).</Text>
              <MultiSelect label="Events" placeholder={form.values.event_codes.length ? '' : 'e.g. Speeding, Harsh braking'} searchable clearable
                           data={eventOptions} {...form.getInputProps('event_codes')} maxDropdownHeight={320} />
              {eventGroups.length > 0 && (
                <Select label="…and an event type group" placeholder="Optional" clearable data={eventGroups.map((g) => ({ value: g.id, label: g.name }))}
                        {...form.getInputProps('event_group_id')} />
              )}
            </Stack>
          ) : (
            <Stack maw={720}>
              <MultiSelect label="Places" placeholder={form.values.place_ids.length || form.values.place_group_ids.length ? '' : 'All places'}
                           searchable clearable data={places.map((p) => ({ value: p.id, label: p.name }))} {...form.getInputProps('place_ids')}
                           nothingFoundMessage="No places — add them under Configuration → Places" />
              {placeGroups.length > 0 && (
                <MultiSelect label="…and place groups" placeholder={form.values.place_group_ids.length ? '' : 'Optional'} searchable clearable
                             data={placeGroups.map((g) => ({ value: g.id, label: g.name }))} {...form.getInputProps('place_group_ids')} />
              )}
              <div>
                <Text size="sm" fw={500} mb={6}>Notify</Text>
                <Stack gap="xs">
                  <Checkbox label="Once when a vehicle enters a place" {...form.getInputProps('on_entry', { type: 'checkbox' })} />
                  <Checkbox label="Once when a vehicle leaves a place" {...form.getInputProps('on_exit', { type: 'checkbox' })}
                            error={form.errors.on_exit} />
                </Stack>
              </div>
            </Stack>
          ) },
        { id: 'email', label: 'Email', keywords: 'email subscribe recipients message placeholders preview',
          content: (
            <Stack maw={760}>
              <Alert variant="light" icon={<IconInfoCircle size={16} />} p="xs">
                Every notification is listed in the Inbox for users who can see the vehicle.
              </Alert>
              <Checkbox label="Subscribe by email" description="Also email these addresses with your own message"
                        {...form.getInputProps('email_enabled', { type: 'checkbox' })} />
              {form.values.email_enabled && (
                <Stack gap="sm">
                  <TagsInput label="Email addresses" placeholder="name@company.co.za — press Enter after each" splitChars={[',', ' ', ';']}
                             clearable {...form.getInputProps('email_recipients')} />
                  <Textarea ref={messageRef} label="Custom message" autosize minRows={3} maxLength={2000}
                            description="Click a field below to insert it; it's filled in from the vehicle and the event."
                            {...form.getInputProps('email_message')} />
                  <Group gap={6}>
                    {(meta?.placeholders ?? []).map((p) => (
                      <Tooltip key={p.key} label={p.label} withinPortal>
                        <Badge component="button" type="button" variant="outline" className={classes.chip} onClick={() => insert(p.key)}>
                          {`{${p.key}}`}
                        </Badge>
                      </Tooltip>
                    ))}
                  </Group>
                  <Paper p="sm" radius="md" className={classes.preview}>
                    <Text size="xs" c="dimmed" mb={4}>Preview{sample ? ` (with ${vehicleName(sample)})` : ''}</Text>
                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{preview}</Text>
                  </Paper>
                </Stack>
              )}
            </Stack>
          ) },
      ]} />
    </Stack>
  );
}
