import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Users, Building2, Handshake, CreditCard, ShieldCheck, ClipboardList,
  AlertTriangle, Receipt, Clock, Activity,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import { Progress } from '@/components/ui/progress';
import { usePlatformDashboard } from '@/hooks/usePageStats';
import { useCurrencyStore } from '@/store/currencyStore';

interface PlatformAdminDashboardProps {
  onNavigate: (target: string) => void;
}

/** Severity colour map for ActivityLog levels via semantic tokens. */
const LEVEL_VARIANT: Record<'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR', 'secondary' | 'default' | 'outline' | 'destructive'> = {
  INFO: 'secondary',
  SUCCESS: 'default',
  WARNING: 'outline',
  ERROR: 'destructive',
};

function KpiCard({
  icon: Icon, label, value, sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase text-muted-foreground tracking-wide">{label}</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function AttentionItem({
  icon: Icon, label, count, onClick, severity = 'warning',
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  count: number;
  onClick: () => void;
  severity?: 'warning' | 'destructive' | 'info';
}) {
  const colorMap = {
    warning: 'text-warning bg-warning/10',
    destructive: 'text-destructive bg-destructive/10',
    info: 'text-info bg-info/10',
  };
  if (count === 0) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
    >
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${colorMap[severity]}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{label}</p>
      </div>
      <Badge variant="secondary" className="tabular-nums">{count}</Badge>
    </button>
  );
}

