import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PanelLeftClose, PanelLeft } from 'lucide-react';

import { PRIMARY_NAV, SECONDARY_NAV } from '@/app/nav';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useMe } from '@/session/useMe';

export interface SideNavProps {
  companyName?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

/**
 * Боковая навигация десктопа (от `md`): компания и право действовать из `GET /me`, разделы кабинета.
 * Только данные контракта: ни переключателя ролей (поставщиков в кабинете нет — CONVENTIONS §2 п. 3), ни статуса
 * менеджера, ни своих запросов к спискам на каждой странице (CAB-FIX-1).
 */
export function SideNav({ companyName, collapsed = false, onToggleCollapse }: SideNavProps) {
  const { t } = useTranslation();
  const me = useMe().data;

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col overflow-x-hidden border-r border-hairline bg-alabaster transition-all duration-200 md:flex',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      {/* Компания и право действовать */}
      <div className="border-b border-hairline p-3">
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <div
              className="flex size-9 items-center justify-center rounded-xl bg-navy font-bold text-primary-foreground shadow-xs"
              title={companyName || t('app.name')}
            >
              {(companyName || 'R')[0].toUpperCase()}
            </div>
            {onToggleCollapse && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-lg text-muted-foreground hover:bg-ice-navy hover:text-navy"
                onClick={onToggleCollapse}
                aria-label={t('nav.expandSidebar', { defaultValue: 'Развернуть меню' })}
              >
                <PanelLeft className="size-4" />
              </Button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="flex min-w-0 flex-1 items-center gap-2.5 p-1.5">
                <div
                  className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-navy font-bold text-primary-foreground shadow-xs"
                  aria-hidden="true"
                >
                  {(companyName || 'R')[0].toUpperCase()}
                </div>
                <p className="min-w-0 flex-1 truncate text-xs font-semibold text-charcoal">{companyName || t('app.name')}</p>
              </div>

              {onToggleCollapse && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0 rounded-lg text-muted-foreground hover:bg-ice-navy hover:text-navy"
                  onClick={onToggleCollapse}
                  aria-label={t('nav.collapseSidebar', { defaultValue: 'Свернуть меню' })}
                >
                  <PanelLeftClose className="size-4" />
                </Button>
              )}
            </div>

            {/* Статус доступа */}
            <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                {me?.can_act ? (
                  <span className="inline-block size-1.5 rounded-full bg-sage" />
                ) : (
                  <span className="inline-block size-1.5 rounded-full bg-sand" />
                )}
                {me?.can_act
                  ? t('roles.canActBadge', { defaultValue: 'Полномочия подтверждены' })
                  : t('roles.observerBadge', { defaultValue: 'Только чтение' })}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Блок 2: Навигация (содержит ровно NAV_ITEMS для соответствия контракту тестов) */}
      <nav aria-label={t('app.sideNav')} className="flex-1 overflow-y-auto px-2 py-3">
        {!collapsed && (
          <p className="px-2 pb-1.5 text-xs font-medium tracking-wider text-muted-foreground/80 uppercase">
            {t('nav.sectionMain', { defaultValue: 'Основное' })}
          </p>
        )}
        <ul className="flex flex-col gap-1">
          {PRIMARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                title={collapsed ? t(item.labelKey) : undefined}
                className={({ isActive }) =>
                  cn(
                    'group relative flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-charcoal outline-none transition-colors hover:bg-ice-navy/60 hover:text-navy focus-visible:ring-2 focus-visible:ring-ring',
                    isActive && 'bg-ice-navy font-semibold text-navy',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                <item.icon className="size-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
              </NavLink>
            </li>
          ))}
        </ul>

        {!collapsed && (
          <p className="mt-4 px-2 pb-1.5 text-xs font-medium tracking-wider text-muted-foreground/80 uppercase">
            {t('nav.sectionDocumentsAndTeam', { defaultValue: 'Документы и компания' })}
          </p>
        )}
        <ul className={cn('flex flex-col gap-1', collapsed && 'mt-2 border-t border-hairline pt-2')}>
          {SECONDARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                title={collapsed ? t(item.labelKey) : undefined}
                className={({ isActive }) =>
                  cn(
                    'group relative flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-charcoal outline-none transition-colors hover:bg-ice-navy/60 hover:text-navy focus-visible:ring-2 focus-visible:ring-ring',
                    isActive && 'bg-ice-navy font-semibold text-navy',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                <item.icon className="size-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
