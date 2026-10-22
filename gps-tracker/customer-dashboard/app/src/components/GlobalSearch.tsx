import { forwardRef, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Combobox, Group, Kbd, Text, TextInput, useCombobox } from '@mantine/core';
import { useHotkeys } from '@mantine/hooks';
import {
  IconBell, IconCar, IconCategory, IconChartBar, IconFileText, IconMapPin, IconSearch, IconUser,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCan, useCategories, usePlaces, usePortalUsers, useReports, useRules, useVehicles } from '../api/hooks';
import { detail, type Alert } from '../api/types';
import { vehicleName } from '../utils/format';
import classes from './GlobalSearch.module.css';

interface Hit { id: string; group: string; label: string; sub?: string; to: string; icon: typeof IconCar }

// Pages and settings, with the permissions that unlock them (empty = everyone)
const PAGES: { label: string; sub: string; to: string; any: string[]; words?: string }[] = [
  { label: 'Dashboard', sub: 'Where is my fleet', to: '/dashboard', any: ['map.view'], words: 'live map kpi' },
  { label: 'Workspace', sub: 'Trips, events and places on the map', to: '/workspace', any: ['map.view', 'history.view'], words: 'trips events history routes' },
  { label: 'Reports', sub: 'Run and download reports', to: '/reports', any: ['reports.view'] },
  { label: 'Inbox', sub: 'Alerts', to: '/inbox', any: ['inbox.view'], words: 'alerts notifications' },
  { label: 'Vehicles', sub: 'Configuration · Vehicles', to: '/configuration/devices', any: ['admin'], words: 'registration driver make model imei delete' },
  { label: 'Vehicle groups', sub: 'Configuration · Vehicles', to: '/configuration/groups', any: ['admin'] },
  { label: 'Data Exchange', sub: 'Configuration · Vehicles', to: '/configuration/exchange', any: ['admin'] },
  { label: 'Users', sub: 'Configuration · Users', to: '/configuration/users', any: ['admin'], words: 'login activity roles' },
  { label: 'User Groups', sub: 'Configuration · Users · preferences', to: '/configuration/user-groups', any: ['admin'], words: 'timezone retention notification preferences' },
  { label: 'Custom Themes', sub: 'Configuration · Users · colours and logos', to: '/configuration/custom-themes', any: ['admin'], words: 'theme logo colour white label' },
  { label: 'Places', sub: 'Configuration · Places', to: '/configuration/places', any: ['admin'], words: 'geofence poi' },
  { label: 'Place Groups', sub: 'Configuration · Places', to: '/configuration/place-groups', any: ['admin'] },
  { label: 'Geofences', sub: 'Configuration · Places · armed vehicles', to: '/configuration/geofences', any: ['admin'], words: 'armed inside outside' },
  { label: 'Event Types', sub: 'Configuration · Events', to: '/configuration/event-types', any: ['admin'], words: 'dictionary marker' },
  { label: 'Event Type Groups', sub: 'Configuration · Events', to: '/configuration/event-type-groups', any: ['admin'] },
  { label: 'Security Groups', sub: 'Configuration · Security', to: '/configuration/security?tab=groups', any: ['admin'] },
  { label: 'Roles', sub: 'Configuration · Security', to: '/configuration/security?tab=roles', any: ['admin'], words: 'permissions features' },
  { label: 'Audit Trail', sub: 'Configuration · Security', to: '/configuration/security?tab=audit', any: ['admin'], words: 'history log who changed' },
  { label: 'Notification Rules', sub: 'Configuration · Misc', to: '/configuration/misc/notification-rules', any: ['admin'], words: 'alerts email geofence event' },
  { label: 'My account', sub: 'Change password', to: '/account', any: [], words: 'password' },
];

const GROUP_ORDER = ['Vehicles', 'Places', 'Vehicle groups', 'Pages', 'Reports', 'Users', 'Notification rules', 'Alerts'];
const PER_GROUP = 5;
const norm = (s: string) => s.toLowerCase();

/**
 * Search everything as you type: vehicles (name, IMEI, registration, driver, make/model), places, vehicle groups,
 * pages and settings, reports, users, notification rules and recent alerts. Ctrl/⌘ + K focuses it.
 */
