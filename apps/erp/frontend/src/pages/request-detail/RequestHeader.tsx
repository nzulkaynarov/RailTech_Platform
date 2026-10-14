import { useTranslation } from 'react-i18next';
import { ArrowLeft, Briefcase, User } from 'lucide-react';
import type { Deal } from '@/api/crmApi';
import { DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

/**
 * RequestDetail header: back button, title, stage badge and the counterparty line. A SOLO deal
 * (calculator draft) carries NO client company — every counterparty field
 * (`client_name`/`company_name`/`contact_name`) is null, which is a legitimate state since Wave E.
 * Instead of a blank line we surface an explicit «Без клиента (расчёт)» label so the page reads
 * intentionally rather than broken.
 *
 * Правка заголовка заявки клиентом и строка «Отправлено продавцам» (маршрутизация) удалены в
 * M1-ERP-02 волна 3: заявку клиент подаёт в Cabinet, продавец в ERP один — сама компания.
 */
export function RequestHeader({ deal, onBack }: { deal: Deal; onBack: () => void }) {
  const { t } = useTranslation();
  // Null-safe counterparty label — a solo/calculator deal has no client at all.
  const counterparty =
    deal.client_name || deal.company_name || deal.contact_name || t('requestDetailActions.soloNoClient');

  return (
    <div className="flex items-center gap-3">
      <Button variant="ghost" size="icon" onClick={onBack} aria-label={t('requestDetailActions.backToRequests')}>
        <ArrowLeft className="h-4 w-4" />
      </Button>
      <div className="flex-1">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{deal.title || `#${deal.id}`}</h1>
          <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
            {deal.stage_code && DEAL_STAGE_LABEL_KEY[deal.stage_code]
              ? t(DEAL_STAGE_LABEL_KEY[deal.stage_code])
              : deal.stage_name}
          </Badge>
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
      </div>
    </div>
  );
}

export default RequestHeader;
