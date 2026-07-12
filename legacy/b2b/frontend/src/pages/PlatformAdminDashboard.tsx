import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ShieldCheck, ClipboardList, CreditCard, AlertTriangle, Receipt,
  LifeBuoy, Clock, TrendingUp, Loader2,
  Building2, Handshake, Users,
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import { useAdminQueue, useAdminPulse, useBulkSubscriptionStatus } from '@/hooks/useAdmin';
import { usePlatformDashboard } from '@/hooks/usePageStats';
import { useVerifyCompany } from '@/hooks/useAccounts';
import type { AdminQueueItem, AdminQueueSeverity, AdminPulseDay } from '@/api/adminApi';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { cn } from '@/lib/utils';
import { activityTitle, activityDetail } from '@/lib/activityText';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQueryClient } from '@tanstack/react-query';

type PulsePeriod = '7d' | '30d' | '90d';

interface PlatformAdminDashboardProps {
  onNavigate: (target: string) => void;
}

const SEVERITY_TONE: Record<AdminQueueSeverity, string> = {
  critical: 'border-destructive/40 bg-destructive/5',
  warning: 'border-warning/40 bg-warning/5',
  info: 'border-info/40 bg-info/5',
};

const SEVERITY_BADGE: Record<AdminQueueSeverity, 'destructive' | 'secondary' | 'outline'> = {
  critical: 'destructive',
  warning: 'secondary',
  info: 'outline',
};

const QUEUE_ICON: Record<AdminQueueItem['queue_type'], React.ComponentType<{ className?: string }>> = {
  kyc_pending: ShieldCheck,
  role_application: ClipboardList,
  subscription_past_due: CreditCard,
  subscription_expiring: Clock,
  invoice_overdue: Receipt,
  support_urgent: LifeBuoy,
};

function formatInt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

type PulseTone = 'primary' | 'success' | 'info' | 'warning';

const PULSE_TONE_CSS: Record<PulseTone, string> = {
  primary: 'var(--primary)',
  success: 'var(--success)',
  info: 'var(--info)',
  warning: 'var(--warning)',
};

function PulseChart({
  series,
  valueKey = 'count',
  tone,
  valueFormatter,
  ariaLabel,
}: {
  series: AdminPulseDay[];
  valueKey?: 'count' | 'value';
  tone: PulseTone;
  valueFormatter?: (v: number) => string;
  ariaLabel?: string;
}) {
  const data = useMemo(
    () =>
      series.map((d) => ({
        date: d.date,
        value: valueKey === 'value' ? Number(d.value) : d.count,
      })),
    [series, valueKey],
  );

  const config: ChartConfig = useMemo(
    () => ({
      value: {
        label: ariaLabel ?? 'Value',
        color: PULSE_TONE_CSS[tone],
      },
    }),
    [tone, ariaLabel],
  );

  if (series.length === 0) {
    return <div className="h-[90px] w-full" aria-hidden="true" />;
  }

  return (
    <ChartContainer config={config} className="h-[90px] w-full">
      <AreaChart
        data={data}
        margin={{ left: 4, right: 4, top: 4, bottom: 0 }}
      >
        <defs>
          <linearGradient id={`pulse-grad-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={`var(--color-value)`} stopOpacity={0.35} />
            <stop offset="95%" stopColor={`var(--color-value)`} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
        <XAxis
          dataKey="date"
          hide
        />
        <YAxis hide domain={[0, 'dataMax + 1']} />
        <ChartTooltip
          cursor={{ stroke: 'var(--border)', strokeDasharray: '3 3' }}
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                new Date(value as string).toLocaleDateString([], {
                  day: '2-digit',
                  month: 'short',
                })
              }
              formatter={(v) => (valueFormatter ? valueFormatter(Number(v)) : String(v))}
              hideIndicator={false}
            />
          }
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-value)"
          strokeWidth={2}
          fill={`url(#pulse-grad-${tone})`}
        />
      </AreaChart>
    </ChartContainer>
  );
}

interface QueueRowProps {
  item: AdminQueueItem;
  onOpen: (item: AdminQueueItem) => void;
  onApprove?: (item: AdminQueueItem) => void;
  onReject?: (item: AdminQueueItem) => void;
}

function QueueRow({ item, onOpen, onApprove, onReject }: QueueRowProps) {
  const { t } = useTranslation();
  const Icon = QUEUE_ICON[item.queue_type] ?? AlertTriangle;
  return (
    <div
      className={cn(
        'flex items-start gap-3 border-l-2 px-3 py-2.5 transition-colors hover:bg-accent/50',
        SEVERITY_TONE[item.severity],
      )}
    >
      <div className="mt-0.5">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs">
          <Badge variant={SEVERITY_BADGE[item.severity]} className="text-xs">
            {t(`adminQueue.severity.${item.severity}`)}
          </Badge>
          <span className="truncate font-medium">{item.title}</span>
          <span className="ml-auto text-muted-foreground">{item.age}</span>
        </div>
        {item.subtitle ? (
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.subtitle}</div>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {onApprove && item.actions.some((a) => a.startsWith('approve')) ? (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onApprove(item);
            }}
          >
            {t('common.approve')}
          </Button>
        ) : null}
        {onReject && item.actions.some((a) => a.startsWith('reject') || a.startsWith('revoke')) ? (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onReject(item);
            }}
          >
            {t('common.reject')}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(item);
          }}
        >
          {t('common.open')}
        </Button>
      </div>
    </div>
  );
}

