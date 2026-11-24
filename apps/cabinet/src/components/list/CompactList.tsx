import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Компактный список: первые `limit` пунктов, остальные — по «Показать все (N)» и обратно «Свернуть».
 * Страница не уезжает вниз из-за длинного перечня; все данные остаются доступны. `items` — готовые `<li>`
 * (с `key`); если их не больше `limit`, кнопки нет.
 */
export function CompactList({
  items,
  limit = 4,
  label,
  className,
}: {
  items: ReactNode[];
  limit?: number;
  /** Подпись списка для диктора. */
  label?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? items : items.slice(0, limit);
  return (
    <>
      <ul aria-label={label} className={cn('flex flex-col', className)}>
        {visible}
      </ul>
      {items.length > limit ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start"
          aria-expanded={showAll}
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? t('common.showLess') : t('common.showAll', { count: items.length })}
        </Button>
      ) : null}
    </>
  );
}
