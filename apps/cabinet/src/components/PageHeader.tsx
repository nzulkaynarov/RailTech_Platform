import type { ReactNode } from 'react';

import { usePageTitle } from '@/hooks/usePageTitle';

/** Заголовок экрана: один `h1` на страницу + действия справа (на телефоне — под заголовком). */
export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  usePageTitle(title);
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="min-w-0 text-xl font-semibold break-words md:text-2xl">{title}</h1>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
