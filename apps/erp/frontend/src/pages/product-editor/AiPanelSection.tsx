import { useTranslation } from 'react-i18next';
import { Loader2, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { AiEnrichPanel } from '../admin-catalog/AiEnrichPanel';
import type { ProductFormState } from '../admin-catalog/useProductForm';

/**
 * Панель ИИ в карточке-странице: та же механика «предложение по каждому полю», что в
 * шторке (Akeneo AI suggestions) — ИИ ПРЕДЛАГАЕТ, применяет человек, ничего не патчится
 * молча. CTA + таблица предложений (`AiEnrichPanel`) переиспользуются как есть.
 */
export function AiPanelSection({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const { draft, categoryHint, enrichPending, aiDailyCap, aiDailyRemaining, runEnrich } = form;

  // Безлимит (`null`) — это НЕ «осталось 0»; когда бэкенд лимит не прислал, не показываем ничего.
  const aiLimitText = aiDailyCap === undefined && aiDailyRemaining === undefined
    ? ''
    : aiDailyCap === null || aiDailyRemaining === null
      ? t('adminCatalog.aiEnrich.limitUnlimited')
      : t('adminCatalog.aiEnrich.limitLeft', { remaining: aiDailyRemaining ?? 0, cap: aiDailyCap ?? 0 });

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3 rounded-md border border-dashed bg-muted/40 p-3">
        <div className="space-y-0.5">
          <p className="text-sm font-medium">{t('adminCatalog.aiEnrich.title')}</p>
          <p className="text-xs text-muted-foreground">{t('adminCatalog.aiEnrich.hint')}</p>
        </div>
        {/* Остаток дневного лимита — информация рядом с кнопкой; гейт живёт на сервере (429). */}
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={runEnrich}
            disabled={enrichPending || !draft.name?.trim()}
          >
            {enrichPending
              ? <Loader2 className="size-4 animate-spin" />
              : <Sparkles className="size-4" />}
            {t('adminCatalog.aiEnrich.button')}
          </Button>
          {aiLimitText && <p className="text-xs text-muted-foreground">{aiLimitText}</p>}
        </div>
      </div>
      <AiEnrichPanel form={form} />
      {categoryHint && (
        <p className="text-xs text-muted-foreground">
          {t('adminCatalog.aiEnrich.categoryHint', { hint: categoryHint })}
        </p>
      )}
    </div>
  );
}
