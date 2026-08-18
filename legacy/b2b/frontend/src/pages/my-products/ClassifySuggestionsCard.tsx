import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatHSCode } from '@/lib/hsCode';
import type { HSSuggestion } from './useHsClassify';

/** Предложения кодов ТН ВЭД: ИИ выбрал ИЗ справочника, карточки меняются после подтверждения. */
export function ClassifySuggestionsCard({
  suggestions,
  onReject,
  onApplyAll,
  onCancel,
}: {
  suggestions: HSSuggestion[];
  onReject: (productId: number) => void;
  onApplyAll: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="border-info/40 bg-info/5">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('nomenclature.classify.title', { count: suggestions.length })}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">{t('nomenclature.classify.hint')}</p>
        {suggestions.map((row) => (
          <div key={row.product_id} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{row.name}</div>
              <div className="text-xs text-muted-foreground">
                <span className="font-mono font-semibold">{formatHSCode(row.suggested_code)}</span>
                {row.explanation ? ` — ${row.explanation}` : ''}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => onReject(row.product_id)}>
              {t('nomenclature.classify.reject')}
            </Button>
          </div>
        ))}
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={onApplyAll}>{t('nomenclature.classify.applyAll', { count: suggestions.length })}</Button>
          <Button variant="outline" size="sm" onClick={onCancel}>{t('nomenclature.classify.cancel')}</Button>
        </div>
      </CardContent>
    </Card>
  );
}
