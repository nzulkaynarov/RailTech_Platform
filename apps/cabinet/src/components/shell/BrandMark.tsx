import { cn } from '@/lib/utils';

/**
 * Марка RailTech в оболочке кабинета (CAB-FIX-2, K14): плитка «RT» основного цвета. Имя для чтения экраном —
 * у подписи рядом («RailTech Cabinet»); без подписи (свёрнутый сайдбар, шапка телефона) — `label`.
 */
export function BrandMark({ label, className }: { label?: string; className?: string }) {
  return (
    <span
      className={cn(
        'flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-xs font-bold tracking-tight text-primary-foreground shadow-xs',
        className,
      )}
      {...(label ? { role: 'img', 'aria-label': label, title: label } : { 'aria-hidden': true })}
    >
      RT
    </span>
  );
}
