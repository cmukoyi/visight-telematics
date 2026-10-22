import { forwardRef, useCallback, useImperativeHandle, useRef, useState } from 'react';
import { AgGridReact, type AgGridReactProps } from 'ag-grid-react';
import type { ColumnState, GridApi, GridReadyEvent } from 'ag-grid-community';
import { ActionIcon, Button, Checkbox, Divider, Popover, ScrollArea, Stack, Text, Tooltip, useComputedColorScheme } from '@mantine/core';
import { IconSettings } from '@tabler/icons-react';
import classes from './DataGrid.module.css';

type Props = AgGridReactProps & {
  height?: number | string;
  /** Remember column order, widths, visibility and sort under this key, and show the column settings (gear). */
  stateKey?: string;
};

const storageKey = (k: string) => `vt-grid-${k}`;

function loadState(key: string): ColumnState[] | null {
  try { return JSON.parse(localStorage.getItem(storageKey(key)) || 'null'); } catch { return null; }
}

/** Show / hide columns and reset the layout. Columns can also be dragged by their headers to reorder them. */
function ColumnSettings({ api, onReset }: { api: GridApi | null; onReset: () => void }) {
  const [, refresh] = useState(0);
  const columns = (api?.getColumns() ?? []).filter((c) => c.getColDef().headerName);
  return (
    <Popover position="bottom-start" shadow="md" width={240} withinPortal onOpen={() => refresh((n) => n + 1)}>
      <Popover.Target>
        <Tooltip label="Columns" withinPortal>
          <ActionIcon size="sm" variant="subtle" color="gray" className={classes.gear} aria-label="Column settings">
            <IconSettings size={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6}>Columns</Text>
        <ScrollArea.Autosize mah={320} type="auto">
          <Stack gap={6}>
            {columns.map((c) => (
              <Checkbox key={c.getColId()} size="xs" label={c.getColDef().headerName} checked={c.isVisible()}
                        onChange={(e) => { api?.setColumnsVisible([c], e.currentTarget.checked); refresh((n) => n + 1); }} />
            ))}
          </Stack>
        </ScrollArea.Autosize>
        <Divider my="xs" />
        <Text size="xs" c="dimmed" mb={6}>Drag column headers to change their order.</Text>
        <Button size="compact-xs" variant="subtle" color="gray" onClick={() => { onReset(); refresh((n) => n + 1); }}>Reset columns</Button>
      </Popover.Dropdown>
    </Popover>
  );
}

/** AG Grid with the app's theme (quartz, light/dark) and sensible defaults. */
export const DataGrid = forwardRef<AgGridReact, Props>(function DataGrid(
  { height = '100%', defaultColDef, stateKey, onGridReady, ...props }, ref,
) {
  const scheme = useComputedColorScheme('dark');
  const inner = useRef<AgGridReact>(null);
  const [api, setApi] = useState<GridApi | null>(null);
  useImperativeHandle(ref, () => inner.current as AgGridReact);

  const save = useCallback((e: { api: GridApi }) => {
    if (!stateKey) return;
    try { localStorage.setItem(storageKey(stateKey), JSON.stringify(e.api.getColumnState())); } catch { /* storage blocked */ }
  }, [stateKey]);

  const ready = (e: GridReadyEvent) => {
    setApi(e.api);
    const saved = stateKey ? loadState(stateKey) : null;
    if (saved) e.api.applyColumnState({ state: saved, applyOrder: true });
    onGridReady?.(e);
  };
  const reset = () => {
    api?.resetColumnState();
    if (stateKey) try { localStorage.removeItem(storageKey(stateKey)); } catch { /* storage blocked */ }
  };

  return (
    <div className={`${scheme === 'dark' ? 'ag-theme-quartz-dark' : 'ag-theme-quartz'} vt-grid ${classes.wrap}`} style={{ height, width: '100%' }}>
      {stateKey && <ColumnSettings api={api} onReset={reset} />}
      <AgGridReact
        ref={inner}
        animateRows
        rowHeight={40}
        headerHeight={42}
        suppressCellFocus
        defaultColDef={{ sortable: true, resizable: true, filter: true, minWidth: 90, ...defaultColDef }}
        overlayNoRowsTemplate='<span style="opacity:.7">Nothing to show for these filters.</span>'
        onGridReady={ready}
        onColumnMoved={(e) => e.finished && save(e)}
        onColumnResized={(e) => e.finished && save(e)}
        onColumnVisible={save}
        onSortChanged={save}
        {...props}
      />
    </div>
  );
});