export const GlobalSearch = forwardRef<HTMLInputElement, { onNavigate?: () => void }>(function GlobalSearch({ onNavigate }, ref) {
  const navigate = useNavigate();
  const can = useCan();
  const combobox = useCombobox({ onDropdownClose: () => combobox.resetSelectedOption() });
  const [q, setQ] = useState('');
  const active = q.trim().length >= 2;

  const { data: vehicles = [] } = useVehicles();
  const { data: places = [] } = usePlaces();
  const { data: categories = [] } = useCategories();
  const { data: reports = [] } = useReports();
  const users = usePortalUsers(active && (can('users.view') || can('users.manage')));
  const rules = useRules(active && (can('inbox.view') || can('rules.manage')));
  const { data: alerts = [] } = useQuery({
    queryKey: ['search-alerts'], queryFn: () => api<Alert[]>('/api/portal/alerts?days=7'),
    enabled: active && can('inbox.view'), staleTime: 60_000,
  });

  const hits = useMemo<Hit[]>(() => {
    if (!active) return [];
    const words = norm(q.trim()).split(/\s+/);
    const match = (...fields: (string | null | undefined)[]) => {
      const hay = norm(fields.filter(Boolean).join(' '));
      return words.every((w) => hay.includes(w));
    };
    const out: Hit[] = [];
    if (can('map.view') || can('history.view')) {
      for (const v of vehicles) {
        const reg = detail(v, 'registration');
        const driver = detail(v, 'driver');
        if (match(vehicleName(v), v.imei, reg, driver, detail(v, 'make'), detail(v, 'model'), v.category_name)) {
          out.push({ id: `v-${v.id}`, group: 'Vehicles', label: vehicleName(v), icon: IconCar,
                     sub: [reg, driver, v.category_name, v.imei].filter(Boolean).join(' · '),
                     to: can('map.view') ? `/dashboard?vehicle=${encodeURIComponent(v.imei)}` : '/workspace' });
        }
      }
    }
    if (can('places.view')) {
      for (const p of places) if (match(p.name, p.address, p.description)) {
        out.push({ id: `p-${p.id}`, group: 'Places', label: p.name, sub: p.address ?? undefined, icon: IconMapPin,
                   to: `/configuration/places?place=${p.id}` });
      }
    }
    for (const c of categories) if (match(c.name)) {
      out.push({ id: `c-${c.id}`, group: 'Vehicle groups', label: c.name, sub: 'Show on dashboard', icon: IconCategory,
                 to: `/dashboard?group=${encodeURIComponent(c.name)}` });
    }
    for (const p of PAGES) if ((p.any.length === 0 || p.any.some(can)) && match(p.label, p.sub, p.words)) {
      out.push({ id: `pg-${p.to}`, group: 'Pages', label: p.label, sub: p.sub, icon: IconFileText, to: p.to });
    }
    if (can('reports.view')) {
      for (const r of reports) if (match(r.title, r.description, r.category)) {
        out.push({ id: `r-${r.key}`, group: 'Reports', label: r.title, sub: r.description, icon: IconChartBar, to: `/reports?run=${r.key}` });
      }
    }
    if (can('users.view') || can('users.manage')) {
      for (const u of users.data ?? []) if (match(u.email, u.first_name, u.last_name)) {
        out.push({ id: `u-${u.id}`, group: 'Users', label: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email, sub: u.email,
                   icon: IconUser, to: `/configuration/users?q=${encodeURIComponent(u.email)}` });
      }
    }
    for (const r of rules.data ?? []) if (match(r.name, r.category)) {
      out.push({ id: `nr-${r.id}`, group: 'Notification rules', label: r.name, sub: r.category ?? 'All vehicles', icon: IconBell,
                 to: '/configuration/misc/notification-rules' });
    }
    for (const a of alerts) if (match(a.title, a.message, a.tag_label)) {
      out.push({ id: `a-${a.id}`, group: 'Alerts', label: a.title, sub: a.message, icon: IconBell,
                 to: `/inbox?search=${encodeURIComponent(a.title)}` });
    }
    return out;
  }, [active, q, vehicles, places, categories, reports, users.data, rules.data, alerts, can]);

  const grouped = GROUP_ORDER.map((g) => [g, hits.filter((h) => h.group === g)] as const).filter(([, list]) => list.length);
  const byId = useMemo(() => new Map(hits.map((h) => [h.id, h])), [hits]);

  useHotkeys([['mod+K', () => { (ref as React.RefObject<HTMLInputElement>)?.current?.focus(); combobox.openDropdown(); }]]);

  return (
    <Combobox store={combobox} position="bottom-start" width={380} withinPortal
              onOptionSubmit={(id) => {
                const hit = byId.get(id);
                if (!hit) return;
                navigate(hit.to);
                setQ('');
                combobox.closeDropdown();
                onNavigate?.();
              }}>
      <Combobox.Target>
        <TextInput ref={ref} value={q} placeholder="Search" aria-label="Search the platform" className={classes.input}
                   leftSection={<IconSearch size={16} />} rightSection={!q ? <Kbd size="xs" className={classes.kbd}>⌘K</Kbd> : null}
                   rightSectionWidth={44}
                   onChange={(e) => { setQ(e.currentTarget.value); combobox.openDropdown(); combobox.updateSelectedOptionIndex(); }}
                   onFocus={() => active && combobox.openDropdown()} onBlur={() => combobox.closeDropdown()}
                   onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); combobox.closeDropdown(); } }} />
      </Combobox.Target>
      <Combobox.Dropdown hidden={!active}>
        <Combobox.Options mah={460} style={{ overflowY: 'auto' }}>
          {grouped.length === 0 && <Combobox.Empty>Nothing found for “{q.trim()}”</Combobox.Empty>}
          {grouped.map(([group, list]) => (
            <Combobox.Group key={group} label={`${group}${list.length > PER_GROUP ? ` (${list.length})` : ''}`}>
              {list.slice(0, PER_GROUP).map((h) => (
                <Combobox.Option key={h.id} value={h.id}>
                  <Group gap="sm" wrap="nowrap">
                    <h.icon size={16} stroke={1.6} className={classes.icon} />
                    <div style={{ minWidth: 0 }}>
                      <Text size="sm" fw={500} truncate>{h.label}</Text>
                      {h.sub && <Text size="xs" c="dimmed" truncate>{h.sub}</Text>}
                    </div>
                  </Group>
                </Combobox.Option>
              ))}
            </Combobox.Group>
          ))}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
});
