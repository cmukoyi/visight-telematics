import { useState } from 'react';
import { Button, Divider, Group, Popover, Stack, Text, UnstyledButton } from '@mantine/core';
import { DatePicker } from '@mantine/dates';
import { useMediaQuery } from '@mantine/hooks';
import { IconCalendar, IconChevronDown } from '@tabler/icons-react';
import dayjs from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import type { Range } from '../api/hooks';
import classes from './RangePicker.module.css';

dayjs.extend(isoWeek);  // weeks start on Monday

const PRESETS: { label: string; get: () => Range }[] = [
  { label: 'Today', get: () => ({ from: dayjs().startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Yesterday', get: () => ({ from: dayjs().subtract(1, 'day').startOf('day').toDate(), to: dayjs().subtract(1, 'day').endOf('day').toDate() }) },
  { label: 'Last 7 days', get: () => ({ from: dayjs().subtract(6, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'This week', get: () => ({ from: dayjs().startOf('isoWeek').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Last week', get: () => ({ from: dayjs().startOf('isoWeek').subtract(7, 'day').toDate(), to: dayjs().startOf('isoWeek').subtract(1, 'day').endOf('day').toDate() }) },
  { label: 'This month', get: () => ({ from: dayjs().startOf('month').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Last month', get: () => ({ from: dayjs().subtract(1, 'month').startOf('month').toDate(), to: dayjs().subtract(1, 'month').endOf('month').toDate() }) },
  { label: 'Last 30 days', get: () => ({ from: dayjs().subtract(29, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Last 90 days', get: () => ({ from: dayjs().subtract(89, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
];

export const defaultRange = (): Range => PRESETS[2].get();

const sameDays = (a: Range, b: Range) => dayjs(a.from).isSame(b.from, 'day') && dayjs(a.to).isSame(b.to, 'day');
const span = (r: Range) => {
  const from = dayjs(r.from), to = dayjs(r.to);
  if (from.isSame(to, 'day')) return from.format('D MMM YYYY');
  return `${from.format(from.isSame(to, 'year') ? 'D MMM' : 'D MMM YYYY')} – ${to.format('D MMM YYYY')}`;
};

/** A period: quick choices (Today, Last 7 days …) or any two dates on the calendar (click the start, then the end). */
export function RangePicker({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const narrow = useMediaQuery('(max-width: 48em)');
  const [opened, setOpened] = useState(false);
  const [draft, setDraft] = useState<[Date | null, Date | null]>([value.from, value.to]);
  const preset = PRESETS.find((p) => sameDays(p.get(), value));

  const open = () => { setDraft([value.from, value.to]); setOpened(true); };
  const apply = (r: Range) => { onChange(r); setOpened(false); };
  // The first click sets the start (kept as a draft), the second the end — then the period applies
  const pick = ([from, to]: [Date | null, Date | null]) => {
    setDraft([from, to]);
    if (from && to) apply({ from: dayjs(from).startOf('day').toDate(), to: dayjs(to).endOf('day').toDate() });
  };

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" shadow="md" withinPortal trapFocus>
      <Popover.Target>
        <Button variant="default" size="sm" leftSection={<IconCalendar size={16} />} rightSection={<IconChevronDown size={14} />}
                onClick={() => (opened ? setOpened(false) : open())} aria-label="Date range" className={classes.target}>
          {preset ? <><b>{preset.label}</b>&nbsp;<Text span c="dimmed" size="sm">· {span(value)}</Text></> : span(value)}
        </Button>
      </Popover.Target>
      <Popover.Dropdown p="sm">
        <Group align="flex-start" gap="sm" wrap={narrow ? 'wrap' : 'nowrap'}>
          <Stack gap={2} className={classes.presets}>
            {PRESETS.map((p) => (
              <UnstyledButton key={p.label} className={classes.preset} data-active={p === preset || undefined}
                              onClick={() => apply(p.get())}>{p.label}</UnstyledButton>
            ))}
          </Stack>
          {!narrow && <Divider orientation="vertical" />}
          <Stack gap={6}>
            <DatePicker type="range" allowSingleDateInRange numberOfColumns={narrow ? 1 : 2} value={draft} onChange={pick}
                        maxDate={new Date()} defaultDate={dayjs(value.to).subtract(narrow ? 0 : 1, 'month').toDate()} />
            <Text size="xs" c="dimmed">
              {draft[0] && !draft[1] ? `From ${dayjs(draft[0]).format('D MMM YYYY')} — now click the end date` : 'Click a start date, then an end date'}
            </Text>
          </Stack>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
}
