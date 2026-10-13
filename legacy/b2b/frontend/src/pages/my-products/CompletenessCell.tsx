import { useTranslation } from 'react-i18next';
import { CheckCircle2 } from 'lucide-react';

import type { Product } from '@/api/catalogApi';

/** Полнота словами: процент мотивирует, но действие подсказывает список недостающего. */
export function CompletenessCell({ product }: { product: Product }) {
  const { t } = useTranslation();
  const report = product.completeness;
  if (!report) return <span className="text-muted-foreground">—</span>;
  if (report.is_publishable) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-success">
        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
        {t('nomenclature.readyToPublish')}
      </span>
    );
  }
  return (
    <div className="min-w-0">
      <div className="text-sm font-medium tabular-nums">{report.percent}%</div>
      <div className="truncate text-xs text-muted-foreground">
        {/* N4: подпись — по КОДУ требования на языке интерфейса (item.label с сервера был
            только русским: EN-продавец видел «missing: Код ТН ВЭД»). label — фолбэк на случай
            нового серверного требования, ещё не известного словарю. */}
        {t('nomenclature.missing')}:{' '}
        {report.missing.map((item) => t(`nomenclature.requirement.${item.code}`, { defaultValue: item.label })).join(', ')}
      </div>
    </div>
  );
}
