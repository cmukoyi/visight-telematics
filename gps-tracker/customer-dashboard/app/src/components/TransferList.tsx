import { useMemo, useState } from 'react';
import { Button, Group, Paper, ScrollArea, Select, Stack, Text, TextInput, UnstyledButton } from '@mantine/core';
import { IconChevronLeft, IconChevronRight, IconChevronsLeft, IconChevronsRight, IconSearch } from '@tabler/icons-react';
import classes from './TransferList.module.css';

export interface TransferItem { value: string; label: string; group: string | null; type: string | null }

const LIMIT = 1000;

/**
 * Two lists — Available and Selected — with Add All » / Add » / « Remove / « Remove All.
 * Available can be narrowed by group, type and a search; click (or Ctrl/⌘-click, Shift-click) to pick rows.
 */
export function TransferList({ items, value, onChange, groups, types, height = 300 }: {
  items: TransferItem[]; value: string[]; onChange: (v: string[]) => void;
  groups: string[]; types: { value: string; label: string }[]; height?: number;
}) {
  const [group, setGroup] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [pickA, setPickA] = useState<string[]>([]);
  const [pickS, setPickS] = useState<string[]>([]);
  const chosen = useMemo(() => new Set(value), [value]);
  const q = search.trim().toLowerCase();
  const available = items.filter((i) => !chosen.has(i.value) && (!group || i.group === group) && (!type || i.type === type)
    && (!q || i.label.toLowerCase().includes(q)));
  const selected = items.filter((i) => chosen.has(i.value)).sort((a, b) => a.label.localeCompare(b.label));
  const shown = available.slice(0, LIMIT);

  const add = (vals: string[]) => { onChange([...value, ...vals.filter((v) => !chosen.has(v))]); setPickA([]); };
  const remove = (vals: string[]) => { const out = new Set(vals); onChange(value.filter((v) => !out.has(v))); setPickS([]); };

  const list = (rows: TransferItem[], picked: string[], setPicked: (v: string[]) => void, onDouble: (v: string) => void) => (
    <ScrollArea h={height} type="auto" className={classes.list}>
      {rows.map((r, i) => (
        <UnstyledButton key={r.value} className={classes.row} data-picked={picked.includes(r.value) || undefined}
                        onDoubleClick={() => onDouble(r.value)}
                        onClick={(e) => {
                          if (e.metaKey || e.ctrlKey) setPicked(picked.includes(r.value) ? picked.filter((x) => x !== r.value) : [...picked, r.value]);
                          else if (e.shiftKey && picked.length) {
                            const from = rows.findIndex((x) => x.value === picked[picked.length - 1]);
                            const [a, b] = [Math.min(from, i), Math.max(from, i)];
                            setPicked([...new Set([...picked, ...rows.slice(a, b + 1).map((x) => x.value)])]);
                          } else setPicked([r.value]);
                        }}>
          <Text size="sm" truncate>{r.label}</Text>
          {(r.group || r.type) && <Text size="xs" c="dimmed" truncate>{[r.group, r.type].filter(Boolean).join(' · ')}</Text>}
        </UnstyledButton>
      ))}
      {!rows.length && <Text size="sm" c="dimmed" p="sm">None</Text>}
    </ScrollArea>
  );

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap">
        <Select size="xs" w={180} placeholder="All vehicle groups" clearable data={groups} value={group} onChange={setGroup} aria-label="Vehicle group" />
        <TextInput size="xs" w={200} placeholder="Search" leftSection={<IconSearch size={13} />} value={search}
                   onChange={(e) => setSearch(e.currentTarget.value)} aria-label="Search vehicles" />
        <Select size="xs" w={170} placeholder="All vehicle types" clearable data={types} value={type} onChange={setType} aria-label="Vehicle type" />
      </Group>
      <div className={classes.panes}>
        <Paper withBorder radius="md" className={classes.pane}>
          <Text size="sm" fw={600} className={classes.head}>Available Vehicles <Text span c="dimmed" size="xs">({available.length})</Text></Text>
          {list(shown, pickA, setPickA, (v) => add([v]))}
          {available.length > LIMIT && <Text size="xs" c="dimmed" px="sm" py={4}>Showing first {LIMIT} entries — narrow with the filters.</Text>}
        </Paper>
        <Stack gap={6} justify="center" className={classes.buttons}>
          <Button size="xs" variant="default" rightSection={<IconChevronsRight size={14} />} onClick={() => add(available.map((i) => i.value))}
                  disabled={!available.length}>Add All</Button>
          <Button size="xs" variant="default" rightSection={<IconChevronRight size={14} />} onClick={() => add(pickA)} disabled={!pickA.length}>Add</Button>
          <Button size="xs" variant="default" leftSection={<IconChevronLeft size={14} />} onClick={() => remove(pickS)} disabled={!pickS.length}>Remove</Button>
          <Button size="xs" variant="default" leftSection={<IconChevronsLeft size={14} />} onClick={() => remove(value)} disabled={!value.length}>Remove All</Button>
        </Stack>
        <Paper withBorder radius="md" className={classes.pane}>
          <Text size="sm" fw={600} className={classes.head}>Selected Vehicles <Text span c="dimmed" size="xs">({selected.length})</Text></Text>
          {list(selected, pickS, setPickS, (v) => remove([v]))}
        </Paper>
      </div>
      <Text size="xs" c="dimmed">Click to pick, Ctrl/⌘ or Shift to pick several, double-click to move one.</Text>
    </Stack>
  );
}
