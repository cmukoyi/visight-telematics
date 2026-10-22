import { useEffect, useRef, useState } from 'react';
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ActionIcon, AppShell, Avatar, Badge, Burger, Group, Menu, NavLink, Stack, Text, Title, Tooltip,
  useMantineColorScheme, useComputedColorScheme,
} from '@mantine/core';
import { useDisclosure, useLocalStorage } from '@mantine/hooks';
import {
  IconAdjustmentsHorizontal, IconChartBar, IconExternalLink, IconInbox, IconLayoutDashboard, IconLogout,
  IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand, IconMapRoute, IconMoon, IconSearch, IconSun,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useQueryClient } from '@tanstack/react-query';
import { useBranding, useCan, useGroupTheme, useUnreadCount } from '../api/hooks';
import { clearSession, getSession } from '../auth/session';
import { GlobalSearch } from '../components/GlobalSearch';
import classes from './AppLayout.module.css';

dayjs.extend(utc);

// `any`: the role needs at least one of these permissions to see the section.
export const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: IconLayoutDashboard, any: ['map.view'] },
  { to: '/workspace', label: 'Workspace', icon: IconMapRoute, any: ['map.view', 'history.view', 'places.view'] },
  { to: '/configuration', label: 'Configuration', icon: IconAdjustmentsHorizontal, any: [] },
  { to: '/reports', label: 'Reports', icon: IconChartBar, any: ['reports.view'] },
  { to: '/inbox', label: 'Inbox', icon: IconInbox, any: ['inbox.view'] },
];

