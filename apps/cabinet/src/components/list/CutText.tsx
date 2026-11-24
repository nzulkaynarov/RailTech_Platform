import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Обрезанный текст ячейки: не больше `lines` строк, полный текст — в подсказке (`title`) и в дереве доступности
 * (обрезка только визуальная). Для коротких значений без обрезки не нужен.
 */
export function CutText({ text, lines = 2, className, children }: { text: string; lines?: 1 | 2 | 3; className?: string; children?: ReactNode }) {
  return (
    <span
      title={text}
      className={cn(lines === 1 ? 'line-clamp-1' : lines === 2 ? 'line-clamp-2' : 'line-clamp-3', 'break-words', className)}
    >
      {children ?? text}
    </span>
  );
}
