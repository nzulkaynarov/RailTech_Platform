import { useTranslation } from 'react-i18next';

import type { DocLinkView } from '@/api/portal';

/**
 * Что показать гостю, кроме состава КП (ДК-3): у счёта — реквизиты для оплаты и справка «Оплачено?» (нового пути оплаты нет:
 * платёж сверяет продавец); у договора и акта — одна строка, что это за документ и как ответить. Только клиентская
 * проекция: ни себестоимости, ни наценки сервер не отдаёт.
 */
export function DocLinkExtra({ doc }: { doc: DocLinkView }) {
  const { t } = useTranslation();
  if (doc.kind === 'invoice') {
    return (
      <section aria-labelledby="doc-pay-title" className="flex flex-col gap-3 rounded-lg border bg-card p-4">
        <h2 id="doc-pay-title" className="text-base font-semibold">
          {t('docLink.pay.title')}
        </h2>
        {doc.payment_details ? (
          <pre className="whitespace-pre-wrap break-words font-sans text-sm">{doc.payment_details}</pre>
        ) : (
          <p className="text-sm text-muted-foreground">{t('docLink.pay.none')}</p>
        )}
        <p className="text-sm text-muted-foreground">{t('docLink.pay.paidQuestion')}</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="doc-about-title" className="flex flex-col gap-2 rounded-lg border bg-card p-4">
      <h2 id="doc-about-title" className="text-base font-semibold">
        {t('docLink.about.title', { context: doc.kind })}
      </h2>
      <p className="text-sm text-muted-foreground">{t('docLink.about.text', { context: doc.kind, from: doc.from_name })}</p>
    </section>
  );
}
