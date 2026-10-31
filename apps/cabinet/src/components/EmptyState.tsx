import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/** Пустое состояние экрана в Notion-стиле: иконка (декоративная), заголовок, пояснение, действие. */
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
    <section className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-silver bg-alabaster/60 px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-ice-navy text-navy">
        <Icon className="size-6 text-navy" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold text-charcoal">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      {children}
    </section>
  );
}
