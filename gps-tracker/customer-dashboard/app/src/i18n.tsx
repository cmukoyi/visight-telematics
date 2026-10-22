import { createContext, useCallback, useContext, useEffect, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

/**
 * Translations for the app, managed in the admin portal (Languages / Translations).
 *
 * Write text as t('app.<area>.<name>', 'English text') — or msg(...) in constants —
 * with literal arguments: on deploy, app/sync_dashboard_translation_keys.py scans
 * this source for those calls, adds the keys to the admin portal and translates
 * them into every active language. {name} in the text is filled from vars.
 */
export interface Msg { key: string; text: string }
export const msg = (key: string, text: string): Msg => ({ key, text });

const LANG_KEY = 'vt-language';
export const storedLanguage = () => { try { return localStorage.getItem(LANG_KEY) || 'en'; } catch { return 'en'; } };

type Dict = Record<string, string>;
const I18nContext = createContext<{ lang: string; dict: Dict }>({ lang: 'en', dict: {} });

export function I18nProvider({ lang, children }: { lang: string; children: ReactNode }) {
  useEffect(() => {
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* storage blocked */ }
    document.documentElement.lang = lang;
  }, [lang]);
  const { data } = useQuery({
    queryKey: ['translations', lang],
    queryFn: async () => {
      const res = await fetch(`/api/translations/${encodeURIComponent(lang)}`);
      return res.ok ? ((await res.json()) as Dict) : {};
    },
    staleTime: 10 * 60_000,
    enabled: lang !== 'en',
  });
  return <I18nContext.Provider value={{ lang, dict: data ?? {} }}>{children}</I18nContext.Provider>;
}

const fill = (text: string, vars?: Record<string, string | number>) =>
  vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : text;

/** t('app.nav.dashboard', 'Dashboard') or t(msg) — the user's language, else the English text. */
export function useT() {
  const { dict } = useContext(I18nContext);
  return useCallback((keyOrMsg: string | Msg, text?: string, vars?: Record<string, string | number>) => {
    const key = typeof keyOrMsg === 'string' ? keyOrMsg : keyOrMsg.key;
    const fallback = typeof keyOrMsg === 'string' ? (text ?? key) : keyOrMsg.text;
    const translated = dict[key];
    return fill(translated && translated !== key ? translated : fallback, typeof keyOrMsg === 'string' ? vars : (text as unknown as Record<string, string | number>));
  }, [dict]);
}

export const useLanguage = () => useContext(I18nContext).lang;
