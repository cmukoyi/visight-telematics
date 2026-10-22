import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button, CloseButton, Group, Modal, ScrollArea, Text, TextInput, UnstyledButton } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconSearch } from '@tabler/icons-react';
import classes from './EditorShell.module.css';

export interface EditorSection {
  id: string;
  label: string;
  content: ReactNode;
  /** Field labels in the section, for "Search label…". */
  keywords?: string;
  danger?: boolean;
}

interface Props {
  opened: boolean;
  onClose: () => void;
  title: ReactNode;
  sections: EditorSection[];
  onSave?: () => void;
  onSaveAndNew?: () => void;
  saving?: boolean;
  saveDisabled?: boolean;
}

/**
 * A large centred editor (Edit user, New role): sections listed on the left,
 * all sections stacked on the right (the list follows the scroll), and
 * Save and new / Save / Cancel at the bottom.
 */
export function EditorShell({ opened, onClose, title, sections, onSave, onSaveAndNew, saving, saveDisabled }: Props) {
  const mobile = useMediaQuery('(max-width: 48em)');
  const viewport = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<string | undefined>(sections[0]?.id);
  const [search, setSearch] = useState('');
  useEffect(() => { if (opened) { setActive(sections[0]?.id); setSearch(''); viewport.current?.scrollTo({ top: 0 }); } }, [opened]); // eslint-disable-line react-hooks/exhaustive-deps

  // A section's distance from the top of the scrolled content
  const topOf = (vp: HTMLElement, el: HTMLElement) => el.getBoundingClientRect().top - vp.getBoundingClientRect().top + vp.scrollTop;
  const jumping = useRef(false);
  const jump = (id: string) => {
    const vp = viewport.current;
    const el = vp?.querySelector<HTMLElement>(`[data-section="${id}"]`);
    if (vp && el) {
      jumping.current = true;
      vp.scrollTo({ top: topOf(vp, el) });
      setTimeout(() => { jumping.current = false; }, 600);
    }
    setActive(id);
  };
  const onScroll = () => {
    const vp = viewport.current;
    if (!vp || jumping.current) return;
    const els = [...vp.querySelectorAll<HTMLElement>('[data-section]')];
    const atEnd = vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 4;
    const current = atEnd ? els[els.length - 1] : els.filter((el) => topOf(vp, el) - 80 <= vp.scrollTop).pop() ?? els[0];
    if (current) setActive(current.dataset.section);
  };
  const q = search.trim().toLowerCase();
  const matches = (s: EditorSection) => !q || `${s.label} ${s.keywords ?? ''}`.toLowerCase().includes(q);

  return (
    <Modal opened={opened} onClose={onClose} centered size={1180} padding={0} withCloseButton={false} fullScreen={mobile}
           classNames={{ content: classes.content, body: classes.body }} trapFocus returnFocus>
      <Group justify="space-between" className={classes.head} wrap="nowrap">
        <Text fz={26} fw={500}>{title}</Text>
        <CloseButton size="lg" onClick={onClose} aria-label="Close" />
      </Group>
      <div className={classes.main}>
        <nav className={classes.nav} aria-label="Sections">
          {sections.map((s) => (
            <UnstyledButton key={s.id} className={classes.navItem} onClick={() => jump(s.id)}
                            data-active={active === s.id || undefined} data-danger={s.danger || undefined}
                            data-dim={!matches(s) || undefined}>
              {s.label}
            </UnstyledButton>
          ))}
        </nav>
        <ScrollArea className={classes.scroll} viewportRef={viewport} onScrollPositionChange={onScroll} type="auto">
          {sections.map((s) => (
            <section key={s.id} data-section={s.id} className={classes.section}>
              <div className={classes.sectionTitle}>{s.label}</div>
              {s.content}
            </section>
          ))}
        </ScrollArea>
      </div>
      <div className={classes.foot}>
        <TextInput w={280} radius="xl" placeholder="Search label…" leftSection={<IconSearch size={16} />} value={search}
                   onChange={(e) => setSearch(e.currentTarget.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') { const hit = sections.find(matches); if (hit) jump(hit.id); } }} />
        <Group gap="sm">
          {onSaveAndNew && <Button variant="outline" radius="xl" size="md" onClick={onSaveAndNew} disabled={saveDisabled} loading={saving}>Save and new</Button>}
          {onSave && <Button radius="xl" size="md" onClick={onSave} disabled={saveDisabled} loading={saving}>Save</Button>}
          <Button variant="default" radius="xl" size="md" onClick={onClose}>{onSave ? 'Cancel' : 'Close'}</Button>
        </Group>
      </div>
    </Modal>
  );
}

/** Show the first validation error (it may be in a section that's scrolled out of view). */
export function firstError(errors: Record<string, unknown>) {
  const msg = Object.values(errors).find(Boolean);
  if (msg) notifications.show({ color: 'orange', message: String(msg) });
}
