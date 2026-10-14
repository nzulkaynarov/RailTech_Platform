import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldAlert, Receipt, Sparkles, X, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useQuoteSendGate, type QuoteSendBlockReason } from '@/hooks/useQuoteSendGate';

interface QuoteSendGateBannerProps {
  /** App-level hash navigation (handleNavigate). Renders the CTA when provided. */
  onNavigate?: (target: string) => void;
  /**
   * U2: allow the seller to fold the strip away for THIS visit, reclaiming its ~29px for КП lines
   * on a 14" screen. The blocker itself is unchanged and the disabled «Отправить» button still
   * explains it at the point of action, so nothing is lost — and the banner comes back on reload
   * (state is deliberately not persisted: a persistent account problem should keep re-announcing
   * itself). Omitted ⇒ the original non-dismissible banner.
   */
  dismissible?: boolean;
}

interface ReasonMeta {
  icon: LucideIcon;
  messageKey: string;
  ctaKey: string;
  /** hash-nav target for the CTA. */
  target: string;
}

/** Reason → message + CTA. Targets are existing hash routes: `my-subscription` (the plan/tariff
 * page) and `help`. */
const REASON_META: Record<QuoteSendBlockReason, ReasonMeta> = {
  subscription: {
    icon: Receipt,
    messageKey: 'quote.sendGate.subscription',
    ctaKey: 'quote.sendGate.subscriptionCta',
    target: 'my-subscription',
  },
  demo: {
    icon: Sparkles,
    messageKey: 'quote.sendGate.demo',
    ctaKey: 'quote.sendGate.demoCta',
    target: 'my-subscription',
  },
  // Запрет платформы. Вести в раздел подписки здесь БЕСПОЛЕЗНО: подписка там написана
  // активной, и продавец ходит по кругу. Адресат вопроса — поддержка платформы.
  disabled_by_operator: {
    icon: ShieldAlert,
    messageKey: 'quote.sendGate.disabledByOperator',
    ctaKey: 'quote.sendGate.disabledByOperatorCta',
    target: 'help',
  },
};

/**
 * WP-H — proactive КП send-gate banner. Warns a seller who cannot send the КП (no subscription,
 * a DEMO grant, or a platform ban) up-front on the builder, instead of at the end after an hour of
 * data entry. Non-blocking and NOT dismissible — it reflects a persistent account state and clears
 * on its own once the blocker is resolved. Renders only on the seller side and only while blocked.
 * Message order mirrors the backend send_to_client gates (see useQuoteSendGate).
 */
export function QuoteSendGateBanner({ onNavigate, dismissible }: QuoteSendGateBannerProps) {
  const { t } = useTranslation();
  const gate = useQuoteSendGate();
  const [dismissed, setDismissed] = useState(false);

  if (!gate.blocked || !gate.reason || (dismissible && dismissed)) return null;

  const meta = REASON_META[gate.reason];
  const Icon = meta.icon;

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-warning/40 bg-warning/5 px-4 py-1.5 text-xs text-warning"
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{t(meta.messageKey)}</span>
      {onNavigate ? (
        <Button
          variant="outline"
          size="sm"
          className="h-7 shrink-0 text-xs"
          onClick={() => onNavigate(meta.target)}
        >
          {t(meta.ctaKey)}
        </Button>
      ) : null}
      {dismissible && (
        <Button
          variant="ghost"
          size="icon-xs"
          className="size-6 shrink-0 text-warning"
          onClick={() => setDismissed(true)}
          aria-label={t('common.close')}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

export default QuoteSendGateBanner;
