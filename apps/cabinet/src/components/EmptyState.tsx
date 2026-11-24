import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Search } from 'lucide-react';

import { Button } from '@/components/ui/button';

/** Пустое состояние экрана: иконка (декоративная), заголовок, пояснение, действие. */
export function EmptyState({
  icon: Icon,
  title,
  text,
  children,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  children?: ReactNode;
}) {
  return (
    <section className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-muted/60 px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-lg bg-accent text-primary">
        <Icon className="size-6 text-primary" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      {children}
    </section>
  );
}

/**
 * «Ничего не найдено» для отфильтрованного списка: то же пустое состояние с кнопкой сброса фильтра и поиска.
 * Один вид на все списки кабинета (пустой список без фильтра — обычный `EmptyState` со своим значком).
 */
export function NoMatchState({
  title,
  text,
  resetLabel,
  onReset,
}: {
  title: string;
  text: string;
  resetLabel: string;
  onReset: () => void;
}) {
  return (
    <EmptyState icon={Search} title={title} text={text}>
      <Button variant="outline" onClick={onReset}>
        {resetLabel}
      </Button>
    </EmptyState>
  );
}
