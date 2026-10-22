import { useEffect, useRef, useState } from 'react';
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ActionIcon, AppShell, Avatar, Badge, Burger, Group, Indicator, Menu, NavLink, Stack, Text, Title, Tooltip,
  useMantineColorScheme, useComputedColorScheme,
} from '@mantine/core';
import { useDisclosure, useLocalStorage } from '@mantine/hooks';
import {
  IconAdjustmentsHorizontal, IconBell, IconChartBar, IconExternalLink, IconUserCircle, IconInbox, IconLayoutDashboard, IconLogout,
  IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand, IconMapRoute, IconMoon, IconSearch, IconSun,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useQueryClient } from '@tanstack/react-query';
import { useCan, useGroupTheme, usePlatformName, useUnreadCount } from '../api/hooks';
import { clearSession, getSession } from '../auth/session';
import { GlobalSearch } from '../components/GlobalSearch';
import { msg, useT } from '../i18n';
import classes from './AppLayout.module.css';

dayjs.extend(utc);

// `any`: the role needs at least one of these permissions to see the section.
export const NAV = [
  { to: '/dashboard', label: msg('app.nav.dashboard', 'Dashboard'), icon: IconLayoutDashboard, any: ['map.view'] },
  { to: '/workspace', label: msg('app.nav.workspace', 'Workspace'), icon: IconMapRoute, any: ['map.view', 'history.view', 'places.view'] },
  { to: '/configuration', label: msg('app.nav.configuration', 'Configuration'), icon: IconAdjustmentsHorizontal, any: ['admin'] },
  { to: '/reports', label: msg('app.nav.reports', 'Reports'), icon: IconChartBar, any: ['reports.view'] },
  { to: '/inbox', label: msg('app.nav.inbox', 'Inbox'), icon: IconInbox, any: ['inbox.view'] },
];

function Clock({ compact }: { compact?: boolean }) {
  const t = useT();
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
          <Text size="10px" c="dimmed" tt="uppercase">{t('app.clock.local', 'Local')}</Text>
        </div>
        <div>
          <Text className={classes.clockBig} c="dimmed">{now.utc().format('HH:mm')}</Text>
          <Text size="10px" c="dimmed">{t('app.clock.utc', 'UTC')}</Text>
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
  const platformName = usePlatformName();
  const can = useCan();
  const nav = NAV.filter((n) => n.any.length === 0 || n.any.some(can));
  const { data: unread } = useUnreadCount();
  const { data: groupTheme } = useGroupTheme();
  const queryClient = useQueryClient();
  const logo = (scheme === 'dark' && groupTheme?.logo_dark_data) || groupTheme?.logo_data;
  const navigate = useNavigate();
  const location = useLocation();
  const { user, group } = getSession();
  const t = useT();
  const navItem = NAV.find((n) => location.pathname.startsWith(n.to));
  const title = navItem ? t(navItem.label) : location.pathname.startsWith('/account') ? t('app.account.title', 'My account') : '';
  const initials = `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || (user?.email?.[0] ?? '?').toUpperCase();

  useEffect(() => { close(); }, [location.pathname, close]);
  useEffect(() => {
    document.title = `${title ? `${title} · ` : ''}${platformName}`;
  }, [platformName, title]);

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
            <Tooltip label={collapsed ? t('app.nav.expand_menu', 'Expand menu') : t('app.nav.collapse_menu', 'Collapse menu')}>
              <ActionIcon variant="subtle" color="gray" size="lg" visibleFrom="sm" onClick={() => setCollapsed(!collapsedPref)}
                          aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}>
                {collapsed ? <IconLayoutSidebarLeftExpand size={20} /> : <IconLayoutSidebarLeftCollapse size={20} />}
              </ActionIcon>
            </Tooltip>
            <Title order={4} fw={650}>{title}</Title>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {nav.some((n) => n.to === '/inbox') && (
              <Tooltip label={unread ? t('app.nav.unread_notifications', '{count} unread notifications', { count: unread }) : t('app.nav.no_unread', 'No unread notifications')}>
                <Indicator label={unread && unread > 99 ? '99+' : unread} size={18} color="red" offset={4} disabled={!unread}>
                  <ActionIcon variant="default" size="lg" aria-label="Notifications"
                              onClick={() => navigate('/inbox?status=unread')}>
                    <IconBell size={18} />
                  </ActionIcon>
                </Indicator>
              </Tooltip>
            )}
            {!groupTheme?.theme_settings?.lock_scheme && <Tooltip label={scheme === 'dark' ? t('app.nav.light_mode', 'Light mode') : t('app.nav.dark_mode', 'Dark mode')}>
              <ActionIcon variant="default" size="lg" aria-label="Toggle colour scheme"
                          onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
                {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
            </Tooltip>}
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
                <Menu.Item leftSection={<IconUserCircle size={16} />} onClick={() => navigate('/account')}>{t('app.account.title', 'My account')}</Menu.Item>
                <Menu.Item leftSection={<IconExternalLink size={16} />} component="a" href="/customer/classic/">
                  {t('app.nav.classic_dashboard', 'Classic dashboard')}
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={logout}>{t('app.nav.sign_out', 'Sign out')}</Menu.Item>
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
              ? <Text className={classes.brandName} fz={20}>{platformName[0]}</Text>
              : <Stack gap={2} align="center">
                  <Text className={classes.brandName}>{platformName}</Text>
                  <Text size="xs" c="dimmed">{group?.name}</Text>
                </Stack>}
        </div>
        <div className={classes.search}>
          {collapsed
            ? <Tooltip label={`${t('app.common.search', 'Search')} (⌘K)`} position="right"><ActionIcon variant="subtle" color="gray" size="xl" onClick={openSearch} aria-label="Search" style={{ color: 'var(--vt-menu-fg)' }}>
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
                label={collapsed ? null : t(n.label)}
                aria-label={t(n.label)}
                leftSection={<span className={classes.navIcon}><n.icon size={22} stroke={1.6} />{collapsed && !!unread && n.to === '/inbox' ? <span className={classes.dotBadge} /> : null}</span>}
                rightSection={collapsed ? null : badge}
                active={location.pathname.startsWith(n.to)}
                className={classes.navItem}
              />
            );
            return collapsed ? <Tooltip key={n.to} label={t(n.label)} position="right">{link}</Tooltip> : link;
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
