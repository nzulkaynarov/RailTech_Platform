import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, X } from 'lucide-react';

import { isWithin, type NavItem } from '@/app/nav';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import { useNav } from '@/session/useNav';

const tabClass =
  'flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';

/**
 * Нижняя навигация телефона (до `md`): четыре основных раздела и «Ещё» — лист снизу с остальными.
 * Отступ снизу учитывает safe-area (iPhone, Mini App на весь экран).
 */
export function BottomNav() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [moreOpen, setMoreOpen] = useState(false);
  const { primary, secondary, groups } = useNav();
  const moreActive = secondary.some((item) => isWithin(pathname, item.to));
  if (primary.length + secondary.length === 0) return null; // разделы ещё не настроены: вместо меню — экран в AppShell

  return (
    <nav
      aria-label={t('app.mainNav')}
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {/* Вкладок столько, сколько разделов у сессии (+ «Ещё», если есть остальные): у клиента прежние пять */}
      <ul
        className="grid"
        style={{
          gridTemplateColumns: `repeat(${primary.length + (secondary.length > 0 ? 1 : 0)}, minmax(0, 1fr))`,
        }}
      >
        {primary.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                cn(tabClass, isActive ? 'font-medium text-primary' : 'text-muted-foreground')
              }
            >
              <item.icon className="size-5" aria-hidden="true" />
              <span className="max-w-full truncate">{t(item.labelKey)}</span>
            </NavLink>
          </li>
        ))}
        {secondary.length > 0 && (
          <li>
            <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
              <button
                type="button"
                className={cn(tabClass, 'w-full', moreActive ? 'font-medium text-primary' : 'text-muted-foreground')}
                aria-haspopup="dialog"
                aria-expanded={moreOpen}
                onClick={() => setMoreOpen(true)}
              >
                <MoreHorizontal className="size-5" aria-hidden="true" />
                <span>{t('nav.more')}</span>
              </button>
              <SheetContent side="bottom" showCloseButton={false} className="pb-[env(safe-area-inset-bottom)]">
                <SheetHeader className="flex-row items-start justify-between gap-2">
                  <div className="flex flex-col gap-1">
                    <SheetTitle>{t('nav.moreTitle')}</SheetTitle>
                    <SheetDescription>{t('nav.moreDescription')}</SheetDescription>
                  </div>
                  <SheetClose
                    className="rounded-md p-2 text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={t('common.close')}
                    title={t('common.close')}
                  >
                    <X className="size-4" aria-hidden="true" />
                  </SheetClose>
                </SheetHeader>
                {groups ? (
                  // Обе роли: «Ещё» тоже по разделам «Покупаю / Поставляю / Компания»
                  groups
                    .map((group) => ({ ...group, items: group.items.filter((item) => secondary.includes(item)) }))
                    .filter((group) => group.items.length > 0)
                    .map((group) => (
                      <section key={group.key} aria-labelledby={`more-group-${group.key}`} className="px-4 pb-3">
                        <h3 id={`more-group-${group.key}`} className="pb-1.5 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                          {t(group.labelKey)}
                        </h3>
                        <MoreLinks items={group.items} onNavigate={() => setMoreOpen(false)} />
                      </section>
                    ))
                ) : (
                  <div className="px-4 pb-4">
                    <MoreLinks items={secondary} onNavigate={() => setMoreOpen(false)} />
                  </div>
                )}
              </SheetContent>
            </Sheet>
          </li>
        )}
      </ul>
    </nav>
  );
}

function MoreLinks({ items, onNavigate }: { items: NavItem[]; onNavigate: () => void }) {
  const { t } = useTranslation();
  return (
    <ul className="grid grid-cols-2 gap-2">
      {items.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex min-h-12 items-center gap-2 rounded-md border px-3 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
                isActive && 'border-primary font-medium text-primary',
              )
            }
          >
            <item.icon className="size-4" aria-hidden="true" />
            {t(item.labelKey)}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}
