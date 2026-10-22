import { useMemo, useState } from 'react';
import { Badge, Code, Drawer, Group, Paper, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { useAudit, usePortalUsers, useCan } from '../api/hooks';
import type { AuditRow } from '../api/types';
import { DataGrid } from '../components/DataGrid';
import { RangePicker, defaultRange } from '../components/RangePicker';
import { dateTime } from '../utils/format';
import classes from './SecurityPage.module.css';

const OUTCOME: Record<AuditRow['outcome'], { label: string; color: string }> = {
  success: { label: 'Done', color: 'green' },
  denied: { label: 'Not allowed', color: 'orange' },
  failed: { label: 'Failed', color: 'red' },
};

function Detail({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <Text size="sm" c="dimmed">—</Text>;
  if (Array.isArray(value)) return <Text size="sm">{value.map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ') || '—'}</Text>;
  if (typeof value === 'object') return <Code block>{JSON.stringify(value, null, 2)}</Code>;
  return <Text size="sm" style={{ wordBreak: 'break-word' }}>{String(value)}</Text>;
}

/** Configuration → Security → Audit Trail: who changed what in this user group, and when. */
export function AuditTrail() {
  const [range, setRange] = useState(defaultRange);
  const [userId, setUserId] = useState<string | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [debounced] = useDebouncedValue(search, 300);
  const [open, setOpen] = useState<AuditRow | null>(null);
  const can = useCan();
  const { data: users = [] } = usePortalUsers(can('users.view') || can('users.manage'));
  const { data, isFetching } = useAudit({ date_from: range.from.toISOString(), date_to: range.to.toISOString(), user_id: userId,
                                          area, outcome, search: debounced || undefined });
  const rows = data?.rows ?? [];
  const cols = useMemo<ColDef<AuditRow>[]>(() => [
    { colId: 'mark', headerName: '', width: 54, minWidth: 54, sortable: false, filter: false, pinned: 'left', lockPosition: 'left',
      cellRenderer: (p: ICellRendererParams<AuditRow>) => p.data &&
        <Badge size="xs" circle variant="filled" color={OUTCOME[p.data.outcome]?.color ?? 'gray'} title={OUTCOME[p.data.outcome]?.label}> </Badge> },
    { colId: 'when', headerName: 'When', field: 'created_at', valueFormatter: (p) => dateTime(p.value), width: 175, sort: 'desc' },
    { colId: 'user', headerName: 'User', valueGetter: (p) => p.data?.user_name || p.data?.user_email || '—', flex: 1, minWidth: 170,
      tooltipValueGetter: (p) => p.data?.user_email ?? '' },
    { colId: 'area', headerName: 'Area', field: 'area', width: 160 },
    { colId: 'summary', headerName: 'What happened', field: 'summary', flex: 2, minWidth: 260 },
    { colId: 'outcome', headerName: 'Result', field: 'outcome', width: 130,
      cellRenderer: (p: ICellRendererParams<AuditRow>) => p.data &&
        <Badge size="sm" variant="light" color={OUTCOME[p.data.outcome]?.color ?? 'gray'}>{OUTCOME[p.data.outcome]?.label ?? p.data.outcome}</Badge> },
    { colId: 'ip', headerName: 'IP address', field: 'ip_address', width: 140, hide: true },
  ], []);

  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap">
        <RangePicker value={range} onChange={setRange} />
        <Select size="xs" w={220} placeholder="All users" clearable searchable value={userId} onChange={setUserId}
                data={users.map((u) => ({ value: u.id, label: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email }))} />
        <Select size="xs" w={190} placeholder="All areas" clearable value={area} onChange={setArea} data={data?.areas ?? []} />
        <Select size="xs" w={150} placeholder="Any result" clearable value={outcome} onChange={setOutcome}
                data={Object.entries(OUTCOME).map(([value, o]) => ({ value, label: o.label }))} />
        <TextInput size="xs" w={240} placeholder="Search what happened or who" leftSection={<IconSearch size={14} />}
                   value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
        <Text size="sm" c="dimmed">{rows.length} entries</Text>
      </Group>
      <Paper withBorder className={classes.grid}>
        <DataGrid rowData={rows} columnDefs={cols} loading={isFetching && !rows.length} getRowId={(p) => p.data.id} stateKey="config-audit"
                  onRowClicked={(e) => e.data && setOpen(e.data)}
                  overlayNoRowsTemplate='<span style="opacity:.7">Nothing recorded in this period.</span>' />
      </Paper>
      <Text size="xs" c="dimmed">Every change made in this portal is recorded, as well as sign-ins and attempts that roles don’t allow. Click an entry for details.</Text>

      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size="lg" title={<Text fw={650}>{open?.summary}</Text>}>
        {open && (
          <Stack>
            <Table withRowBorders={false} verticalSpacing={6}>
              <Table.Tbody>
                <Table.Tr><Table.Td c="dimmed" w={140}>When</Table.Td><Table.Td>{dateTime(open.created_at)}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">User</Table.Td><Table.Td>{open.user_name ? `${open.user_name} (${open.user_email})` : open.user_email}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">Area</Table.Td><Table.Td>{open.area}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">Action</Table.Td><Table.Td>{open.action}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">Result</Table.Td><Table.Td>
                  <Badge size="sm" variant="light" color={OUTCOME[open.outcome]?.color}>{OUTCOME[open.outcome]?.label}</Badge></Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">IP address</Table.Td><Table.Td>{open.ip_address || '—'}</Table.Td></Table.Tr>
              </Table.Tbody>
            </Table>
            {open.details && typeof open.details === 'object' && !Array.isArray(open.details) && Object.keys(open.details).length > 0 && (
              <>
                <Text fw={600} size="sm">What was sent</Text>
                <Table withTableBorder verticalSpacing={6}>
                  <Table.Tbody>
                    {Object.entries(open.details).map(([k, v]) => (
                      <Table.Tr key={k}><Table.Td c="dimmed" w={180}>{k.replace(/_/g, ' ')}</Table.Td><Table.Td><Detail value={v} /></Table.Td></Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </>
            )}
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}