function Clock({ compact }: { compact?: boolean }) {
  const [now, setNow] = useState(dayjs());
  useEffect(() => {
    const t = setInterval(() => setNow(dayjs()), 15_000);
    return () => clearInterval(t);
  }, []);
  if (compact) {
    return (
      <Tooltip label={`${now.format('ddd, DD MMM YYYY HH:mm')} local · ${now.utc().format('HH:mm')} UTC`} position="right">
        <div className={`${classes.clock} ${classes.clockCompact}`}><Text fw={600}>{now.format('HH:mm')}</Text></div>
      </Tooltip>
    );
  }
  return (
    <div className={classes.clock}>
      <Text size="xs" c="dimmed">{now.format('ddd, DD MMM YYYY')}</Text>
      <Group gap="md" align="baseline" wrap="nowrap">
        <div>
          <Text className={classes.clockBig}>{now.format('HH:mm')}</Text>
          <Text size="10px" c="dimmed">LOCAL</Text>
        </div>
        <div>
          <Text className={classes.clockBig} c="dimmed">{now.utc().format('HH:mm')}</Text>
          <Text size="10px" c="dimmed">UTC</Text>
        </div>
      </Group>
    </div>
  );
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  // Collapsed (icons only) on desktop; remembered per browser
  const [collapsedPref, setCollapsed] = useLocalStorage({ key: 'vt-nav-collapsed', defaultValue: false });
  const collapsed = collapsedPref && !opened;
  const searchRef = useRef<HTMLInputElement>(null);
  const openSearch = () => { setCollapsed(false); setTimeout(() => searchRef.current?.focus(), 250); };
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('dark');
  const { data: branding } = useBranding();
  const can = useCan();
  const nav = NAV.filter((n) => n.any.length === 0 || n.any.some(can));
  const { data: unread } = useUnreadCount();
  const { data: groupTheme } = useGroupTheme();
  const queryClient = useQueryClient();
  const logo = (scheme === 'dark' && groupTheme?.logo_dark_data) || groupTheme?.logo_data;
  const navigate = useNavigate();
  const location = useLocation();
  const { user, group } = getSession();
  const title = NAV.find((n) => location.pathname.startsWith(n.to))?.label ?? '';
  const initials = `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || (user?.email?.[0] ?? '?').toUpperCase();

  useEffect(() => { close(); }, [location.pathname, close]);
  useEffect(() => {
    if (branding) document.title = `${title ? `${title} · ` : ''}${branding.name}`;
  }, [branding, title]);

  const logout = () => {
    clearSession();
    queryClient.clear();
    navigate('/login', { replace: true });
  };

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: collapsed ? 84 : 312, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      transitionDuration={200}
      padding={0}
      classNames={{ navbar: classes.navbar, header: classes.header, main: classes.main }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Tooltip label={collapsed ? 'Expand menu' : 'Collapse menu'}>
              <ActionIcon variant="subtle" color="gray" size="lg" visibleFrom="sm" onClick={() => setCollapsed(!collapsedPref)}
                          aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}>
                {collapsed ? <IconLayoutSidebarLeftExpand size={20} /> : <IconLayoutSidebarLeftCollapse size={20} />}
              </ActionIcon>
            </Tooltip>
            <Title order={4} fw={650}>{title}</Title>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label={scheme === 'dark' ? 'Light mode' : 'Dark mode'}>
              <ActionIcon variant="default" size="lg" aria-label="Toggle colour scheme"
                          onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
                {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
            </Tooltip>
            <Menu position="bottom-end" width={240} shadow="md">
              <Menu.Target>
                <Group gap={8} className={classes.userButton} wrap="nowrap">
                  <Avatar color="brand" radius="xl" size={32}>{initials}</Avatar>
                  <div className={classes.userText}>
                    <Text size="sm" fw={600} lh={1.2} truncate>{user?.first_name || user?.email}</Text>
                    <Text size="xs" c="dimmed" lh={1.2} truncate>{group?.name}</Text>
                  </div>
                </Group>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.email}</Menu.Label>
                <Menu.Item leftSection={<IconExternalLink size={16} />} component="a" href="/customer/classic/">
                  Classic dashboard
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={logout}>Sign out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p={collapsed ? 'xs' : 'md'} className={collapsed ? classes.collapsed : undefined}>
        {/* Logo area: 280 × 150 (Configuration → User Group → Platform logo); a small square when collapsed */}
        <div className={collapsed ? classes.logoSmall : classes.logoBox}>
          {logo
            ? <img src={logo} alt={groupTheme?.name ?? group?.name ?? 'Logo'} className={classes.logo} />
            : collapsed
              ? <Text className={classes.brandName} fz={20}>{(branding?.name ?? 'V')[0]}</Text>
              : <Stack gap={2} align="center">
                  <Text className={classes.brandName}>{branding?.name ?? 'ViSight Track'}</Text>
                  <Text size="xs" c="dimmed">{group?.name}</Text>
                </Stack>}
        </div>
        <div className={classes.search}>
          {collapsed
            ? <Tooltip label="Search (⌘K)" position="right"><ActionIcon variant="subtle" color="gray" size="xl" onClick={openSearch} aria-label="Search">
                <IconSearch size={20} /></ActionIcon></Tooltip>
            : <GlobalSearch ref={searchRef} onNavigate={close} />}
        </div>
        <Stack gap={6} mt="md" style={{ flex: 1 }}>
          {nav.map((n) => {
            const badge = n.to === '/inbox' && unread ? <Badge size="sm" color="red" variant="filled">{unread}</Badge> : null;
            const link = (
              <NavLink
                key={n.to}
                component={RouterLink}
                to={n.to}
                label={collapsed ? null : n.label}
                aria-label={n.label}
                leftSection={<span className={classes.navIcon}><n.icon size={22} stroke={1.6} />{collapsed && !!unread && n.to === '/inbox' ? <span className={classes.dotBadge} /> : null}</span>}
                rightSection={collapsed ? null : badge}
                active={location.pathname.startsWith(n.to)}
                className={classes.navItem}
              />
            );
            return collapsed ? <Tooltip key={n.to} label={n.label} position="right">{link}</Tooltip> : link;
          })}
        </Stack>
        <Clock compact={collapsed} />
      </AppShell.Navbar>

      <AppShell.Main className={classes.main}>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