export default function PlatformAdminDashboard({ onNavigate }: PlatformAdminDashboardProps): React.ReactNode {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState<PulsePeriod>('30d');
  const [queueFilter, setQueueFilter] = useState<string>('');
  const [confirm, setConfirm] = useState<
    | { kind: 'approve-kyc'; item: AdminQueueItem }
    | { kind: 'revoke-kyc'; item: AdminQueueItem }
    | { kind: 'activate-sub'; item: AdminQueueItem }
    | null
  >(null);

  const queue = useAdminQueue(queueFilter || undefined);
  const pulse = useAdminPulse(period);
  const dashboard = usePlatformDashboard();
  const verifyCompany = useVerifyCompany();
  const bulkSubStatus = useBulkSubscriptionStatus();
  const format = useCurrencyStore((s) => s.format);

  const queueItems = queue.data?.items ?? [];
  const queueTotals = queue.data?.totals ?? {};
  const activity = dashboard.data?.recent_activity ?? [];

  const pulseCompaniesTotal = useMemo(
    () => (pulse.data?.companies ?? []).reduce((s, d) => s + d.count, 0),
    [pulse.data],
  );
  const pulseDealsTotal = useMemo(
    () => (pulse.data?.deals ?? []).reduce((s, d) => s + d.count, 0),
    [pulse.data],
  );
  const pulseSignedValue = useMemo(
    () => (pulse.data?.quotes_signed_value ?? []).reduce((s, d) => s + Number(d.value || 0), 0),
    [pulse.data],
  );

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
    queryClient.invalidateQueries({ queryKey: ['admin-pulse'] });
    queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
  }

  function handleOpen(item: AdminQueueItem) {
    const map: Record<string, string> = {
      kyc_pending: 'admin-kyc',
      role_application: 'admin-role-apps',
      subscription_past_due: 'admin-subscriptions',
      subscription_expiring: 'admin-subscriptions',
      invoice_overdue: 'admin-deals',
      support_urgent: 'admin-support',
      // NOTE: there is no 'supplier_bid_pending' entry — the SupplierBid model
      // was removed (crm migration 0015) and no triage collector emits that
      // queue_type any more. Anything unmapped falls through to 'admin-companies'.
    };
    onNavigate(map[item.queue_type] ?? 'admin-companies');
  }

  function handleApprove(item: AdminQueueItem) {
    if (item.queue_type === 'kyc_pending') {
      setConfirm({ kind: 'approve-kyc', item });
    } else if (item.queue_type === 'role_application') {
      onNavigate('admin-role-apps');
    } else if (item.queue_type === 'subscription_expiring' || item.queue_type === 'subscription_past_due') {
      setConfirm({ kind: 'activate-sub', item });
    }
  }

  function handleReject(item: AdminQueueItem) {
    if (item.queue_type === 'kyc_pending') {
      setConfirm({ kind: 'revoke-kyc', item });
    } else {
      handleOpen(item);
    }
  }

  async function runConfirm(payload: { reason: string }) {
    if (!confirm) return;
    if (confirm.kind === 'approve-kyc') {
      await verifyCompany.mutateAsync({
        companyId: confirm.item.entity_id,
        status_code: 'L2_VERIFIED',
      });
      toast.success(t('adminQueue.kycApproved'));
      refreshAll();
      return;
    }
    if (confirm.kind === 'revoke-kyc') {
      await verifyCompany.mutateAsync({
        companyId: confirm.item.entity_id,
        status_code: 'L1_UNVERIFIED',
        reason: payload.reason,
      });
      toast.success(t('adminQueue.kycRevoked'));
      refreshAll();
      return;
    }
    if (confirm.kind === 'activate-sub') {
      await bulkSubStatus.mutateAsync({
        ids: [confirm.item.entity_id],
        status: 'ACTIVE',
      });
      toast.success(t('adminQueue.subscriptionActivated'));
      refreshAll();
      return;
    }
  }

  const queueLoading = queue.isLoading && !queue.data;
  const attention = dashboard.data?.attention;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{t('platformAdmin.dashboard.title')}</h1>
          <p className="text-xs text-muted-foreground">{t('platformAdmin.dashboard.subtitle')}</p>
        </div>
        <Tabs value={period} onValueChange={(v) => setPeriod(v as PulsePeriod)}>
          <TabsList className="h-8">
            <TabsTrigger value="7d" className="text-xs">{t('common.period7d')}</TabsTrigger>
            <TabsTrigger value="30d" className="text-xs">{t('common.period30d')}</TabsTrigger>
            <TabsTrigger value="90d" className="text-xs">{t('common.period90d')}</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-3.5 w-3.5 text-primary" />
              <span className="text-xs font-medium">{t('platformAdmin.pulse.newCompanies')}</span>
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {pulse.isLoading ? <Skeleton className="h-7 w-16" /> : formatInt(pulseCompaniesTotal)}
            </div>
            <div className="mt-2">
              <PulseChart
                series={pulse.data?.companies ?? []}
                tone="primary"
                ariaLabel={t('platformAdmin.pulse.newCompanies')}
              />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <Handshake className="h-3.5 w-3.5 text-success" />
              <span className="text-xs font-medium">{t('platformAdmin.pulse.newDeals')}</span>
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {pulse.isLoading ? <Skeleton className="h-7 w-16" /> : formatInt(pulseDealsTotal)}
            </div>
            <div className="mt-2">
              <PulseChart
                series={pulse.data?.deals ?? []}
                tone="success"
                ariaLabel={t('platformAdmin.pulse.newDeals')}
              />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-3.5 w-3.5 text-info" />
              <span className="text-xs font-medium">{t('platformAdmin.pulse.signedValue')}</span>
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {pulse.isLoading ? <Skeleton className="h-7 w-16" /> : format(pulseSignedValue)}
            </div>
            <div className="mt-2">
              <PulseChart
                series={pulse.data?.quotes_signed_value ?? []}
                tone="info"
                valueKey="value"
                valueFormatter={format}
                ariaLabel={t('platformAdmin.pulse.signedValue')}
              />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <CreditCard className="h-3.5 w-3.5 text-warning" />
              <span className="text-xs font-medium">{t('platformAdmin.pulse.mrr')}</span>
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {pulse.isLoading ? (
                <Skeleton className="h-7 w-16" />
              ) : (
                format(Number(pulse.data?.mrr ?? 0))
              )}
            </div>
            <div className="mt-2 text-xs text-muted-foreground">
              {t('platformAdmin.pulse.activeSubscriptions', {
                count: pulse.data?.active_subscriptions ?? 0,
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3 pb-2">
          <CardTitle className="text-sm">
            {t('platformAdmin.queue.title')}
            <span className="ml-2 text-xs text-muted-foreground">({queueItems.length})</span>
          </CardTitle>
          <Select
            value={queueFilter || 'all'}
            onValueChange={(v) => setQueueFilter(v === 'all' ? '' : v)}
          >
            <SelectTrigger className="ml-auto h-7 w-48 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">{t('platformAdmin.queue.filters.all')}</SelectItem>
              {Object.keys(queueTotals).map((qt) => (
                <SelectItem key={qt} value={qt} className="text-xs">
                  {t(`platformAdmin.queue.filters.${qt}`, { defaultValue: qt })}
                  <span className="ml-1 text-muted-foreground">· {queueTotals[qt]}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent className="p-0">
          {queue.isError ? (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden="true" />
              <div className="text-xs font-medium text-foreground">{t('common.loadError')}</div>
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => queue.refetch()}>
                {t('common.retry')}
              </Button>
            </div>
          ) : queueLoading ? (
            <div className="flex justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : queueItems.length === 0 ? (
            <div className="flex flex-col items-center gap-1 py-10 text-center text-xs text-muted-foreground">
              <ShieldCheck className="h-5 w-5 text-success" />
              <div className="font-medium">{t('platformAdmin.queue.emptyTitle')}</div>
              <div>{t('platformAdmin.queue.emptyHint')}</div>
            </div>
          ) : (
            <div className="divide-y">
              {queueItems.map((item) => (
                <QueueRow
                  key={`${item.queue_type}:${item.entity_id}`}
                  item={item}
                  onOpen={handleOpen}
                  onApprove={handleApprove}
                  onReject={handleReject}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('platformAdmin.activity.title')}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {dashboard.isError ? (
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden="true" />
                <div className="text-xs font-medium text-foreground">{t('common.loadError')}</div>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => dashboard.refetch()}>
                  {t('common.retry')}
                </Button>
              </div>
            ) : dashboard.isLoading && activity.length === 0 ? (
              <div className="flex justify-center p-6">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : activity.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground">
                {t('platformAdmin.activity.empty')}
              </div>
            ) : (
              <ul className="divide-y text-xs">
                {activity.slice(0, 15).map((entry) => (
                  <li key={entry.id} className="flex items-start justify-between gap-3 px-4 py-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={
                            entry.level === 'ERROR'
                              ? 'destructive'
                              : entry.level === 'WARNING'
                                ? 'secondary'
                                : 'outline'
                          }
                          className="text-xs"
                        >
                          {entry.level}
                        </Badge>
                        <span className="font-medium">{activityTitle(t, i18n, entry)}</span>
                      </div>
                      {activityDetail(t, i18n, entry) ? (
                        <div className="mt-0.5 truncate text-muted-foreground">{activityDetail(t, i18n, entry)}</div>
                      ) : null}
                      {entry.user_email ? (
                        <div className="mt-0.5 text-muted-foreground">{entry.user_email}</div>
                      ) : null}
                    </div>
                    <time className="shrink-0 text-muted-foreground" dateTime={entry.timestamp}>
                      {new Date(entry.timestamp).toLocaleDateString([], {
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </time>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('platformAdmin.summary.title')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <SummaryRow
              icon={Users}
              label={t('shell.users')}
              value={dashboard.data?.users.total}
              onClick={() => onNavigate('admin-users')}
            />
            <SummaryRow
              icon={Building2}
              label={t('shell.companies')}
              value={dashboard.data?.companies.total}
              onClick={() => onNavigate('admin-companies')}
            />
            <SummaryRow
              icon={Handshake}
              label={t('shell.adminDeals')}
              value={dashboard.data?.deals.total}
              onClick={() => onNavigate('admin-deals')}
            />
            <SummaryRow
              icon={ShieldCheck}
              label={t('shell.kyc')}
              value={attention?.kyc ?? 0}
              highlight={Boolean(attention?.kyc)}
              onClick={() => onNavigate('admin-kyc')}
            />
            <SummaryRow
              icon={ClipboardList}
              label={t('shell.roleApplications')}
              value={attention?.role_applications ?? 0}
              highlight={Boolean(attention?.role_applications)}
              onClick={() => onNavigate('admin-role-apps')}
            />
            <SummaryRow
              icon={CreditCard}
              label={t('platformAdmin.summary.subsExpiring')}
              value={(attention?.subscriptions_expiring_7d ?? 0) + (attention?.subscriptions_past_due ?? 0)}
              highlight={Boolean(attention?.subscriptions_past_due)}
              onClick={() => onNavigate('admin-subscriptions')}
            />
            <SummaryRow
              icon={Receipt}
              label={t('platformAdmin.summary.overdueInvoices')}
              value={attention?.overdue_invoices ?? 0}
              highlight={Boolean(attention?.overdue_invoices)}
              onClick={() => onNavigate('admin-deals')}
            />
          </CardContent>
        </Card>
      </div>

      <ConfirmActionDialog
        open={confirm?.kind === 'approve-kyc'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('adminQueue.confirm.kycApproveTitle')}
        description={t('adminQueue.confirm.kycApproveDescription', {
          name: confirm?.item.title ?? '',
        })}
        variant="primary"
        confirmLabel={t('common.approve')}
        showReason
        reasonLabel={t('adminQueue.confirm.commentOptional')}
        diff={confirm?.kind === 'approve-kyc' ? [
          {
            label: t('confirmDialog.kycLevel'),
            before: 'PROFILE_SUBMITTED',
            after: 'L2_VERIFIED',
          },
        ] : undefined}
        onConfirm={runConfirm}
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'revoke-kyc'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('adminQueue.confirm.kycRevokeTitle')}
        description={t('adminQueue.confirm.kycRevokeDescription', {
          name: confirm?.item.title ?? '',
        })}
        variant="destructive"
        confirmLabel={t('common.revoke')}
        requireReason
        reasonTemplates={[
          t('adminQueue.reasonTemplates.docsInvalid'),
          t('adminQueue.reasonTemplates.innMismatch'),
          t('adminQueue.reasonTemplates.other'),
        ]}
        onConfirm={runConfirm}
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'activate-sub'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('adminQueue.confirm.subActivateTitle')}
        description={confirm?.item.title ?? ''}
        variant="primary"
        confirmLabel={t('common.activate')}
        onConfirm={runConfirm}
      />
    </div>
  );
}

function SummaryRow({
  icon: Icon,
  label,
  value,
  highlight,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value?: number;
  highlight?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent',
        highlight && 'bg-warning/10',
      )}
    >
      <span className="flex items-center gap-2 text-xs">
        <Icon className={cn('h-3.5 w-3.5 text-muted-foreground', highlight && 'text-warning')} />
        {label}
      </span>
      <span className={cn('text-xs font-semibold tabular-nums', highlight && 'text-warning')}>
        {value == null ? '—' : value.toLocaleString()}
      </span>
    </button>
  );
}
