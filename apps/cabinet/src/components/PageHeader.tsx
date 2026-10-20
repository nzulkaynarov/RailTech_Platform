import type { ReactNode } from 'react';

import { usePageTitle } from '@/hooks/usePageTitle';

/** Заголовок экрана: один `h1` на страницу, необязательная строка под ним (название сделки) + действия справа. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string | null; actions?: ReactNode }) {
  usePageTitle(title);
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold break-words md:text-2xl">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-muted-foreground break-words">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
