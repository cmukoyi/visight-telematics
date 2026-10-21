import { createTheme, MantineColorsTuple } from '@mantine/core';

// Brand blue, and a navy "dark" palette so dark mode reads as deep navy rather than grey.
const brand: MantineColorsTuple = [
  '#e7f1ff', '#cfe0ff', '#9ebfff', '#699bfd', '#3e7cfb', '#2468fb', '#145efc', '#004ee1', '#0045ca', '#003bb3',
];
const navy: MantineColorsTuple = [
  '#c9d4e5', '#a6b5cc', '#7d8fad', '#56698a', '#2f4366', '#1f3354', '#162847', '#10203b', '#0b1830', '#071226',
];

export const theme = createTheme({
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

// Semantic colours (status/alerts) — always paired with a text label in the UI.
export const STATUS = {
  active: '#22c55e',
  idle: '#f59e0b',
  offline: '#94a3b8',
  danger: '#ef4444',
  warn: '#f97316',
};
