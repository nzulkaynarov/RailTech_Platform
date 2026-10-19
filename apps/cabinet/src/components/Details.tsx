import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { LucideIcon } from 'lucide-react';

import type { DealRef } from '@/api/portal';
import { cn } from '@/lib/utils';

/** Пары «подпись — значение» карточки объекта; на телефоне — столбиком, от `sm` — в две колонки. */
export function DetailList({ items, className }: { items: Array<{ label: string; value: ReactNode } | null | false>; className?: string }) {
  return (
    <dl className={cn('grid gap-3 text-sm sm:grid-cols-2', className)}>
      {items.filter(Boolean).map((item) => {
        const { label, value } = item as { label: string; value: ReactNode };
        return (
          <div key={label} className="min-w-0">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium break-words">{value}</dd>
          </div>
        );
      })}
    </dl>
  );
}

/**
 * Ссылка на сделку — цель deep-link бота (`deal_<id>`), собирает всё по сделке. Клиент видит номер
 * (`deal.number`), а не внутренний id; название (`deal.title`) — по запросу, рядом с номером.
 */
export function DealLink({ deal, showTitle = false }: { deal: DealRef | null | undefined; showTitle?: boolean }) {
  const { t } = useTranslation();
  if (!deal) return <>{t('common.noDeal')}</>;
  return (
    <>
      <Link
        to={`/deals/${deal.id}`}
        className="relative z-10 rounded-sm text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t('common.dealNumber', { number: deal.number })}
      </Link>
      {showTitle && deal.title ? <span className="font-normal text-muted-foreground"> · {deal.title}</span> : null}
    </>
  );
}

/** Плашка-сводка над списком («2 КП ждут вашего решения»). */
export function SummaryNote({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <p className="mb-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

/** Подпись секции внутри экрана (h2). */
export function SectionTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-base font-semibold">{children}</h2>
      {actions}
    </div>
  );
}
