import { AreaChart, BarChart, DonutChart, LineChart, PieChart } from '@mantine/charts';
import { Group, ScrollArea, Stack, Table, Text } from '@mantine/core';
import type { AnalyticsColumn, AnalyticsResult, Visual } from '../api/types';

// Categorical slots in fixed order (styles.css); a 9th series never gets a new hue — pies fold the tail into "Other"
export const SERIES = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)', 'var(--viz-5)', 'var(--viz-6)', 'var(--viz-7)', 'var(--viz-8)'];
const PIE_SLICES = 5;

export const HEIGHTS = { s: 150, m: 300, l: 440 } as const;

/** 1,284 · 12.9K · 4.2M; with the column's decimals below 1,000. */
export function formatValue(v: number | null | undefined, col?: AnalyticsColumn, compact = true) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (compact && abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (compact && abs >= 10_000) return `${(v / 1000).toFixed(1)}K`;
  const d = col?.decimals ?? 1;
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: d });
}
const withUnit = (text: string, col?: AnalyticsColumn) => (col?.unit ? (col.unit === 'R' ? `R ${text}` : `${text} ${col.unit}`) : text);

/** Rows as a table — every chart can be read this way too (and it's the relief for low-contrast colours). */
export function ResultTable({ result, maxHeight }: { result: AnalyticsResult; maxHeight?: number }) {
  // A list (Each trip / Each place visit) shows its text columns instead of the row label
  const info = result.info_columns ?? [];
  const dimension = result.dimension !== '' && info.length === 0;
  return (
    <ScrollArea.Autosize mah={maxHeight} type="auto">
      <Table striped highlightOnHover stickyHeader fz="sm" verticalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            {dimension && <Table.Th>{result.dimension_label}</Table.Th>}
            {info.map((c) => <Table.Th key={c.key}>{c.label}</Table.Th>)}
            {result.columns.map((c) => <Table.Th key={c.key} ta="right">{c.label}{c.unit && c.unit !== 'R' ? ` (${c.unit})` : c.unit === 'R' ? ' (R)' : ''}</Table.Th>)}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {result.rows.map((r) => (
            <Table.Tr key={r.key}>
              {dimension && <Table.Td>{r.label}</Table.Td>}
              {info.map((c) => <Table.Td key={c.key} style={{ whiteSpace: c.key === 'from' || c.key === 'to' ? 'normal' : 'nowrap' }}>{r.info?.[c.key] || '—'}</Table.Td>)}
              {result.columns.map((c) => <Table.Td key={c.key} ta="right" style={{ fontVariantNumeric: 'tabular-nums' }}>{formatValue(r.values[c.key], c, false)}</Table.Td>)}
            </Table.Tr>
          ))}
          {result.rows.length === 0 && <Table.Tr><Table.Td colSpan={result.columns.length + info.length + 1}><Text size="sm" c="dimmed">No data.</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
    </ScrollArea.Autosize>
  );
}

/** Draw one visual from its query result. */
export function VisualChart({ visual, result, height }: { visual: Visual; result: AnalyticsResult | undefined; height: number }) {
  if (visual.type === 'text') {
    return <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{visual.text || 'Add text in the visual’s Format tab.'}</Text>;
  }
  if (!result) return null;
  const cols = result.columns;
  const total = (key: string) => result.rows.reduce((a, r) => a + (r.values[key] ?? 0), 0);

  if (visual.type === 'kpi') {
    // A figure: the first value (for a breakdown, the first row) — exactly one hero number per tile
    const col = cols[0];
    const value = result.dimension === '' ? result.rows[0]?.values[col.key] ?? null : total(col.key);
    return (
      <Stack gap={2} justify="center" h={height}>
        <Text fz={`clamp(28px, 3.4vw, ${Math.min(52, height / 2.6)}px)`} fw={650} lh={1.05} style={{ whiteSpace: 'nowrap' }}>
          {col.unit === 'R' && <Text span inherit c="dimmed" fz="0.55em" mr={4}>R</Text>}
          {formatValue(value, col)}
          {col.unit && col.unit !== 'R' && <Text span inherit c="dimmed" fz="0.45em" ml={6}>{col.unit}</Text>}
        </Text>
        <Text size="sm" c="dimmed">{col.label}</Text>
        {cols.slice(1, 3).map((c) => (
          <Group key={c.key} gap={6}><Text size="sm" c="dimmed">{c.label}</Text>
            <Text size="sm" fw={600}>{withUnit(formatValue(result.dimension === '' ? result.rows[0]?.values[c.key] : total(c.key), c), c)}</Text></Group>
        ))}
      </Stack>
    );
  }
  if (visual.type === 'table') return <ResultTable result={result} maxHeight={height} />;
  if (result.rows.length === 0) return <Text size="sm" c="dimmed">No data in this period.</Text>;

  const data = result.rows.map((r) => ({ label: r.label, ...Object.fromEntries(cols.map((c) => [c.key, r.values[c.key] ?? 0])) }));
  const series = cols.map((c, i) => ({ name: c.key, label: c.unit && c.unit !== 'R' ? `${c.label} (${c.unit})` : c.label, color: SERIES[i % SERIES.length] }));
  const legend = cols.length > 1;   // one series: the title says what it is
  const fmt = (v: number) => formatValue(v, cols[0]);
  const common = {
    h: height, data, dataKey: 'label', series, valueFormatter: fmt, withLegend: legend,
    // Mantine's gridAxis names the axis the lines run along: 'x' = horizontal lines (for columns and lines)
    legendProps: { verticalAlign: 'top' as const, height: 36 }, gridAxis: 'x' as const, strokeDasharray: '0',
    tickLine: 'none' as const, withTooltip: true, tooltipAnimationDuration: 120,
  };

  if (visual.type === 'pie' || visual.type === 'donut') {
    const col = cols[0];
    const sorted = [...result.rows].sort((a, b) => (b.values[col.key] ?? 0) - (a.values[col.key] ?? 0)).filter((r) => (r.values[col.key] ?? 0) > 0);
    const head = sorted.slice(0, PIE_SLICES);
    const rest = sorted.slice(PIE_SLICES).reduce((a, r) => a + (r.values[col.key] ?? 0), 0);
    const slices = [...head.map((r, i) => ({ name: r.label, value: r.values[col.key] ?? 0, color: SERIES[i] })),
                    ...(rest > 0 ? [{ name: 'Other', value: rest, color: 'var(--viz-other)' }] : [])];
    if (slices.length < 2) return <ResultTable result={result} maxHeight={height} />;   // a one-slice pie is just a number
    const size = Math.min(height - 40, 190);
    const Chart = visual.type === 'pie' ? PieChart : DonutChart;
    const sum = slices.reduce((a, s) => a + s.value, 0);
    return (
      <Group wrap="nowrap" align="center" h={height} gap="lg">
        <Chart data={slices} size={size} withTooltip tooltipDataSource="segment" valueFormatter={fmt} strokeWidth={2}
               strokeColor="var(--mantine-color-body)" {...(visual.type === 'donut' ? { thickness: Math.max(18, size / 7) } : {})} />
        <Stack gap={6} style={{ minWidth: 110, flex: 1 }}>
          {slices.map((s) => (
            <Group key={s.name} gap={8} wrap="nowrap">
              <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, flex: 'none' }} />
              <Text size="sm" truncate style={{ flex: 1 }}>{s.name}</Text>
              <Text size="sm" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums' }}>{Math.round((s.value / sum) * 100)}%</Text>
            </Group>
          ))}
        </Stack>
      </Group>
    );
  }
  if (visual.type === 'line') {
    return <LineChart {...common} curveType="monotone" strokeWidth={2} dotProps={{ r: 4, strokeWidth: 2, stroke: 'var(--mantine-color-body)' }} />;
  }
  if (visual.type === 'area') {
    return <AreaChart {...common} curveType="monotone" strokeWidth={2} fillOpacity={0.1} withGradient={false} />;
  }
  const horizontal = visual.type === 'bar';
  return (
    <BarChart {...common} type={visual.type === 'stacked' ? 'stacked' : 'default'} orientation={horizontal ? 'vertical' : 'horizontal'}
              gridAxis={horizontal ? 'y' : 'x'} maxBarWidth={24} withBarValueLabel={!!visual.show_values && visual.type !== 'stacked'}
              barProps={{ radius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0], stroke: 'var(--mantine-color-body)', strokeWidth: visual.type === 'stacked' ? 2 : 0 }}
              {...(horizontal ? { yAxisProps: { width: 120 } } : {})} />
  );
}
