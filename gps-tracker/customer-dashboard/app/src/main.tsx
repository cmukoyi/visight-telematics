import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import './styles.css';
import { theme } from './theme';
import { App } from './App';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 } },
});

// Old bookmarks like //customer/index.html don't match the router's basename and
// would render a blank page; normalise them to /customer/... first.
const cleanPath = window.location.pathname.replace(/\/{2,}/g, '/').replace(/\/index\.html$/, '/');
if (cleanPath !== window.location.pathname) {
  window.history.replaceState(null, '', cleanPath + window.location.search.replace(/^\?$/, '') + window.location.hash);
}

const colorSchemeManager = localStorageColorSchemeManager({ key: 'vt-color-scheme' });

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark" colorSchemeManager={colorSchemeManager}>
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/customer" future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <ModalsProvider><App /></ModalsProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
