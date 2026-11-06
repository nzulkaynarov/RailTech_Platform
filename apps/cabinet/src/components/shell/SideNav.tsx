import { useId } from 'react';
import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PanelLeftClose, PanelLeft } from 'lucide-react';

import { type NavItem } from '@/app/nav';
import { Button } from '@/components/ui/button';
import { useNavBadges } from '@/hooks/useActionRequired';
import { useUnreadText } from '@/hooks/useUnread';
import { cn } from '@/lib/utils';
import { useCanAct, useMe } from '@/session/useMe';
import { useNav } from '@/session/useNav';
import { BrandMark } from './BrandMark';
import { UnreadBadge, UnreadNote } from './MessagesLink';

export interface SideNavProps {
  companyName?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

/**
 * Боковая навигация десктопа (от `md`): марка RailTech Cabinet, компания и право действовать из `GET /me`, разделы.
 * Только данные контракта: ни переключателя ролей (поставщиков в кабинете нет — CONVENTIONS §2 п. 3), ни статуса
 * менеджера, ни своих запросов к спискам на каждой странице (CAB-FIX-1). Свёрнутый — только иконки, имя пункта —
 * в `aria-label` (CAB-FIX-2). Ширина меняется одним шагом, без анимации: анимация ширины пересчитывала холст на каждом
 * кадре (K12).
 */
export function SideNav({ companyName, collapsed = false, onToggleCollapse }: SideNavProps) {
  const { t } = useTranslation();
  const me = useMe().data;
  const canAct = useCanAct();
  const { primary, secondary, groups } = useNav();

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col overflow-x-hidden border-r border-border/60 bg-muted md:flex',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      {/* Марка, компания и право действовать */}
      <div className="border-b border-border/60 p-3">
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <BrandMark label={companyName ? `${t('app.name')} · ${companyName}` : t('app.name')} />
            {onToggleCollapse && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-lg text-muted-foreground hover:bg-accent hover:text-primary"
                onClick={onToggleCollapse}
                aria-label={t('nav.expandSidebar')}
              >
                <PanelLeft className="size-4" aria-hidden="true" />
              </Button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="flex min-w-0 flex-1 items-center gap-2.5 p-1.5">
                <BrandMark />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-primary">{t('app.name')}</p>
                  {companyName ? <p className="truncate text-xs text-muted-foreground">{companyName}</p> : null}
                </div>
              </div>

              {onToggleCollapse && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0 rounded-lg text-muted-foreground hover:bg-accent hover:text-primary"
                  onClick={onToggleCollapse}
                  aria-label={t('nav.collapseSidebar')}
                >
                  <PanelLeftClose className="size-4" aria-hidden="true" />
                </Button>
              )}
            </div>

            {/* Право действовать: подпись текстом, точка — только украшение */}
            {me ? (
              <p className="flex items-center gap-1.5 px-1.5 text-xs text-muted-foreground">
                <span
                  className={cn('inline-block size-1.5 shrink-0 rounded-full', canAct ? 'bg-success' : 'bg-warning')}
                  aria-hidden="true"
                />
                {canAct ? t('access.canAct') : t('access.viewOnly')}
              </p>
            ) : null}
          </div>
        )}
      </div>

      <nav aria-label={t('app.sideNav')} className="flex-1 overflow-y-auto px-2 py-3">
        {groups ? (
          // Обе роли (клиент и партнёр): «Покупаю» / «Поставляю» / «Компания» — не одним рядом из двенадцати пунктов
          groups.map((group, index) => (
            <section key={group.key} aria-labelledby={`nav-group-${group.key}`} className={cn(index > 0 && (collapsed ? 'mt-2 border-t border-border/60 pt-2' : 'mt-4'))}>
              {!collapsed && (
                <h2
                  id={`nav-group-${group.key}`}
                  className="px-2 pb-1.5 text-xs font-medium tracking-wider text-muted-foreground uppercase"
                >
                  {t(group.labelKey)}
                </h2>
              )}
              <NavList items={group.items} collapsed={collapsed} />
            </section>
          ))
        ) : (
          <>
            {primary.length > 0 && (
              <>
                {!collapsed && (
                  <p className="px-2 pb-1.5 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                    {t('nav.sectionMain')}
                  </p>
                )}
                <NavList items={primary} collapsed={collapsed} />
              </>
            )}

            {secondary.length > 0 && (
              <>
                {!collapsed && (
                  <p className="mt-4 px-2 pb-1.5 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                    {t('nav.sectionDocumentsAndTeam')}
                  </p>
                )}
                <NavList
                  items={secondary}
                  collapsed={collapsed}
                  className={cn(collapsed && 'mt-2 border-t border-border/60 pt-2')}
                />
              </>
            )}
          </>
        )}
      </nav>
    </aside>
  );
}

function NavList({ items, collapsed, className }: { items: NavItem[]; collapsed: boolean; className?: string }) {
  const { t } = useTranslation();
  const badges = useNavBadges();
  const unread = badges['/messages'] ?? 0;
  const unreadText = useUnreadText(unread);
  const noteId = useId();
  return (
    <ul className={cn('flex flex-col gap-1', className)}>
      {items.map((item) => {
        const label = t(item.labelKey);
        // Счётчики действий (волна J1): КП, договоры, счета, акты, поставки, товары, заявки, чат
        const badge = badges[item.to] ?? 0;
        const isMessages = item.to === '/messages';
        return (
          <li key={item.to}>
            <NavLink
              to={item.to}
              // свёрнутый с бейджем: имя — скрытым текстом, а не aria-label (видимое «2» не входит в aria-label, axe)
              aria-label={collapsed && badge === 0 ? label : undefined}
              aria-describedby={isMessages && badge > 0 && unreadText ? noteId : undefined}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-foreground outline-none transition-colors hover:bg-accent/60 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring',
                  isActive && 'bg-accent font-semibold text-primary',
                  collapsed && 'justify-center px-0',
                )
              }
            >
              <item.icon className="size-4 shrink-0" aria-hidden="true" />
              {!collapsed ? <span className="truncate">{label}</span> : null}
              {collapsed && badge > 0 ? <span className="sr-only">{label}</span> : null}
              <UnreadBadge count={badge} className={collapsed ? 'absolute top-0.5 right-0.5' : 'ml-auto'} />
            </NavLink>
            {isMessages && badge > 0 ? <UnreadNote id={noteId} text={unreadText} /> : null}
          </li>
        );
      })}
    </ul>
  );
}
