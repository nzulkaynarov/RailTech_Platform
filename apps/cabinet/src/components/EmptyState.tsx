import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/** Пустое состояние экрана: иконка (декоративная), заголовок, пояснение, необязательное действие. */
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
    <section className="flex flex-col items-center gap-3 rounded-lg border border-dashed bg-card px-4 py-10 text-center">
      <Icon className="size-10 text-muted-foreground" aria-hidden="true" />
      <h2 className="text-base font-medium">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      {children}
    </section>
  );
}
