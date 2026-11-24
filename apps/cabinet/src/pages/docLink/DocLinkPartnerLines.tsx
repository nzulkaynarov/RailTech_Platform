import { useTranslation } from 'react-i18next';

import type { DocLinkView } from '@/api/portal';
import { formatMoney } from '@/lib/format';

/**
 * Состав запроса цены или заказа поставщику для партнёра по ссылке (ДК-5): его позиции, количество, его цены и сроки.
 * Клиента заявки, нашей цены продажи и наценки сервер не отдаёт — здесь их нет. Одна вёрстка на любой ширине: строка —
 * название и сумма, под ним «количество × цена» и срок.
 */
export function DocLinkPartnerLines({ doc }: { doc: DocLinkView }) {
  const { t } = useTranslation();
  const lines = doc.partner_lines ?? [];
  const priced = doc.kind === 'supplier_order';
  return (
    <section aria-labelledby="doc-lines-title" className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <h2 id="doc-lines-title" className="text-base font-semibold">
        {t('docLink.lines.titlePartner')}
      </h2>
      <ul className="flex flex-col divide-y" aria-labelledby="doc-lines-title">
        {lines.map((line) => (
          <li key={line.id} className="flex items-start justify-between gap-4 px-3 py-2 text-sm">
            <div className="min-w-0">
              <p className="font-medium break-words">{line.name}</p>
              {line.article ? <p className="text-muted-foreground break-words">{line.article}</p> : null}
              <p className="text-muted-foreground tabular-nums">
                {line.unit_price
                  ? t('docLink.lines.price', { quantity: `${line.quantity} ${line.unit}`.trim(), price: formatMoney(line.unit_price) })
                  : `${line.quantity} ${line.unit}`.trim()}
                {line.lead_days != null ? ` · ${t('docLink.partner.leadDays', { days: line.lead_days })}` : ''}
              </p>
            </div>
            {priced && line.total ? <p className="shrink-0 text-right font-medium tabular-nums">{formatMoney(line.total)}</p> : null}
          </li>
        ))}
      </ul>
      {priced ? (
        <dl className="flex flex-col gap-1 border-t pt-3 text-sm">
          <div className="flex justify-between gap-4 font-semibold">
            <dt>{t('docLink.lines.totalPlain')}</dt>
            <dd className="tabular-nums">{formatMoney(doc.total)}</dd>
          </div>
        </dl>
      ) : null}
      {doc.partner_note ? <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{doc.partner_note}</p> : null}
      {doc.answer_note ? (
        <p className="whitespace-pre-wrap break-words text-sm">
          <span className="text-muted-foreground">{t('docLink.partner.yourAnswer')} </span>
          {doc.answer_note}
        </p>
      ) : null}
    </section>
  );
}
