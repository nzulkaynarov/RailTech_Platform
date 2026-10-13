import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import type { Product } from '@/api/catalogApi';

import { SECTION_BY_REQUIREMENT, SECTION_IDS, scrollToSection } from './anchors';

/**
 * Рейка полноты карточки (Akeneo completeness panel): процент + список недостающего,
 * где КАЖДЫЙ пункт — якорь к секции с полем. Полноту считает СЕРВЕР по сохранённой
 * карточке (`completeness.py`), поэтому у несохранённого черновика вместо процента —
 * подсказка сохранить.
 */
export function CompletenessRail({
  completeness, isCreate, className,
}: {
  completeness?: Product['completeness'];
  /** Карточка ещё не создана — сервер полноту не считал. */
  isCreate: boolean;
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('productEditor.completeness.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isCreate || !completeness ? (
          <p className="text-sm text-muted-foreground">{t('productEditor.completeness.createHint')}</p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Progress value={completeness.percent} className="h-2" />
              <span className="text-sm font-medium tabular-nums">{completeness.percent}%</span>
            </div>
            {completeness.missing.length === 0 ? (
              <p className="flex items-center gap-1.5 text-sm text-success">
                <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />
                {t('productEditor.completeness.done')}
              </p>
            ) : (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">
                  {t('productEditor.completeness.missingTitle')}
                </p>
                <ul className="space-y-1">
                  {completeness.missing.map((item) => (
                    <li key={item.code}>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-auto w-full justify-start gap-1.5 px-2 py-1 text-left whitespace-normal"
                        onClick={() => scrollToSection(SECTION_BY_REQUIREMENT[item.code] ?? SECTION_IDS.basics)}
                      >
                        <CircleAlert className="size-3.5 shrink-0 text-warning" aria-hidden="true" />
                        {/* Код → локализованная подпись (как в реестре); подпись сервера — фолбэк. */}
                        {t(`nomenclature.requirement.${item.code}`, { defaultValue: item.label })}
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
