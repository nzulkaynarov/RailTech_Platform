import { useTranslation } from 'react-i18next';
import { ShieldAlert, Receipt, Sparkles, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useQuoteSendGate, type QuoteSendBlockReason } from '@/hooks/useQuoteSendGate';

interface QuoteSendGateBannerProps {
  /** App-level hash navigation (handleNavigate). Renders the CTA when provided. */
  onNavigate?: (target: string) => void;
}

interface ReasonMeta {
  icon: LucideIcon;
  messageKey: string;
  ctaKey: string;
  /** hash-nav target for the CTA. */
  target: string;
}

/** Reason → message + CTA. Targets are existing hash routes: `settings` (Settings Hub → company /
 * documents, where a seller completes KYC) and `my-subscription` (the plan/tariff page). */
const REASON_META: Record<QuoteSendBlockReason, ReasonMeta> = {
  kyc: {
    icon: ShieldAlert,
    messageKey: 'quote.sendGate.kyc',
    ctaKey: 'quote.sendGate.kycCta',
    target: 'settings',
  },
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
};

/**
 * WP-H — proactive КП send-gate banner. Warns a seller who cannot send the КП (KYC below L2, no
 * subscription, or a DEMO grant) up-front on the builder, instead of at the end after an hour of
 * data entry. Non-blocking and NOT dismissible — it reflects a persistent account state and clears
 * on its own once the blocker is resolved. Renders only on the seller side and only while blocked.
 * Message order mirrors the backend send_to_client gates (see useQuoteSendGate).
 */
export function QuoteSendGateBanner({ onNavigate }: QuoteSendGateBannerProps) {
  const { t } = useTranslation();
  const gate = useQuoteSendGate();

  if (!gate.blocked || !gate.reason) return null;

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
    </div>
  );
}

export default QuoteSendGateBanner;
