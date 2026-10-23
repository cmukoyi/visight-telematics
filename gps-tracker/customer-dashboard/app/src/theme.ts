import { createTheme, CSSVariablesResolver, MantineColorsTuple } from '@mantine/core';
import type { ThemeSettings } from './api/types';

// Brand blue, and a navy "dark" palette so dark mode reads as deep navy rather than grey.
const brand: MantineColorsTuple = [
  '#e7f1ff', '#cfe0ff', '#9ebfff', '#699bfd', '#3e7cfb', '#2468fb', '#145efc', '#004ee1', '#0045ca', '#003bb3',
];
const navy: MantineColorsTuple = [
  '#d3dceb', '#b0bfd6', '#899dbc', '#62789c', '#3f5880', '#2d4a72', '#1d3f66', '#113356', '#0d2b4a', '#09223d',
];
export const DEFAULT_MENU = '#113356';
// Night: text greys, then graphite steps (4 borders, 5 hover/selected, 6 inputs) on a warm near-black canvas (7 = page)
const night: MantineColorsTuple = [
  '#cccccc', '#b4b4b4', '#888888', '#555555', '#404347', '#4c4f55', '#34363a', '#080607', '#050404', '#020202',
];

const rgbOf = (hex: string) => {
  const n = parseInt(hex.replace('#', '').padEnd(6, '0').slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
/** hex mixed towards white (to = 255) or black (to = 0) by t (0–1). */
function mix(hex: string, to: number, t: number) {
  return '#' + rgbOf(hex).map((c) => Math.round(c + (to - c) * t).toString(16).padStart(2, '0')).join('');
}

/** Ten shades of a hex colour (index 6 = the colour itself), for a Mantine palette. */
export function shadesOf(hex: string): MantineColorsTuple {
  return [mix(hex, 255, 0.9), mix(hex, 255, 0.78), mix(hex, 255, 0.6), mix(hex, 255, 0.42), mix(hex, 255, 0.26),
          mix(hex, 255, 0.12), hex, mix(hex, 0, 0.12), mix(hex, 0, 0.24), mix(hex, 0, 0.36)] as unknown as MantineColorsTuple;
}

/** A Mantine "dark" palette around a background colour (index 7 = the page background in dark mode). */
export function darkShadesOf(hex: string): MantineColorsTuple {
  return [mix(hex, 255, 0.8), mix(hex, 255, 0.66), mix(hex, 255, 0.5), mix(hex, 255, 0.34), mix(hex, 255, 0.2),
          mix(hex, 255, 0.12), mix(hex, 255, 0.06), hex, mix(hex, 0, 0.14), mix(hex, 0, 0.28)] as unknown as MantineColorsTuple;
}

/** True when dark text reads better than white on this colour (WCAG relative luminance). */
export function isLight(hex: string) {
  const [r, g, b] = rgbOf(hex).map((c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4;
}

export const isHex = (v: string | null | undefined): v is string => !!v && /^#[0-9a-f]{6}$/i.test(v);

const SYSTEM_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
export const FONTS = ['Inter', 'System', 'Roboto', 'Open Sans', 'Lato', 'Montserrat', 'Poppins', 'Nunito', 'Source Sans 3'];
export const fontStack = (font?: string) => (!font || font === 'System' ? SYSTEM_FONT : `"${font}", ${SYSTEM_FONT}`);

/** Load a Google font once (fonts.googleapis.com is allowed by the CSP). */
export function loadFont(font?: string) {
  if (!font || font === 'System' || typeof document === 'undefined') return;
  const id = `vt-font-${font.replace(/\s+/g, '-')}`;
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(font).replace(/%20/g, '+')}:wght@300;400;500;600;700&display=swap`;
  document.head.appendChild(link);
}

export interface ThemeInput { primary?: string | null; secondary?: string | null; settings?: ThemeSettings | null }

/** The app theme, with the user group's colours, font and corners when set (white label). */
export function buildTheme({ primary, secondary, settings }: ThemeInput = {}) {
  const s = settings ?? {};
  const font = fontStack(s.font ?? 'Inter');
  return createTheme({
    ...base,
    colors: { ...base.colors, brand: isHex(primary) ? shadesOf(primary) : brand,
              accent: isHex(secondary) ? shadesOf(secondary) : shadesOf('#f59e0b'),
              dark: s.style === 'night' ? night : isHex(s.surface) ? darkShadesOf(s.surface) : navy },
    ...(isHex(primary) ? { primaryShade: { light: 6, dark: s.style === 'night' ? 6 : 5 } as const } : {}),
    // Night: a light accent gets dark text on filled buttons and badges
    ...(s.style === 'night' ? { autoContrast: true, luminanceThreshold: 0.45 } : {}),
    fontFamily: font,
    headings: { ...base.headings, fontFamily: font },
    defaultRadius: s.radius ?? 'md',
    other: { settings: s },
  });
}

const base = createTheme({
  primaryColor: 'brand',
  colors: { brand, dark: navy },
  headings: { fontWeight: '650' },
  cursorType: 'pointer',
  components: {
    Card: { defaultProps: { withBorder: true, radius: 'lg', padding: 'lg' } },
    Paper: { defaultProps: { radius: 'lg' } },
    Button: { defaultProps: { radius: 'md' } },
    // Dialogs (confirmations, temporary passwords) open in the middle of the screen, like the editors
    Modal: { defaultProps: { centered: true } },
  },
});

/** Menu colours (with readable text on any background) and the light-mode page background. */
export const cssVariables: CSSVariablesResolver = (theme) => {
  const s = (theme.other.settings ?? {}) as ThemeSettings;
  const menu = isHex(s.menu_bg) ? s.menu_bg : null;
  const ink = (hex: string) => (isLight(hex)
    ? { '--vt-menu-fg': '#1f2937', '--vt-menu-muted': '#4b5563', '--vt-menu-ink': '0, 0, 0' }
    : { '--vt-menu-fg': '#ffffff', '--vt-menu-muted': mix(hex, 255, 0.72), '--vt-menu-ink': '255, 255, 255' });
  const menuVars = (hex: string, gradient: string) => ({ '--vt-menu-bg': gradient, ...ink(hex) });
  // A gentle top-to-bottom shade (barely any on light menus, so white stays white)
  const shaded = (hex: string) => `linear-gradient(180deg, ${hex} 0%, ${mix(hex, 0, isLight(hex) ? 0.03 : 0.18)} 100%)`;
  return {
    variables: {},
    light: {
      ...menuVars(menu ?? DEFAULT_MENU, shaded(menu ?? DEFAULT_MENU)),
      ...(isHex(s.light_bg) ? { '--mantine-color-body': s.light_bg } : {}),
    },
    dark: menu
      ? menuVars(menu, shaded(menu))
      : menuVars(theme.colors.dark[8], `linear-gradient(180deg, ${theme.colors.dark[8]} 0%, ${theme.colors.dark[9]} 100%)`),
  };
};

export const theme = buildTheme();

/** Ready-made looks for Custom Themes (each can be adjusted after picking it). */
export const PRESETS: { name: string; primary: string; secondary: string; settings: ThemeSettings }[] = [
  { name: 'ViSight navy', primary: '#2468fb', secondary: '#f59e0b', settings: {} },
  { name: 'Corporate light', primary: '#2563eb', secondary: '#0ea5e9',
    settings: { menu_bg: '#ffffff', light_bg: '#f5f7fb', color_scheme: 'light', surface: '#1e293b' } },
  { name: 'Graphite', primary: '#0ea5e9', secondary: '#facc15', settings: { menu_bg: '#18181b', surface: '#27272a' } },
  { name: 'Forest', primary: '#16a34a', secondary: '#facc15', settings: { menu_bg: '#14532d', surface: '#1a2e22' } },
  { name: 'Burgundy', primary: '#be123c', secondary: '#f59e0b', settings: { menu_bg: '#4c0519', surface: '#2a1419', color_scheme: 'light' } },
  { name: 'Ocean', primary: '#0891b2', secondary: '#22d3ee', settings: { menu_bg: '#083344', surface: '#0c2a33' } },
  { name: 'Night lime', primary: '#8cc63f', secondary: '#d9822b',
    settings: { style: 'night', color_scheme: 'dark', lock_scheme: true, menu_bg: '#1c1d1f', surface: '#080607', font: 'Roboto', radius: 'xs' } },
];

// Semantic colours (status/alerts) — always paired with a text label in the UI.
export const STATUS = {
  active: '#22c55e',
  idle: '#f59e0b',
  offline: '#94a3b8',
  danger: '#ef4444',
  warn: '#f97316',
};
