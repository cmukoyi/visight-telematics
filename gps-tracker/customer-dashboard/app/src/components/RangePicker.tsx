import { Button, Group, Menu } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCalendar, IconChevronDown } from '@tabler/icons-react';
import dayjs from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import type { Range } from '../api/hooks';

dayjs.extend(isoWeek);  // weeks start on Monday

const PRESETS: { label: string; get: () => Range }[] = [
  { label: 'Today', get: () => ({ from: dayjs().startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Yesterday', get: () => ({ from: dayjs().subtract(1, 'day').startOf('day').toDate(), to: dayjs().subtract(1, 'day').endOf('day').toDate() }) },
  { label: 'Last 7 days', get: () => ({ from: dayjs().subtract(6, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'This week', get: () => ({ from: dayjs().startOf('isoWeek').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Last week', get: () => ({ from: dayjs().startOf('isoWeek').subtract(7, 'day').toDate(), to: dayjs().startOf('isoWeek').toDate() }) },
  { label: 'This month', get: () => ({ from: dayjs().startOf('month').toDate(), to: dayjs().endOf('day').toDate() }) },
  { label: 'Last 30 days', get: () => ({ from: dayjs().subtract(29, 'day').startOf('day').toDate(), to: dayjs().endOf('day').toDate() }) },
];

export const defaultRange = (): Range => PRESETS[2].get();

export function RangePicker({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  return (
    <Group gap={6} wrap="nowrap">
      <DatePickerInput
        type="range"
        size="sm"
        leftSection={<IconCalendar size={16} />}
        value={[value.from, value.to]}
        valueFormat="DD MMM YYYY"
        maxDate={new Date()}
        onChange={([from, to]) => { if (from && to) onChange({ from: dayjs(from).startOf('day').toDate(), to: dayjs(to).endOf('day').toDate() }); }}
        w={250}
        aria-label="Date range"
      />
      <Menu position="bottom-end">
        <Menu.Target>
          <Button variant="default" size="sm" rightSection={<IconChevronDown size={14} />}>Quick</Button>
        </Menu.Target>
        <Menu.Dropdown>
          {PRESETS.map((p) => <Menu.Item key={p.label} onClick={() => onChange(p.get())}>{p.label}</Menu.Item>)}
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
