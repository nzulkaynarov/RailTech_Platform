import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { NAV_ITEMS } from '@/app/nav';
import { cn } from '@/lib/utils';

/** Боковая навигация десктопа (от `md`): все разделы, активный — `aria-current="page"` (NavLink). */
export function SideNav({ companyName }: { companyName?: string }) {
  const { t } = useTranslation();
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-card md:flex">
      <div className="border-b px-4 py-4">
        <p className="text-sm font-semibold">{t('app.name')}</p>
        {companyName ? <p className="truncate text-xs text-muted-foreground">{companyName}</p> : null}
      </div>
      <nav aria-label={t('app.sideNav')} className="flex-1 overflow-y-auto p-2">
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring',
                    isActive && 'bg-accent font-medium text-accent-foreground',
                  )
                }
              >
                <item.icon className="size-4" aria-hidden="true" />
                {t(item.labelKey)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
