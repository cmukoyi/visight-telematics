import React, { useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/charts/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import './styles.css';
import { useGroupTheme } from './api/hooks';
import { buildTheme, cssVariables, loadFont } from './theme';
import { setDisplayTimezone } from './utils/format';
import { cachedLook, saveLook, type Look } from './utils/look';
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

function Root() {
  // The group's look and timezone (refetched when the user signs in or out).
  const { data: groupTheme } = useGroupTheme();
  const [cached] = useState(cachedLook);
  const look: Look | null = groupTheme ?? cached;
  useEffect(() => { if (groupTheme) saveLook(groupTheme); }, [groupTheme]);
  const settings = look?.theme_settings ?? null;
  const appTheme = useMemo(() => buildTheme({ primary: look?.theme_primary, secondary: look?.theme_accent, settings }),
    [look?.theme_primary, look?.theme_accent, JSON.stringify(settings)]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadFont(settings?.font); }, [settings?.font]);
  setDisplayTimezone(look?.timezone);
  const scheme = settings?.color_scheme ?? 'dark';
  return (
    <MantineProvider theme={appTheme} cssVariablesResolver={cssVariables} defaultColorScheme={scheme}
                     forceColorScheme={settings?.lock_scheme ? scheme : undefined} colorSchemeManager={colorSchemeManager}>
      <Notifications position="top-right" />
      <BrowserRouter basename="/customer" future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ModalsProvider><App /></ModalsProvider>
      </BrowserRouter>
    </MantineProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  </React.StrictMode>,
);
