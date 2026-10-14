import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

import { usePageTitle } from '@/hooks/usePageTitle';

/** Полноэкранное состояние вне оболочки: загрузка сессии, вход по ссылке, ошибка входа из Telegram. */
export function StatusScreen({
  title,
  text,
  loading = false,
  children,
}: {
  title: string;
  text?: string;
  loading?: boolean;
  children?: ReactNode;
}) {
  usePageTitle(title);
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-8 text-foreground">
      <div className="flex w-full max-w-sm flex-col items-center gap-4 text-center" aria-live="polite" aria-busy={loading}>
        {loading ? <Loader2 className="size-8 animate-spin text-primary" aria-hidden="true" /> : null}
        <h1 className="text-xl font-semibold">{title}</h1>
        {text ? <p className="text-sm text-muted-foreground">{text}</p> : null}
        {children ? <div className="flex w-full flex-col gap-2">{children}</div> : null}
      </div>
    </main>
  );
}
