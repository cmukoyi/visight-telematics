import { useEffect, useState } from 'react';
import type { ThemeSettings } from '../api/types';

/** A look being tried in this browser only (Custom Themes → Try on this browser); everyone else keeps the saved theme. */
export interface ThemeTrial { name: string; theme_primary: string | null; theme_accent: string | null; theme_settings: ThemeSettings | null }

const KEY = 'vt-theme-trial';
const EVENT = 'vt-theme-trial';

export function getTrial(): ThemeTrial | null {
  try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; }
}

export function setTrial(trial: ThemeTrial | null) {
  try {
    if (trial) localStorage.setItem(KEY, JSON.stringify(trial));
    else localStorage.removeItem(KEY);
  } catch { /* storage blocked: the trial lasts until the page reloads */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: trial }));
}

export function useThemeTrial(): ThemeTrial | null {
  const [trial, set] = useState<ThemeTrial | null>(getTrial);
  useEffect(() => {
    const on = (e: Event) => set((e as CustomEvent<ThemeTrial | null>).detail ?? null);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return trial;
}
