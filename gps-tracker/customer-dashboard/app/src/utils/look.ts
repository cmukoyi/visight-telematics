import type { GroupTheme } from '../api/types';

/** The last user-group look seen in this browser, so a reload (and the sign-in page) doesn't flash the default theme. */
export type Look = Pick<GroupTheme, 'theme_primary' | 'theme_accent' | 'theme_settings' | 'timezone'>;
const LOOK_KEY = 'vt-group-look';

export function cachedLook(): Look | null {
  try { return JSON.parse(localStorage.getItem(LOOK_KEY) ?? 'null'); } catch { return null; }
}

export function saveLook({ theme_primary, theme_accent, theme_settings, timezone }: GroupTheme) {
  try { localStorage.setItem(LOOK_KEY, JSON.stringify({ theme_primary, theme_accent, theme_settings, timezone })); } catch { /* storage blocked */ }
}
