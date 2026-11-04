import { useTranslation } from 'react-i18next';

import type { PartnerOffer } from '@/api/portal';
import { StatusBadge } from '@/components/StatusBadge';
import { formatDate, formatMoney } from '@/lib/format';

/**
 * Своя цена по карточке: сумма и валюта, срок действия, MOQ и Incoterms, «подтверждена …» и пометка свежести («устарела»,
 * «срок истёк», «скоро истекает»). Чужих цен в ответе ERP нет, сюда приходит только цена этой компании.
 */
export function OfferCell({ offer }: { offer: PartnerOffer | null }) {
  const { t, i18n } = useTranslation();
  if (!offer) return <span className="text-muted-foreground">{t('partner.noPrice')}</span>;
  const details = [
    offer.valid_until ? t('partner.validUntil', { date: formatDate(offer.valid_until, i18n.language) }) : null,
    offer.min_order_qty > 1 ? t('partner.moq', { count: offer.min_order_qty }) : null,
    offer.delivery_basis,
  ].filter(Boolean);
  return (
    <div className="flex min-w-0 flex-col items-start gap-1 sm:items-start">
      <span className="font-medium tabular-nums">{offer.price ? formatMoney(offer.price, i18n.language) : t('partner.noPrice')}</span>
      {details.map((detail) => (
        <span key={detail} className="text-xs text-muted-foreground">
          {detail}
        </span>
      ))}
      <span className="text-xs text-muted-foreground">
        {offer.confirmed_at ? t('partner.priceConfirmed', { date: formatDate(offer.confirmed_at, i18n.language) }) : t('partner.priceNotConfirmed')}
      </span>
      {offer.freshness !== 'fresh' ? <StatusBadge entity="freshness" code={offer.freshness} /> : null}
    </div>
  );
}
