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
import { useThemeTrial } from './utils/themeTrial';
import { App } from './App';
import { I18nProvider, storedLanguage } from './i18n';
import { useMe } from './api/hooks';
import { getSession } from './auth/session';

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

/** The signed-in user's language (from /me), else the last one used in this browser. */
function Localised({ children }: { children: React.ReactNode }) {
  const signedIn = !!getSession().token;
  const { data: me } = useMe();
  const lang = (signedIn && (me?.access.language || getSession().access?.language)) || storedLanguage();
  return <I18nProvider lang={lang}>{children}</I18nProvider>;
}

function Root() {
  // The group's look and timezone (refetched when the user signs in or out).
  const { data: groupTheme } = useGroupTheme();
  const [cached] = useState(cachedLook);
  // A look being tried in this browser (Custom Themes → Try in this browser) wins over the saved one
  const trial = useThemeTrial();
  const saved: Look | null = groupTheme ?? cached;
  const look: Look | null = trial ? { ...saved, timezone: saved?.timezone ?? null, ...trial } : saved;
  useEffect(() => { if (groupTheme) saveLook(groupTheme); }, [groupTheme]);
  const settings = look?.theme_settings ?? null;
  useEffect(() => {
    if (settings?.style === 'night') document.documentElement.dataset.vtStyle = 'night';
    else delete document.documentElement.dataset.vtStyle;
  }, [settings?.style]);
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
        <ModalsProvider><Localised><App /></Localised></ModalsProvider>
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
