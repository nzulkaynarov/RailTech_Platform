import { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronsUpDown,
  Plus,
  ShieldCheck,
  Eye,
  PanelLeftClose,
  PanelLeft,
} from 'lucide-react';

import { PRIMARY_NAV, SECONDARY_NAV } from '@/app/nav';
import { useRequests, useQuotes, useContracts, useDeliveries } from '@/api/queries';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useMe } from '@/session/useMe';

export interface SideNavProps {
  companyName?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface DealItem {
  deal?: {
    id: number;
    number: string;
    title?: string | null;
  } | null;
}

const ROLE_STORAGE_KEY = 'rt-cab-role-contour-v1';

export function SideNav({ companyName, collapsed = false, onToggleCollapse }: SideNavProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const me = useMe().data;

  // Ролевой контур
  const [roleContour, setRoleContour] = useState(() => {
    try {
      return localStorage.getItem(ROLE_STORAGE_KEY) || 'buyer';
    } catch {
      return 'buyer';
    }
  });

  const handleSelectRole = (key: string) => {
    setRoleContour(key);
    try {
      localStorage.setItem(ROLE_STORAGE_KEY, key);
    } catch {
      // ignore
    }
  };

  // Агрегируем уникальные активные сделки клиента
  const requests = useRequests();
  const quotes = useQuotes();
  const contracts = useContracts();
  const deliveries = useDeliveries();

  const dealsMap = new Map<number, { id: number; number: string; title?: string | null }>();
  ([requests.data, quotes.data, contracts.data, deliveries.data] as Array<DealItem[] | undefined>).forEach((list) => {
    if (Array.isArray(list)) {
      list.forEach((item) => {
        if (item?.deal?.id) {
          dealsMap.set(item.deal.id, {
            id: item.deal.id,
            number: item.deal.number,
            title: item.deal.title,
          });
        }
      });
    }
  });
  const deals = Array.from(dealsMap.values()).slice(0, 5);

  const roleTitles: Record<string, string> = {
    buyer: t('roles.buyer', { defaultValue: 'Покупатель товаров и сервиса' }),
    supplier: t('roles.supplier', { defaultValue: 'Поставщик и Подрядчик' }),
    partner: t('roles.partner', { defaultValue: 'Партнёр и Представитель' }),
  };

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col overflow-x-hidden border-r border-hairline bg-alabaster transition-all duration-200 md:flex',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      {/* Блок 1: Role & Workspace Switcher */}
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl p-1.5 text-left outline-none transition-colors hover:bg-ice-navy/60 focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-navy font-bold text-primary-foreground shadow-xs">
                      {(companyName || 'R')[0].toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-charcoal">{companyName || t('app.name')}</p>
                      <p className="truncate text-xs text-muted-foreground">{roleTitles[roleContour]}</p>
                    </div>
                    <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-60 rounded-xl bg-card p-1 shadow-lg">
                  <DropdownMenuLabel className="text-xs text-muted-foreground">
                    {t('roles.selectContour', { defaultValue: 'Ролевой контур' })}
                  </DropdownMenuLabel>
                  <DropdownMenuItem onClick={() => handleSelectRole('buyer')} className="rounded-lg text-xs">
                    {roleTitles.buyer}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleSelectRole('supplier')} className="rounded-lg text-xs">
                    {roleTitles.supplier}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleSelectRole('partner')} className="rounded-lg text-xs">
                    {roleTitles.partner}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5 font-medium text-charcoal">
                      {me?.can_act ? (
                        <>
                          <ShieldCheck className="size-3.5 text-sage" />
                          {t('roles.fullAccess', { defaultValue: 'Полный доступ' })}
                        </>
                      ) : (
                        <>
                          <Eye className="size-3.5 text-sand" />
                          {t('roles.viewOnly', { defaultValue: 'Режим наблюдателя' })}
                        </>
                      )}
                    </span>
                  </div>
                </DropdownMenuContent>
              </DropdownMenu>

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

      {/* Блок 3: Активные сделки (для развернутого сайдбара) */}
      {!collapsed && deals.length > 0 && (
        <div className="border-t border-hairline px-3 py-2.5">
          <div className="mb-1 flex items-center justify-between px-1">
            <span className="text-xs font-medium tracking-wider text-muted-foreground/80 uppercase">
              {t('nav.activeDeals', { defaultValue: 'Сделки в работе' })}
            </span>
            <button
              type="button"
              onClick={() => navigate('/requests/new')}
              className="rounded-md p-0.5 text-muted-foreground hover:bg-ice-navy hover:text-navy"
              title={t('pages.requests.new')}
            >
              <Plus className="size-3.5" />
            </button>
          </div>
          <ul className="flex flex-col gap-1">
            {deals.map((deal) => {
              const active = location.pathname === `/deals/${deal.id}`;
              return (
                <li key={deal.id}>
                  <button
                    type="button"
                    onClick={() => navigate(`/deals/${deal.id}`)}
                    title={deal.title ? `${deal.number}: ${deal.title}` : deal.number}
                    className={cn(
                      'group relative flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-charcoal transition-colors hover:bg-ice-navy/60 hover:text-navy',
                      active && 'bg-ice-navy font-semibold text-navy',
                    )}
                  >
                    {active && <span className="absolute left-0 top-1.5 h-4 w-1 rounded-r-full bg-navy" />}
                    <span className="size-1.5 shrink-0 rounded-full bg-sand" />
                    <span className="font-mono text-xs">{deal.number}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Блок 4: Ваш менеджер */}
      {!collapsed && (
        <div className="border-t border-hairline p-3">
          <div className="flex items-center justify-between rounded-xl border border-hairline bg-canvas p-2.5 shadow-2xs">
            <div className="flex min-w-0 items-center gap-2">
              <div className="relative flex size-8 shrink-0 items-center justify-center rounded-full bg-ice-navy text-xs font-semibold text-navy">
                M
                <span
                  className="absolute right-0 bottom-0 size-2 rounded-full border border-canvas bg-sage"
                  title="Online"
                />
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-charcoal">{t('manager.title', { defaultValue: 'Менеджер RailTech' })}</p>
                <p className="truncate text-xs text-muted-foreground">{t('manager.directSupport', { defaultValue: 'Прямая связь' })}</p>
              </div>
            </div>
            <ManagerButton dealId={null} compact label={t('manager.contactSupport', { defaultValue: 'Чат с персональным менеджером' })} />
          </div>
        </div>
      )}
    </aside>
  );
}
