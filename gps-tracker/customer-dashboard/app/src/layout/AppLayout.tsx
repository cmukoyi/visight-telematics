import { useEffect, useState } from 'react';
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ActionIcon, AppShell, Avatar, Badge, Burger, Group, Menu, NavLink, Stack, Text, Title, Tooltip,
  useMantineColorScheme, useComputedColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconAdjustmentsHorizontal, IconChartBar, IconExternalLink, IconInbox, IconLayoutDashboard, IconLogout,
  IconMapRoute, IconMoon, IconSun,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useBranding, useUnreadCount } from '../api/hooks';
import { clearSession, getSession } from '../auth/session';
import classes from './AppLayout.module.css';

dayjs.extend(utc);

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: IconLayoutDashboard },
  { to: '/workspace', label: 'Workspace', icon: IconMapRoute },
  { to: '/configuration', label: 'Configuration', icon: IconAdjustmentsHorizontal },
  { to: '/reports', label: 'Reports', icon: IconChartBar },
  { to: '/inbox', label: 'Inbox', icon: IconInbox },
];

function Clock() {
  const [now, setNow] = useState(dayjs());
  useEffect(() => {
    const t = setInterval(() => setNow(dayjs()), 15_000);
    return () => clearInterval(t);
  }, []);
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
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('dark');
  const { data: branding } = useBranding();
  const { data: unread } = useUnreadCount();
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
    navigate('/login', { replace: true });
  };

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 248, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding={0}
      classNames={{ navbar: classes.navbar, header: classes.header, main: classes.main }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
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

      <AppShell.Navbar p="md">
        <Stack gap={4} className={classes.brand}>
          <Text className={classes.brandName}>{branding?.name ?? 'ViSight Track'}</Text>
          <Text size="xs" c="dimmed">{group?.name}</Text>
        </Stack>
        <Stack gap={4} mt="lg" style={{ flex: 1 }}>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              component={RouterLink}
              to={n.to}
              label={n.label}
              leftSection={<n.icon size={20} stroke={1.6} />}
              rightSection={n.to === '/inbox' && unread ? <Badge size="sm" color="red" variant="filled">{unread}</Badge> : null}
              active={location.pathname.startsWith(n.to)}
              className={classes.navItem}
            />
          ))}
        </Stack>
        <Clock />
      </AppShell.Navbar>

      <AppShell.Main className={classes.main}>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
