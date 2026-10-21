import { forwardRef } from 'react';
import { AgGridReact, type AgGridReactProps } from 'ag-grid-react';
import { useComputedColorScheme } from '@mantine/core';

/** AG Grid with the app's theme (quartz, light/dark) and sensible defaults. */
export const DataGrid = forwardRef<AgGridReact, AgGridReactProps & { height?: number | string }>(function DataGrid(
  { height = '100%', defaultColDef, ...props }, ref,
) {
  const scheme = useComputedColorScheme('dark');
  return (
    <div className={`${scheme === 'dark' ? 'ag-theme-quartz-dark' : 'ag-theme-quartz'} vt-grid`} style={{ height, width: '100%' }}>
      <AgGridReact
        ref={ref}
        animateRows
        rowHeight={40}
        headerHeight={42}
        suppressCellFocus
        defaultColDef={{ sortable: true, resizable: true, filter: true, minWidth: 90, ...defaultColDef }}
        overlayNoRowsTemplate='<span style="opacity:.7">Nothing to show for these filters.</span>'
        {...props}
      />
    </div>
  );
});
