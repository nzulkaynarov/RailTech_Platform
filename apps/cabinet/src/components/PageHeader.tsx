import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';

import { usePageTitle } from '@/hooks/usePageTitle';
import { usePageCrumb } from './shell/crumbs';

export interface PageHeaderProps {
  title: string;
  subtitle?: string | null;
  actions?: ReactNode;
  icon?: LucideIcon;
  badge?: ReactNode;
  /** Номер документа для хлебных крошек оболочки (KP-…, D-…, Z-…) — из уже загруженных данных экрана. */
  crumb?: string | null;
}

/**
 * Заголовок экрана в эстетике минимализма:
 * крупная иконка в скруглённом квадрате основного цвета (bg-primary), один h1, статус/роль, подзаголовок и действия справа.
 */
export function PageHeader({ title, subtitle, actions, icon: Icon, badge, crumb }: PageHeaderProps) {
  usePageTitle(title);
  usePageCrumb(crumb);
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
      <div className="flex min-w-0 items-center gap-3.5">
        {Icon ? (
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs md:size-12 md:rounded-2xl">
            <Icon className="size-5 text-primary-foreground md:size-6" aria-hidden="true" />
          </div>
        ) : null}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-primary break-words md:text-2xl">{title}</h1>
            {badge}
          </div>
          {subtitle ? <p className="mt-1 text-xs text-muted-foreground break-words">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
