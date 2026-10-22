import { createTheme, MantineColorsTuple } from '@mantine/core';

// Brand blue, and a navy "dark" palette so dark mode reads as deep navy rather than grey.
const brand: MantineColorsTuple = [
  '#e7f1ff', '#cfe0ff', '#9ebfff', '#699bfd', '#3e7cfb', '#2468fb', '#145efc', '#004ee1', '#0045ca', '#003bb3',
];
const navy: MantineColorsTuple = [
  '#c9d4e5', '#a6b5cc', '#7d8fad', '#56698a', '#2f4366', '#1f3354', '#162847', '#10203b', '#0b1830', '#071226',
];

/** Ten shades of a hex colour (index 6 = the colour itself), for a Mantine palette. */
export function shadesOf(hex: string): MantineColorsTuple {
  const n = parseInt(hex.replace('#', '').padEnd(6, '0').slice(0, 6), 16);
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const mix = (to: number, t: number) => '#' + rgb.map((c) => Math.round(c + (to - c) * t).toString(16).padStart(2, '0')).join('');
  return [mix(255, 0.9), mix(255, 0.78), mix(255, 0.6), mix(255, 0.42), mix(255, 0.26), mix(255, 0.12), mix(0, 0),
          mix(0, 0.12), mix(0, 0.24), mix(0, 0.36)] as unknown as MantineColorsTuple;
}

const isHex = (v: string | null | undefined): v is string => !!v && /^#[0-9a-f]{6}$/i.test(v);

/** The app theme, with the user group's primary and secondary colours when set. */
export function buildTheme(primary?: string | null, secondary?: string | null) {
  return createTheme({
    ...base,
    colors: { ...base.colors, brand: isHex(primary) ? shadesOf(primary) : brand,
              accent: isHex(secondary) ? shadesOf(secondary) : shadesOf('#f59e0b') },
    ...(isHex(primary) ? { primaryShade: { light: 6, dark: 5 } as const } : {}),
  });
}

const base = createTheme({
  primaryColor: 'brand',
  colors: { brand, dark: navy },
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  headings: { fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', fontWeight: '650' },
  defaultRadius: 'md',
  cursorType: 'pointer',
  components: {
    Card: { defaultProps: { withBorder: true, radius: 'lg', padding: 'lg' } },
    Paper: { defaultProps: { radius: 'lg' } },
    Button: { defaultProps: { radius: 'md' } },
  },
});

export const theme = buildTheme();

// Semantic colours (status/alerts) — always paired with a text label in the UI.
export const STATUS = {
  active: '#22c55e',
  idle: '#f59e0b',
  offline: '#94a3b8',
  danger: '#ef4444',
  warn: '#f97316',
};
