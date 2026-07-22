import { useTranslation } from 'react-i18next';
import { ArrowLeft, Briefcase, User, Loader2 } from 'lucide-react';
import type { Deal } from '@/api/crmApi';
import { DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { buyerStatus } from '@/lib/requestStatus';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/ui/StatusBadge';

/**
 * RequestDetail header: back button, editable/read-only title, stage badge and the
 * counterparty line. A SOLO deal (calculator draft) carries NO buyer company — every
 * counterparty field (`client_name`/`company_name`/`contact_name`) is null, which is a
 * legitimate state since Wave E. Instead of a blank line we surface an explicit
 * «Без клиента (расчёт)» label so the page reads intentionally rather than broken.
 */
export function RequestHeader({
  deal,
  isBuyerSide,
  canEditRequest,
  isSavingTitle,
  onSaveTitle,
  onBack,
}: {
  deal: Deal;
  isBuyerSide: boolean;
  canEditRequest: boolean;
  isSavingTitle: boolean;
  onSaveTitle: (title: string, onError: (err: unknown) => void) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  // Null-safe counterparty label — a solo/calculator deal has no buyer at all.
  const counterparty =
    deal.client_name || deal.company_name || deal.contact_name || t('requestDetailActions.soloNoClient');

  return (
    <div className="flex items-center gap-3">
      <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
      <div className="flex-1">
        <div className="flex items-center gap-3">
          {canEditRequest ? (
            <div className="flex max-w-md flex-1 items-center gap-2">
              <Input
                defaultValue={deal.title || ''}
                onBlur={(e) => {
                  const value = e.target.value.trim();
                  // Empty title is not a valid edit — restore the previous value in the field
                  // instead of silently keeping the old DB value while the input looks blank.
                  if (!value) { e.target.value = deal.title || ''; return; }
                  if (value !== (deal.title || '')) {
                    onSaveTitle(value, () => { e.target.value = deal.title || ''; });
                  }
                }}
                className="h-auto border-transparent bg-transparent px-1 text-2xl font-bold hover:border-input focus-visible:border-input"
                aria-label={t('requestDetailActions.titleLabel')}
              />
              {isSavingTitle && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />}
            </div>
          ) : (
            <h1 className="text-2xl font-bold">{deal.title || `#${deal.id}`}</h1>
          )}
          {isBuyerSide ? (
            <StatusBadge label={t(buyerStatus(deal.stage_code).labelKey)} variant={buyerStatus(deal.stage_code).variant} />
          ) : (
            <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
              {deal.stage_code && DEAL_STAGE_LABEL_KEY[deal.stage_code]
                ? t(DEAL_STAGE_LABEL_KEY[deal.stage_code])
                : deal.stage_name}
            </Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-2">
          <Briefcase className="h-3.5 w-3.5" />
          {counterparty}
          {deal.manager_name && (
            <>
              <span className="text-border">|</span>
              <User className="h-3.5 w-3.5" />
              {deal.manager_name}
            </>
          )}
        </p>
        {/* Multi-seller routing — the seller companies this RFQ is routed to. */}
        {(deal.target_sellers_data?.length ?? 0) > 0 && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">{t('requestDetailActions.routedTo')}:</span>
            {deal.target_sellers_data!.map((seller) => (
              <Badge key={seller.id} variant="secondary">{seller.name}</Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default RequestHeader;
