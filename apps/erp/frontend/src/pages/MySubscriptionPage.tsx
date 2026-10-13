import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CreditCard,
  Calendar,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Wallet,
  Pause,
  Play,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import { PageShell } from './shared/PageShell';
import { DetailKPIGrid } from '@/components/Shared/DetailKPIGrid';
import { SubscriptionPayDialog } from '@/components/Shared/SubscriptionPayDialog';
import { useMySubscription } from '@/hooks/useAccounts';
import { subscriptionPlanLabelKey, subscriptionStatusLabelKey } from '@/lib/codes';

function statusTone(status?: string | null): 'success' | 'warning' | 'destructive' | 'info' | 'default' {
  switch (status) {
    case 'ACTIVE':
      return 'success';
    case 'TRIAL':
      return 'info';
    case 'PAST_DUE':
    case 'SUSPENDED':
    case 'CANCELLED':
      return 'destructive';
    default:
      return 'default';
  }
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return null;
  const diff = date.getTime() - Date.now();
  return Math.ceil(diff / 86_400_000);
}

/**
 * Standalone page — plan витрина под своим PageShell-заголовком.
 * Тело вынесено в MySubscriptionContent, чтобы Settings Hub (секция «Биллинг», S5/P7)
 * переиспользовал его БЕЗ второго заголовка (в настройках уже есть h1 + таб).
 */
export function MySubscriptionPage() {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('mySubscription.title')}
      description={t('mySubscription.description')}
      icon={<CreditCard className="h-5 w-5" />}
    >
      <MySubscriptionContent />
    </PageShell>
  );
}

/** Тело витрины подписки без PageShell — переиспользуется страницей и секцией «Биллинг». */
export function MySubscriptionContent() {
  const { t } = useTranslation();
  const { data: sub, isLoading, isError, refetch } = useMySubscription();
  const [payOpen, setPayOpen] = useState(false);

  // `plan_display` / `status_display` are Russian-only `get_FOO_display()` output — keep
  // them only as a fallback when the CODE is not in the localized map.
  const planLabel = (code?: string | null, fallback?: string | null): string => {
    const key = subscriptionPlanLabelKey(code);
    return key ? t(key) : fallback || code || '';
  };
  const statusLabel = (code?: string | null, fallback?: string | null): string => {
    const key = subscriptionStatusLabelKey(code);
    return key ? t(key) : fallback || code || '';
  };

  const remainingDays = useMemo(() => daysUntil(sub?.valid_until), [sub]);
  const isExpiringSoon = remainingDays !== null && remainingDays <= 7 && remainingDays >= 0;
  const isPastDue = sub?.status === 'PAST_DUE' || (remainingDays !== null && remainingDays < 0);
  const isSuspended = sub?.status === 'SUSPENDED';

  return (
    // Own vertical rhythm (PageShell previously supplied the flex gap around these blocks).
    <div className="flex flex-col gap-6">
      {isLoading ? (
        <Card>
          <CardContent className="p-6">
            <Skeleton className="h-20 w-full" />
          </CardContent>
        </Card>
      ) : isError ? (
        // A failed fetch must read as an error with a retry — never as the
        // "no subscription" empty state (which looks like a successful load).
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
            <p className="text-sm font-medium">{t('common.loadError')}</p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              {t('common.retry')}
            </Button>
          </CardContent>
        </Card>
      ) : !sub ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <AlertCircle className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <div>
              <h3 className="text-base font-semibold">{t('mySubscription.noneTitle')}</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('mySubscription.noneHint')}
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {isSuspended ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
              <Pause className="mt-0.5 h-3.5 w-3.5 text-destructive" aria-hidden="true" />
              <div>
                <div className="font-medium text-destructive">
                  {t('mySubscription.alerts.suspendedTitle')}
                </div>
                <div className="text-muted-foreground">
                  {/* Причина приходит с сервера: раньше она жила только в журнале доступа за
                      правом оператора, и отключённая сторона видела общий текст, не понимая,
                      за что её отключили. Эталон Stripe: ограничение называет причину. */}
                  {sub?.suspended_reason
                    ? t('mySubscription.alerts.suspendedWithReason', { reason: sub.suspended_reason })
                    : t('mySubscription.alerts.suspendedHint')}
                </div>
              </div>
            </div>
          ) : isPastDue ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 text-destructive" aria-hidden="true" />
              <div>
                <div className="font-medium text-destructive">
                  {t('mySubscription.alerts.pastDueTitle')}
                </div>
                <div className="text-muted-foreground">
                  {t('mySubscription.alerts.pastDueHint')}
                </div>
              </div>
            </div>
          ) : isExpiringSoon ? (
            <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
              <Calendar className="mt-0.5 h-3.5 w-3.5 text-warning" aria-hidden="true" />
              <div>
                <div className="font-medium text-warning">
                  {t('mySubscription.alerts.expiringTitle', { days: remainingDays })}
                </div>
                <div className="text-muted-foreground">
                  {t('mySubscription.alerts.expiringHint')}
                </div>
              </div>
            </div>
          ) : null}

          <DetailKPIGrid
            columns={4}
            items={[
              {
                label: t('mySubscription.kpi.plan'),
                value: planLabel(sub.plan, sub.plan_display),
                icon: <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />,
              },
              {
                label: t('mySubscription.kpi.status'),
                value: statusLabel(sub.status, sub.status_display),
                icon:
                  sub.status === 'ACTIVE'
                    ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                    : <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />,
                tone: statusTone(sub.status),
              },
              {
                label: t('mySubscription.kpi.monthly'),
                value:
                  sub.monthly_rate
                    ? `${sub.monthly_rate} ${sub.currency_code ?? ''}`.trim()
                    : '—',
              },
              {
                label: t('mySubscription.kpi.validUntil'),
                value: sub.valid_until ?? '—',
                hint:
                  remainingDays != null
                    ? t('mySubscription.kpi.remaining', { count: Math.max(0, remainingDays) })
                    : undefined,
              },
            ]}
          />

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('mySubscription.billing.title')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Row label={t('mySubscription.billing.lastPayment')} value={sub.last_payment_date ?? '—'} />
                <Row label={t('mySubscription.billing.nextPayment')} value={sub.next_payment_date ?? '—'} />
                <Row label={t('mySubscription.billing.validFrom')} value={sub.valid_from ?? '—'} />
                <Row label={t('mySubscription.billing.company')} value={sub.company_name ?? '—'} />
              </dl>

              <Separator />

              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <div className="text-muted-foreground">
                  {t('mySubscription.billing.manualModeHint')}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetch()}
                    className="h-8 text-xs"
                  >
                    <Play className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('common.refresh')}
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => setPayOpen(true)}
                    disabled={sub.status === 'CANCELLED'}
                    className="h-8 text-xs"
                  >
                    <Wallet className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('mySubscription.payNow')}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <SubscriptionPayDialog
            subscriptionId={sub.id}
            open={payOpen}
            onOpenChange={(v) => {
              setPayOpen(v);
              if (!v) refetch();
            }}
          />
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-start justify-between gap-2 rounded-md border border-muted/50 p-2">
      <dt className="text-muted-foreground">
        <Badge variant="outline" className="text-xs">{label}</Badge>
      </dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </div>
  );
}

export default MySubscriptionPage;
