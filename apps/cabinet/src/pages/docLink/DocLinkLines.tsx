import { useTranslation } from 'react-i18next';

import type { DocLinkView } from '@/api/portal';
import { formatMoney, formatQuantity } from '@/lib/format';

/**
 * Состав КП для гостя по ссылке — клиентская проекция: цена продажи, без себестоимости и наценки. Одна вёрстка на любой
 * ширине (строка — название и сумма, под ним «количество × цена»): таблица из пяти колонок на телефоне не нужна, гостю
 * достаточно прочитать, что и за сколько.
 */
export function DocLinkLines({ doc }: { doc: DocLinkView }) {
  const { t } = useTranslation();
  const lines = [...doc.lines].sort((a, b) => a.line_no - b.line_no);
  return (
    <section aria-labelledby="doc-lines-title" className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <h2 id="doc-lines-title" className="text-base font-semibold">
        {t('docLink.lines.title')}
      </h2>
      <ul className="flex flex-col divide-y" aria-labelledby="doc-lines-title">
        {lines.map((line) =>
          line.kind === 'section' || line.kind === 'stage' ? (
            <li key={line.line_no} className="bg-muted px-3 py-2 text-sm font-semibold">
              {line.title}
            </li>
          ) : line.kind === 'note' ? (
            <li key={line.line_no} className="px-3 py-2 text-sm text-muted-foreground italic">
              {line.title}
            </li>
          ) : (
            <li key={line.line_no} className="flex items-start justify-between gap-4 px-3 py-2 text-sm">
              <div className="min-w-0">
                <p className="font-medium break-words">{line.title}</p>
                {line.description ? <p className="text-muted-foreground break-words">{line.description}</p> : null}
                <p className="text-muted-foreground tabular-nums">
                  {t('docLink.lines.price', {
                    quantity: formatQuantity(line.quantity, line.unit),
                    price: formatMoney(line.unit_price),
                  })}
                </p>
              </div>
              <p className="shrink-0 text-right font-medium tabular-nums">{formatMoney(line.total)}</p>
            </li>
          ),
        )}
      </ul>
      <dl className="flex flex-col gap-1 border-t pt-3 text-sm">
        {doc.subtotal ? (
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">{t('docLink.lines.subtotal')}</dt>
            <dd className="tabular-nums">{formatMoney(doc.subtotal)}</dd>
          </div>
        ) : null}
        {doc.vat ? (
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">{t('docLink.lines.vat')}</dt>
            <dd className="tabular-nums">{formatMoney(doc.vat)}</dd>
          </div>
        ) : null}
        <div className="flex justify-between gap-4 font-semibold">
          <dt>{t('docLink.lines.total')}</dt>
          <dd className="tabular-nums">{formatMoney(doc.total)}</dd>
        </div>
      </dl>
      {doc.payment_terms || doc.delivery_days || doc.delivery_note ? (
        <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
          {doc.payment_terms ? <li>{t('docLink.lines.payment', { terms: doc.payment_terms })}</li> : null}
          {doc.delivery_days ? <li>{t('docLink.lines.delivery', { days: doc.delivery_days })}</li> : null}
          {doc.delivery_note ? <li>{t('docLink.lines.note', { note: doc.delivery_note })}</li> : null}
        </ul>
      ) : null}
    </section>
  );
}
