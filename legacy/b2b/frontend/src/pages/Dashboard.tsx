import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Package,
  FileText,
  Users,
  DollarSign,
  Calendar,
  MoreHorizontal,
  BarChart3,
  ShoppingCart,
  AlertCircle,
  Loader2,
  Clock,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';

import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Progress } from '@/components/ui/progress';
import { KPICard } from '@/components/ui/KPICard';
import { OnboardingChecklist } from '@/components/Shared/OnboardingChecklist';

import { useTranslation } from 'react-i18next';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { dashboardApi, type DashboardStats } from '@/api/dashboardApi';

// ─── Top Products Table ─────────────────────────────────────────────────

function TopProductsTable({ onProductClick, onShowAll, topProducts }: { onProductClick?: (id: string) => void; onShowAll?: () => void; topProducts: DashboardStats['top_products'] }) {
  const { t } = useTranslation();
  return (
    <Card className="py-0 gap-0">
      <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
        <CardTitle className="text-sm font-semibold">{t('dashboardPage.topProducts')}</CardTitle>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={t('dashboardPage.actions')}>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => {
              const rows: (string | number)[][] = [
                ['id', 'name', 'category', 'quantity'],
                ...topProducts.map((p) => [p.id, p.name, p.category, p.quantity]),
              ];
              const csv = rows.map((r) => r.join(',')).join('\n');
              const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
              const url = URL.createObjectURL(blob);
              const link = document.createElement('a');
              link.href = url; link.download = 'top_products.csv';
              document.body.appendChild(link); link.click(); link.remove();
              URL.revokeObjectURL(url);
            }}>{t('dashboardPage.export')}</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onShowAll?.()}>
              {t('dashboardPage.showAll')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs">{t('common.id')}</TableHead>
            <TableHead className="text-xs">{t('dashboardPage.productName')}</TableHead>
            <TableHead className="text-right text-xs">{t('dashboardPage.quantity')}</TableHead>
            <TableHead className="text-xs">{t('dashboardPage.category')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {topProducts.length === 0 && (
            <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground py-8">{t('common.noData')}</TableCell></TableRow>
          )}
          {topProducts.map((p) => (
            <TableRow
              key={p.id}
              className="cursor-pointer"
              tabIndex={0}
              role="link"
              onClick={() => onProductClick?.(p.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onProductClick?.(p.id); } }}
            >
              <TableCell className="font-mono text-xs text-muted-foreground">{p.id}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
                    <Package className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <span className="text-sm font-medium truncate max-w-xs">{p.name}</span>
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm font-medium">
                {p.quantity}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{p.category}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

// ─── KYC Pending Banner ────────────────────────────────────────────────

function KYCPendingBanner({ onNavigate }: { onNavigate?: (p: string) => void } = {}) {
  const { t } = useTranslation();
  const { profile, company } = useUserStore();

  const levels = [
    {
      code: 'L1',
      label: t('dashboardPage.kyc.levels.l1.label'),
      desc: t('dashboardPage.kyc.levels.l1.desc'),
      features: t('dashboardPage.kyc.levels.l1.features'),
      status: 'done' as const,
    },
    {
      code: 'L2',
      label: t('dashboardPage.kyc.levels.l2.label'),
      desc: t('dashboardPage.kyc.levels.l2.desc'),
      features: t('dashboardPage.kyc.levels.l2.features'),
      status: (company.kycStatus === 'verified' ? 'done' : 'current') as 'done' | 'current' | 'locked',
    },
    {
      code: 'L3',
      label: t('dashboardPage.kyc.levels.l3.label'),
      desc: t('dashboardPage.kyc.levels.l3.desc'),
      features: t('dashboardPage.kyc.levels.l3.features'),
      status: 'locked' as const,
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-warning/10">
              <Clock className="h-6 w-6 text-warning" />
            </div>
            <div>
              <h2 className="text-lg font-bold">{t('dashboardPage.kyc.title', { name: profile.firstName || '' })}</h2>
              <p className="text-sm text-muted-foreground mt-1">{t('dashboardPage.kyc.subtitle')}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Company info */}
      <Card>
        <CardContent className="p-5">
          <h3 className="text-sm font-semibold mb-4">{t('dashboardPage.kyc.statusTitle')}</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('dashboardPage.kyc.company')}</span>
              <span className="text-sm font-medium">{company.name || t('dashboardPage.kyc.notSpecified')}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('dashboardPage.kyc.inn')}</span>
              <span className="text-sm font-mono">{company.inn || t('dashboardPage.kyc.notSpecified')}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('dashboardPage.kyc.status')}</span>
              <Badge variant="secondary" className="gap-1">
                <Clock className="h-3 w-3" />
                {t('dashboardPage.kyc.pending')}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* KYC Levels Roadmap */}
      <Card>
        <CardContent className="p-5">
          <h3 className="text-sm font-semibold mb-4">{t('dashboardPage.kyc.levelsTitle')}</h3>
          <div className="space-y-4">
            {levels.map((level, i) => (
              <div key={level.code} className={cn(
                'relative rounded-lg border p-4',
                level.status === 'current' && 'border-warning bg-warning/5',
                level.status === 'done' && 'border-success/30 bg-success/5',
                level.status === 'locked' && 'opacity-50',
              )}>
                <div className="flex items-start gap-3">
                  {/* Step indicator */}
                  <div className={cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                    level.status === 'done' && 'bg-success text-success-foreground',
                    level.status === 'current' && 'bg-warning text-warning-foreground',
                    level.status === 'locked' && 'bg-muted text-muted-foreground',
                  )}>
                    {level.status === 'done' ? '✓' : i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-semibold">{level.label}</h4>
                      {level.status === 'current' && (
                        <Badge variant="secondary" className="text-xs gap-1">
                          <Clock className="h-3 w-3" />
                          {t('dashboardPage.kyc.yourLevel')}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{level.desc}</p>
                    <p className="text-xs mt-2">
                      <span className="font-medium">{t('dashboardPage.kyc.access')}: </span>
                      <span className="text-muted-foreground">{level.features}</span>
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Actions */}
      <Card className="border-dashed">
        <CardContent className="p-5 text-center space-y-3">
          <p className="text-sm text-muted-foreground">{t('dashboardPage.kyc.hint')}</p>
          <div className="flex justify-center gap-3">
            <Button variant="outline" size="sm" onClick={() => onNavigate?.('profile')}>
              {t('dashboardPage.kyc.editProfile')}
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={`mailto:support@railtech.uz?subject=${encodeURIComponent(t('dashboardPage.kyc.supportSubject'))}`}>
                {t('dashboardPage.kyc.contactSupport')}
              </a>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── BUYER Welcome (KYC verified, no activity) ────────────────────────

function BuyerWelcome({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { t } = useTranslation();
  const { profile } = useUserStore();

  const steps = [
    { icon: Package, label: t('dashboardPage.welcome.step1'), desc: t('dashboardPage.welcome.step1Desc'), action: () => onNavigate('products'), actionLabel: t('dashboardPage.welcome.browseCatalog') },
    { icon: ShoppingCart, label: t('dashboardPage.welcome.step2'), desc: t('dashboardPage.welcome.step2Desc'), action: () => onNavigate('products'), actionLabel: t('dashboardPage.welcome.addToCart') },
    { icon: FileText, label: t('dashboardPage.welcome.step3'), desc: t('dashboardPage.welcome.step3Desc'), action: () => onNavigate('my-requests'), actionLabel: t('dashboardPage.welcome.viewRequests') },
  ];

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="p-6">
          <h2 className="text-lg font-bold">{t('dashboardPage.welcome.title', { name: profile.firstName || '' })}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t('dashboardPage.welcome.subtitle')}</p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {steps.map((step, i) => (
          <Card key={i} className="hover:shadow-md transition-shadow">
            <CardContent className="p-5 flex flex-col gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <step.icon className="h-5 w-5" />
                </div>
                <span className="text-xs font-bold text-muted-foreground">{t('dashboardPage.welcome.stepN', { n: i + 1 })}</span>
              </div>
              <h3 className="text-sm font-semibold">{step.label}</h3>
              <p className="text-xs text-muted-foreground flex-1">{step.desc}</p>
              <Button variant="outline" size="sm" className="w-full gap-2" onClick={step.action}>
                {step.actionLabel}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ─── BUYER Dashboard ────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function BuyerDashboard({ onProductClick: _onProductClick, period: _period, stats, onNavigate }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null; onNavigate: (page: string) => void }) {
  const { t } = useTranslation();
  const { company } = useUserStore();

  const buyerRequestsStatus = useMemo(() => stats ? [
    { name: t('dashboardPage.buyer.statusActive'), value: stats.active_requests ?? 0 },
    { name: t('dashboardPage.buyer.statusInProgress'), value: stats.deals_in_progress ?? 0 },
    { name: t('dashboardPage.buyer.statusQuoteReceived'), value: stats.quotes_received ?? 0 },
    { name: t('dashboardPage.buyer.statusCompleted'), value: stats.deals_completed ?? 0 },
  ] : [], [stats, t]);

  // State 1: KYC not verified — show verification status
  if (company.kycStatus !== 'verified') return <KYCPendingBanner onNavigate={onNavigate} />;

  // State 2: KYC verified but no activity — show welcome guide
  const isEmpty = !stats || ((stats.active_requests ?? 0) === 0 && (stats.deals_completed ?? 0) === 0 && (stats.quotes_received ?? 0) === 0);
  if (isEmpty) return <BuyerWelcome onNavigate={onNavigate} />;

  // Trend badge only when there is a previous-period baseline worth comparing.
  // A 1400% delta on a 4→60 jump is technically correct but is visual noise
  // for a buyer's personal dashboard — suppress until at least one side had
  // meaningful volume.
  const trendFor = (current: number, change: number, suffix: string) => {
    if (!current || change === 0) return undefined;
    return {
      value: `${change > 0 ? '+' : ''}${change}% ${suffix}`,
      direction: (change > 0 ? 'up' : 'down') as 'up' | 'down',
    };
  };
  const vsPrev = t('dashboardPage.vsPrevPeriod');

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row — buyer-scoped: own activity, not platform totals. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('dashboardPage.kpi.activeRequests')}
          value={String(stats?.active_requests ?? 0)}
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={trendFor(stats?.active_requests ?? 0, stats?.active_requests_change ?? 0, vsPrev)}
        />
        <KPICard
          label={t('dashboardPage.kpi.inProgress')}
          value={String(stats?.deals_in_progress ?? 0)}
          icon={<Clock className="h-5 w-5 text-muted-foreground" />}
        />
        <KPICard
          label={t('dashboardPage.kpi.quotesReceived')}
          value={String(stats?.quotes_received ?? 0)}
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
        />
        <KPICard
          label={t('dashboardPage.kpi.completed')}
          value={String(stats?.deals_completed ?? 0)}
          icon={<Package className="h-5 w-5 text-muted-foreground" />}
        />
      </div>

      {/* Charts — one bar chart of buyer's requests by status. The previous
          revision shipped both a bar and a pie with identical data; dropped
          the pie to avoid visual duplication. */}
      <Card className="py-0 gap-0">
        <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
          <CardTitle className="text-sm font-semibold">{t('dashboardPage.buyer.requestsByStatus')}</CardTitle>
        </CardHeader>
        <CardContent className="px-2 pb-4">
          <div role="img" aria-label={t('dashboardPage.buyer.requestsByStatusChart')}>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={buyerRequestsStatus}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} allowDecimals={false} />
                <RechartsTooltip
                  formatter={(value: number) => [value, t('dashboardPage.requests')]}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── SELLER Dashboard ───────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function SellerDashboard({ onProductClick, period: _period, stats, onNavigate }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null; onNavigate: (page: string) => void }) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { company } = useUserStore();

  const counterpartyBreakdown = useMemo(() => stats ? [
    { name: t('dashboardPage.seller.manufacturers'), value: stats.counterparties.manufacturers, color: 'var(--color-chart-1)', dotClass: 'bg-[var(--color-chart-1)]' },
    { name: t('dashboardPage.seller.buyers'), value: stats.counterparties.buyers, color: 'var(--color-chart-2)', dotClass: 'bg-[var(--color-chart-2)]' },
    { name: t('dashboardPage.seller.intermediaries'), value: stats.counterparties.intermediaries, color: 'var(--color-chart-4)', dotClass: 'bg-[var(--color-chart-4)]' },
  ] : [], [stats, t]);

  if (company.kycStatus !== 'verified') return <KYCPendingBanner onNavigate={onNavigate} />;

  const dealVolumeData = stats?.deals_by_month ?? [];
  const activityByDay = stats?.activity_by_day ?? [];
  const completionPct = stats?.request_completion ?? 0;
  const completionGoal = stats?.request_completion_goal ?? 80;

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('dashboardPage.kpi.dealsVolume')}
          value={formatCurrency(stats?.deals_volume ?? 0)}
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.deals_volume_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.deals_volume_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label={t('dashboardPage.kpi.activeRequests')}
          value={String(stats?.active_requests ?? 0)}
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.active_requests_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.active_requests_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label={t('dashboardPage.kpi.catalogItems')}
          value={String(stats?.catalog_items ?? 0)}
          icon={<Package className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.catalog_items_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.catalog_items_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label={t('dashboardPage.kpi.clients')}
          value={String(stats?.clients_count ?? 0)}
          icon={<Users className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.clients_count_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.clients_count_change ?? 0) >= 0 ? "up" : "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Area Chart — Deal Volume */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <div>
              <CardTitle className="text-sm font-semibold">{t('dashboardPage.seller.dealsVolume')}</CardTitle>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold tabular-nums">{formatCurrency(stats?.deals_volume ?? 0)}</span>
                <span className="text-xs font-medium text-muted-foreground">{stats?.deals_volume_change ?? 0}% {t('dashboardPage.vsPrevPeriod')}</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div role="img" aria-label={t('dashboardPage.seller.dealsVolumeChart')}>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={dealVolumeData}>
                <defs>
                  <linearGradient id="colorVal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-chart-1)" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="var(--color-chart-1)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatCurrency(v)} />
                <RechartsTooltip
                  formatter={(value: number) => [formatCurrency(value), t('dashboardPage.seller.volume')]}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Area type="monotone" dataKey="value" stroke="var(--color-chart-1)" strokeWidth={2} fill="url(#colorVal)" />
              </AreaChart>
            </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Bar Chart — Activity by Day */}
        <Card className="py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">{t('dashboardPage.seller.activityByDay')}</CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div className="mb-2 text-center">
              <span className="text-2xl font-bold tabular-nums">{activityByDay.reduce((s, d) => s + d.count, 0)}</span>
              <p className="text-xs text-muted-foreground">{t('dashboardPage.seller.requestsPerWeek')}</p>
            </div>
            <div role="img" aria-label={t('dashboardPage.seller.activityByDayChart')}>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={activityByDay}>
                <XAxis dataKey="day" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <RechartsTooltip
                  formatter={(value: number) => [value, t('dashboardPage.requests')]}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="count" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Top Products */}
        <div className="lg:col-span-2">
          <TopProductsTable onProductClick={onProductClick} onShowAll={() => onNavigate?.("products")} topProducts={stats?.top_products ?? []} />
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-4">
          {/* Counterparty breakdown */}
          <Card className="py-0 gap-0">
            <CardHeader className="px-4 py-3">
              <CardTitle className="text-sm font-semibold">{t('dashboardPage.seller.counterparties')}</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <div className="flex items-center justify-center" role="img" aria-label={t('dashboardPage.seller.counterpartiesChart')}>
                <ResponsiveContainer width={160} height={160}>
                  <PieChart>
                    <Pie
                      data={counterpartyBreakdown}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={70}
                      dataKey="value"
                      strokeWidth={2}
                    >
                      {counterpartyBreakdown.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 flex justify-center gap-4">
                {counterpartyBreakdown.map((c) => (
                  <div key={c.name} className="flex items-center gap-1.5 text-xs">
                    <span className={`h-2.5 w-2.5 rounded-full ${c.dotClass}`} />
                    <span className="font-medium">{c.value}</span>
                    <span className="text-muted-foreground">{c.name}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Fulfillment Rate */}
          <Card className="py-0 gap-0">
            <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
              <CardTitle className="text-sm font-semibold">{t('dashboardPage.seller.requestCompletion')}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-3 px-4 pb-4">
              <span className="text-4xl font-bold text-primary tabular-nums">{completionPct}%</span>
              <p className="text-xs text-muted-foreground">{t('dashboardPage.goal')}: {completionGoal}%</p>
              <Progress value={completionPct} className="h-2 w-full" />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ─── MANUFACTURER Dashboard ──────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ManufacturerDashboard({ onProductClick: _onProductClick, period: _period, stats, onNavigate }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null; onNavigate: (page: string) => void }) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { company } = useUserStore();

  if (company.kycStatus !== 'verified') return <KYCPendingBanner onNavigate={onNavigate} />;

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('dashboardPage.kpi.activeRequests')}
          value={String(stats?.active_requests ?? 0)}
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.active_requests_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.active_requests_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label={t('dashboardPage.kpi.catalogItems')}
          value={String(stats?.catalog_items ?? 0)}
          icon={<AlertCircle className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.catalog_items_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.catalog_items_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label={t('dashboardPage.kpi.requestCompletion')}
          value={`${stats?.request_completion ?? 0}%`}
          icon={<BarChart3 className="h-5 w-5 text-muted-foreground" />}
        />
        <KPICard
          label={t('dashboardPage.kpi.dealsVolume')}
          value={formatCurrency(stats?.deals_volume ?? 0)}
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.deals_volume_change ?? 0}% ${t('dashboardPage.vsPrevPeriod')}`, direction: (stats?.deals_volume_change ?? 0) >= 0 ? "up" : "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Bar Chart — Deals by Month */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">{t('dashboardPage.manufacturer.dealsByMonth')}</CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div role="img" aria-label={t('dashboardPage.manufacturer.dealsByMonthChart')}>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stats?.deals_by_month ?? []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatCurrency(v)} />
                <RechartsTooltip
                  formatter={(value: number) => [formatCurrency(value), t('dashboardPage.seller.volume')]}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Completion */}
        <Card className="py-0 gap-0">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-semibold">{t('dashboardPage.seller.requestCompletion')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-3 px-4 pb-4">
            <span className="text-4xl font-bold text-primary tabular-nums">{stats?.request_completion ?? 0}%</span>
            <p className="text-xs text-muted-foreground">{t('dashboardPage.goal')}: {stats?.request_completion_goal ?? 80}%</p>
            <Progress value={stats?.request_completion ?? 0} className="h-2 w-full" />
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row — Top Products */}
      <TopProductsTable onProductClick={_onProductClick} onShowAll={() => onNavigate?.("products")} topProducts={stats?.top_products ?? []} />
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────

interface DashboardProps {
  onProductClick?: (productId: string) => void;
  onNavigate?: (page: string) => void;
}

export function Dashboard({ onProductClick, onNavigate }: DashboardProps) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState('30d');
  const activeStatus = useUserStore((s) => s.activeStatus);

  const { data, isLoading: loading, error: queryError, refetch } = useQuery({
    queryKey: ['dashboard-stats', period],
    queryFn: () => dashboardApi.getStats(period),
    staleTime: 60_000,
  });
  const stats: DashboardStats | null = data ?? null;
  const error = queryError ? (queryError instanceof Error ? queryError.message : t('errors.server')) : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" role="status">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <Alert variant="destructive" className="max-w-md">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => refetch()}>
          {t('common.retry')}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <OnboardingChecklist onNavigate={onNavigate} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{t('dashboardPage.title')}</h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-xs text-muted-foreground">
            <Calendar className="h-3.5 w-3.5" />
            <span>1 {t('dashboardPage.months.jan')} – 21 {t('dashboardPage.months.mar')} 2026</span>
          </div>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="h-8 w-36 text-xs" aria-label={t('dashboardPage.selectPeriod')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">7 {t('dashboardPage.buyer.days')}</SelectItem>
              <SelectItem value="30d">30 {t('dashboardPage.buyer.days')}</SelectItem>
              <SelectItem value="90d">{t('dashboardPage.quarter')}</SelectItem>
              <SelectItem value="1y">{t('dashboardPage.year')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Role-based dashboard content — fallback to BuyerDashboard */}
      {activeStatus === 'SELLER' ? (
        <SellerDashboard onProductClick={onProductClick} period={period} stats={stats} onNavigate={onNavigate ?? (() => {})} />
      ) : activeStatus === 'MANUFACTURER' ? (
        <ManufacturerDashboard onProductClick={onProductClick} period={period} stats={stats} onNavigate={onNavigate ?? (() => {})} />
      ) : (
        <BuyerDashboard onProductClick={onProductClick} period={period} stats={stats} onNavigate={onNavigate ?? (() => {})} />
      )}
    </div>
  );
}
