import { useMemo, useState, type ReactNode } from 'react';
import { Badge, Checkbox, CloseButton, Group, Radio, ScrollArea, Stack, Switch, Text, TextInput, UnstyledButton } from '@mantine/core';
import { IconCheck, IconSearch, IconX } from '@tabler/icons-react';
import type { Permission } from '../api/types';
import classes from './FeaturePicker.module.css';

export interface CheckItem { value: string; label: string; description?: string; extra?: ReactNode; disabled?: boolean }
type Show = 'all' | 'selected' | 'unselected';

/** A searchable checkbox list with Show: All / Selected / Unselected, and optionally Select all / none. */
export function CheckList({ items, value, onChange, readOnly, height = 360, selectAll = true, empty = 'Nothing matches.' }: {
  items: CheckItem[]; value: string[]; onChange: (v: string[]) => void; readOnly?: boolean; height?: number;
  selectAll?: boolean; empty?: string;
}) {
  const [search, setSearch] = useState('');
  const [show, setShow] = useState<Show>('all');
  const chosen = new Set(value);
  const q = search.trim().toLowerCase();
  const shown = items.filter((i) => (!q || `${i.label} ${i.description ?? ''}`.toLowerCase().includes(q))
    && (show === 'all' || (show === 'selected') === chosen.has(i.value)));
  const toggle = (v: string) => onChange(chosen.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  const editable = shown.filter((i) => !i.disabled).map((i) => i.value);
  return (
    <Stack gap="sm">
      {selectAll && !readOnly && (
        <Group justify="flex-end" gap="md">
          <Checkbox size="xs" label="Select all" checked={editable.length > 0 && editable.every((v) => chosen.has(v))}
                    onChange={() => onChange([...new Set([...value, ...editable])])} />
          <Text c="dimmed">/</Text>
          <Checkbox size="xs" label="Select none" checked={editable.every((v) => !chosen.has(v))}
                    onChange={() => onChange(value.filter((v) => !editable.includes(v)))} />
        </Group>
      )}
      <TextInput radius="xl" placeholder="Search" leftSection={<IconSearch size={15} />} value={search}
                 onChange={(e) => setSearch(e.currentTarget.value)}
                 rightSection={search ? <CloseButton size="sm" onClick={() => setSearch('')} aria-label="Clear search" /> : null} />
      <Radio.Group value={show} onChange={(v) => setShow(v as Show)}>
        <Group gap="lg">
          <Text size="sm">Show:</Text>
          <Radio size="sm" value="all" label="All" />
          <Radio size="sm" value="selected" label={`Selected (${value.length})`} />
          <Radio size="sm" value="unselected" label="Unselected" />
        </Group>
      </Radio.Group>
      <ScrollArea.Autosize mah={height} type="auto" className={classes.list}>
        {shown.length === 0 && <Text size="sm" c="dimmed" p="md">{empty}</Text>}
        {shown.map((i) => (
          <div key={i.value} className={classes.item}>
            <Checkbox mt={2} radius="sm" checked={chosen.has(i.value)} disabled={readOnly || i.disabled} onChange={() => toggle(i.value)}
                      aria-label={i.label} />
            <div style={{ minWidth: 0, flex: 1, cursor: readOnly || i.disabled ? undefined : 'pointer' }}
                 onClick={() => !readOnly && !i.disabled && toggle(i.value)}>
              <Group gap={6}><Text size="sm" fw={500}>{i.label}</Text>{i.extra}</Group>
              {i.description && <Text size="xs" c="dimmed">{i.description}</Text>}
            </div>
          </div>
        ))}
      </ScrollArea.Autosize>
    </Stack>
  );
}

/** Role editor → Features: the areas on the left, that area's features (with what they allow) on the right. */
export function FeaturePicker({ permissions, value, onChange, readOnly, lockedReason }: {
  permissions: Permission[]; value: string[]; onChange: (v: string[]) => void; readOnly?: boolean;
  /** Features that can't be ticked, with why (e.g. you don't have them yourself). */
  lockedReason?: (key: string) => string | null;
}) {
  const sections = useMemo(() => [...new Set(permissions.map((p) => p.section))], [permissions]);
  const [cat, setCat] = useState<string>('All');
  const chosen = new Set(value);
  const inCat = permissions.filter((p) => cat === 'All' || p.section === cat);
  const count = (s: string) => permissions.filter((p) => p.section === s && chosen.has(p.key)).length;
  return (
    <div className={classes.picker}>
      <div className={classes.cats}>
        {['All', ...sections].map((s) => (
          <UnstyledButton key={s} className={classes.cat} data-active={cat === s || undefined} onClick={() => setCat(s)}>
            <span>{s}</span>
            <Badge size="sm" variant={s === 'All' ? 'filled' : 'light'} color={(s === 'All' ? value.length : count(s)) ? 'brand' : 'gray'}>
              {s === 'All' ? `${value.length}/${permissions.length}` : `${count(s)}/${permissions.filter((p) => p.section === s).length}`}
            </Badge>
          </UnstyledButton>
        ))}
      </div>
      <CheckList readOnly={readOnly} value={value} onChange={onChange} height={440}
                 items={inCat.map((p) => {
                   const locked = lockedReason?.(p.key);
                   return { value: p.key, label: p.label, description: locked ? `${p.description} ${locked}` : p.description,
                            disabled: !!locked && !chosen.has(p.key),
                            extra: cat === 'All' ? <Badge size="xs" variant="default">{p.section}</Badge> : undefined };
                 })} />
    </div>
  );
}

/** What a set of permissions allows, grouped by area, with what isn't included on request. */
export function FeatureSummary({ permissions, granted, admin, height = 420 }: {
  permissions: Permission[]; granted: string[]; admin?: boolean; height?: number;
}) {
  const [showMissing, setShowMissing] = useState(false);
  const [search, setSearch] = useState('');
  const has = new Set(admin ? permissions.map((p) => p.key) : granted);
  const sections = [...new Set(permissions.map((p) => p.section))];
  const q = search.trim().toLowerCase();
  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <Text fw={600}>Features <Text span c="dimmed" size="sm">({has.size} of {permissions.length})</Text></Text>
        <TextInput size="xs" radius="xl" w={180} placeholder="Search" leftSection={<IconSearch size={13} />} value={search}
                   onChange={(e) => setSearch(e.currentTarget.value)} />
      </Group>
      {admin && <Text size="xs" c="dimmed">Administrator: every feature, and every vehicle in the user group.</Text>}
      <ScrollArea.Autosize mah={height} type="auto" className={classes.summary}>
        {sections.map((s) => {
          const rows = permissions.filter((p) => p.section === s && (showMissing || has.has(p.key))
            && (!q || `${p.label} ${p.description}`.toLowerCase().includes(q)));
          if (!rows.length) return null;
          return (
            <div key={s}>
              <div className={classes.sumSection}>{s}</div>
              {rows.map((p) => (
                <div key={p.key} className={classes.sumItem}>
                  {has.has(p.key) ? <IconCheck size={15} className={classes.yes} /> : <IconX size={15} className={classes.no} />}
                  <div>
                    <Text size="sm" c={has.has(p.key) ? undefined : 'dimmed'}>{p.label}</Text>
                    <Text size="xs" c="dimmed">{p.description}</Text>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
        {has.size === 0 && !showMissing && <Text size="sm" c="dimmed" p="md">No features yet — tick a role.</Text>}
      </ScrollArea.Autosize>
      <Switch size="xs" label="Also show what isn't included" checked={showMissing} onChange={(e) => setShowMissing(e.currentTarget.checked)} />
    </Stack>
  );
}