export function PlatformAdminDashboard({ onNavigate }: PlatformAdminDashboardProps) {
  const { t } = useTranslation();
  const { data, isLoading } = usePlatformDashboard();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const kpi = useMemo(() => {
    if (!data) return [];
    return [
      {
        icon: Users,
        label: t('platformDashboard.kpi.users'),
        value: String(data.users.total),
        sub: t('platformDashboard.kpi.usersSub', {
          active: data.users.active, new: data.users.new_7d,
        }),
      },
      {
        icon: Building2,
        label: t('platformDashboard.kpi.companies'),
        value: String(data.companies.total),
        sub: t('platformDashboard.kpi.companiesSub', {
          buyers: data.companies.by_type.BUYER,
          sellers: data.companies.by_type.SELLER,
          mfg: data.companies.by_type.MANUFACTURER,
        }),
      },
      {
        icon: Handshake,
        label: t('platformDashboard.kpi.deals'),
        value: String(data.deals.total),
        sub: t('platformDashboard.kpi.dealsSub', {
          active: data.deals.active, won: data.deals.won,
        }),
      },
      {
        icon: Receipt,
        label: t('platformDashboard.kpi.pipeline'),
        value: formatCurrency(Number(data.deals.pipeline_value)),
        sub: t('platformDashboard.kpi.wonValue', {
          value: formatCurrency(Number(data.deals.won_value)),
        }),
      },
    ];
  }, [data, t, formatCurrency]);

  if (isLoading || !data) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('platformDashboard.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('platformDashboard.subtitle')}</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
      </div>
    );
  }

  const totalAttention =
    data.attention.kyc
    + data.attention.role_applications
    + data.attention.subscriptions_past_due
    + data.attention.overdue_invoices;

  const maxStageCount = Math.max(1, ...data.deals.by_stage.map((s) => s.count));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('platformDashboard.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('platformDashboard.subtitle')}</p>
        </div>
        {totalAttention > 0 && (
          <Badge variant="destructive" className="text-xs gap-1.5">
            <AlertTriangle className="h-3 w-3" />
            {t('platformDashboard.attention.total', { count: totalAttention })}
          </Badge>
        )}
      </div>

      {/* KPI */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {kpi.map((k) => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* Attention + Deals by stage */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              {t('platformDashboard.attention.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {totalAttention === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                {t('platformDashboard.attention.empty')}
              </p>
            ) : (
              <>
                <AttentionItem
                  icon={ShieldCheck}
                  label={t('platformDashboard.attention.kyc')}
                  count={data.attention.kyc}
                  onClick={() => onNavigate('admin-kyc')}
                  severity="warning"
                />
                <AttentionItem
                  icon={ClipboardList}
                  label={t('platformDashboard.attention.roleApps')}
                  count={data.attention.role_applications}
                  onClick={() => onNavigate('admin-role-apps')}
                  severity="warning"
                />
                <AttentionItem
                  icon={CreditCard}
                  label={t('platformDashboard.attention.subsPastDue')}
                  count={data.attention.subscriptions_past_due}
                  onClick={() => onNavigate('admin-subscriptions')}
                  severity="destructive"
                />
                <AttentionItem
                  icon={Clock}
                  label={t('platformDashboard.attention.subsExpiring')}
                  count={data.attention.subscriptions_expiring_7d}
                  onClick={() => onNavigate('admin-subscriptions')}
                  severity="info"
                />
                <AttentionItem
                  icon={Receipt}
                  label={t('platformDashboard.attention.overdueInvoices')}
                  count={data.attention.overdue_invoices}
                  onClick={() => onNavigate('invoices')}
                  severity="destructive"
                />
              </>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">
              {t('platformDashboard.dealsByStage.title')}
            </CardTitle>
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-deals')}>
              {t('platformDashboard.dealsByStage.openAll')}
            </Button>
          </CardHeader>
          <CardContent>
            {data.deals.by_stage.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                {t('platformDashboard.dealsByStage.empty')}
              </p>
            ) : (
              <div className="space-y-2">
                {data.deals.by_stage.map((stage) => (
                  <div key={stage.stage__code} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{stage.stage__name}</span>
                      <span className="tabular-nums text-muted-foreground">{stage.count}</span>
                    </div>
                    <Progress value={(stage.count / maxStageCount) * 100} className="h-2" />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Subscriptions + Quick actions */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <CreditCard className="h-4 w-4" />
              {t('platformDashboard.subscriptions.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <SubRow label={t('platformDashboard.subscriptions.active')} value={data.subscriptions.active} variant="default" />
            <SubRow label={t('platformDashboard.subscriptions.trial')} value={data.subscriptions.trial} variant="secondary" />
            <SubRow label={t('platformDashboard.subscriptions.pastDue')} value={data.subscriptions.past_due} variant="destructive" />
            <SubRow label={t('platformDashboard.subscriptions.suspended')} value={data.subscriptions.suspended} variant="outline" />
            <Separator />
            <Button variant="outline" size="sm" className="w-full" onClick={() => onNavigate('admin-subscriptions')}>
              {t('platformDashboard.subscriptions.manage')}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              {t('platformDashboard.companies.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <SubRow label={t('platformDashboard.companies.verified')} value={data.companies.verified} variant="default" />
            <SubRow label={t('platformDashboard.companies.pendingKyc')} value={data.companies.pending_kyc} variant="outline" />
            <SubRow label={t('platformDashboard.companies.buyers')} value={data.companies.by_type.BUYER} variant="secondary" />
            <SubRow label={t('platformDashboard.companies.sellers')} value={data.companies.by_type.SELLER} variant="secondary" />
            <SubRow label={t('platformDashboard.companies.manufacturers')} value={data.companies.by_type.MANUFACTURER} variant="secondary" />
            <Separator />
            <Button variant="outline" size="sm" className="w-full" onClick={() => onNavigate('admin-companies')}>
              {t('platformDashboard.companies.manage')}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="h-4 w-4" />
              {t('platformDashboard.quickActions.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-users')}>
              <Users className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.users')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-companies')}>
              <Building2 className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.companies')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-kyc')}>
              <ShieldCheck className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.kyc')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-master-data')}>
              <Receipt className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.masterData')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => onNavigate('admin-catalog')}>
              <Handshake className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.catalog')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => onNavigate('settings')}>
              <ClipboardList className="mr-2 h-3.5 w-3.5" />
              {t('platformDashboard.quickActions.settings')}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Recent Activity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" />
            {t('platformDashboard.recentActivity.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {data.recent_activity.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {t('platformDashboard.recentActivity.empty')}
            </p>
          ) : (
            <div className="divide-y">
              {data.recent_activity.map((log) => (
                <div key={log.id} className="flex items-start gap-3 p-3">
                  <Badge variant={LEVEL_VARIANT[log.level] ?? 'secondary'} className="shrink-0 text-xs">
                    {log.level}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{log.action}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2">{log.detail}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {log.user_email ?? t('platformDashboard.recentActivity.system')}
                      {' · '}
                      {new Date(log.timestamp).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SubRow({
  label, value, variant,
}: {
  label: string;
  value: number;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <Badge variant={variant} className="tabular-nums">{value}</Badge>
    </div>
  );
}

export default PlatformAdminDashboard;
