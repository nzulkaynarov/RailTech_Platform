import { useMemo } from 'react';
import { useNow } from '@/hooks/useNow';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Clock, Pause, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useMySubscription } from '@/hooks/useAccounts';
import { useUserStore } from '@/store/userStore';
import { cn } from '@/lib/utils';

interface SubscriptionStatusBannerProps {
  onNavigate?: (target: string) => void;
  onDismiss?: () => void;
}

/**
 * Shell-level banner for SELLER/MANUFACTURER companies. Surfaces:
 *  - SUSPENDED: hard block, destructive tone
 *  - PAST_DUE:  destructive tone, nudges the user to pay now
 *  - valid_until ≤ 7 days away: warning tone with renewal CTA
 *
 * Hidden for CLIENT-only contexts, platform admins, and when no subscription
 * exists (fresh users who haven't applied for seller role yet).
 */
export function SubscriptionStatusBanner({ onNavigate, onDismiss }: SubscriptionStatusBannerProps) {
  const { t } = useTranslation();
  const activeStatus = useUserStore((s) => s.activeStatus);
  const role = useUserStore((s) => s.role);
  const sellerSubscriptionOperational = useUserStore((s) => s.sellerSubscriptionOperational);
  const { data: sub } = useMySubscription();
  // Часы для «осталось дней»: чистый рендер + баннер сам переходит в «истекла» без перезагрузки.
  const now = useNow();

  const relevantForRole =
    activeStatus === 'SELLER';

  const alert = useMemo(() => {
    if (role === 'ADMIN') return null;
    if (!relevantForRole) return null;

    // Authoritative backend signal (/me seller_subscription_operational): the
    // seller cannot perform paid writes (send КП, sign contract, issue act) —
    // they return SUBSCRIPTION_REQUIRED. Covers the "no subscription at all"
    // case the sub-detail branches below miss (they bail on `!sub`).
    if (sellerSubscriptionOperational === false && !sub) {
      return {
        tone: 'destructive' as const,
        icon: AlertCircle,
        title: t('mySubscription.alerts.requiredTitle'),
        hint: t('mySubscription.alerts.requiredHint'),
      };
    }
    if (!sub) return null;

    if (sub.status === 'SUSPENDED') {
      return {
        tone: 'destructive' as const,
        icon: Pause,
        title: t('mySubscription.alerts.suspendedTitle'),
        hint: t('mySubscription.alerts.suspendedHint'),
      };
    }
    if (sub.status === 'PAST_DUE') {
      return {
        tone: 'destructive' as const,
        icon: AlertCircle,
        title: t('mySubscription.alerts.pastDueTitle'),
        hint: t('mySubscription.alerts.pastDueHint'),
      };
    }
    if (sub.valid_until) {
      const diff = new Date(sub.valid_until).getTime() - now;
      const days = Math.ceil(diff / 86_400_000);
      if (diff < 0) {
        return {
          tone: 'destructive' as const,
          icon: AlertCircle,
          title: t('mySubscription.alerts.pastDueTitle'),
          hint: t('mySubscription.alerts.pastDueHint'),
        };
      }
      if (days <= 7) {
        return {
          tone: 'warning' as const,
          icon: Clock,
          title: t('mySubscription.alerts.expiringTitle', { days }),
          hint: t('mySubscription.alerts.expiringHint'),
        };
      }
    }
    return null;
  }, [role, relevantForRole, sub, sellerSubscriptionOperational, now, t]);

  if (!alert) return null;

  const Icon = alert.icon;
  const toneCls =
    alert.tone === 'destructive'
      ? 'border-destructive/40 bg-destructive/5'
      : 'border-warning/40 bg-warning/5';
  const iconCls = alert.tone === 'destructive' ? 'text-destructive' : 'text-warning';
  const titleCls = alert.tone === 'destructive' ? 'text-destructive' : 'text-warning';

  return (
    <div className={cn('flex items-start gap-3 rounded-md border p-3 text-xs', toneCls)}>
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', iconCls)} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <div className={cn('font-medium', titleCls)}>{alert.title}</div>
        <div className="mt-0.5 text-muted-foreground">{alert.hint}</div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {onNavigate ? (
          <Button
            size="sm"
            variant={alert.tone === 'destructive' ? 'destructive' : 'default'}
            className="h-7 text-xs"
            onClick={() => onNavigate('my-subscription')}
          >
            {t('mySubscription.payNow')}
          </Button>
        ) : null}
        {onDismiss ? (
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={onDismiss}
            aria-label={t('common.close')}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        ) : null}
      </div>
    </div>
  );
}
