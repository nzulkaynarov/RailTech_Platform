import { useState, useEffect } from 'react';
import {
  Package,
  FileText,
  Users,
  DollarSign,
  Calendar,
  Download,
  MoreHorizontal,
  BarChart3,
  ShoppingCart,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

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

import { useTranslation } from 'react-i18next';
import { useUserStore } from '@/store/userStore';
import { dashboardApi, type DashboardStats } from '@/api/dashboardApi';

// ─── Chart color constants ──────────────────────────────────────────────

const buyerRequestsStatusColors = ['var(--color-chart-1)', 'var(--color-chart-2)', 'var(--color-chart-3)', 'var(--color-chart-4)', 'var(--color-chart-5)'];

// ─── Top Products Table ─────────────────────────────────────────────────

function TopProductsTable({ onProductClick, topProducts }: { onProductClick?: (id: string) => void; topProducts: DashboardStats['top_products'] }) {
  return (
    <Card className="py-0 gap-0">
      <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
        <CardTitle className="text-sm font-semibold">Топ товаров по запросам</CardTitle>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem>Экспорт</DropdownMenuItem>
            <DropdownMenuItem>Показать все</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs">ID</TableHead>
            <TableHead className="text-xs">Наименование</TableHead>
            <TableHead className="text-right text-xs">Кол-во</TableHead>
            <TableHead className="text-xs">Категория</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {topProducts.length === 0 && (
            <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground py-8">Нет данных</TableCell></TableRow>
          )}
          {topProducts.map((p) => (
            <TableRow
              key={p.id}
              className="cursor-pointer"
              onClick={() => onProductClick?.(p.id)}
            >
              <TableCell className="font-mono text-xs text-muted-foreground">{p.id}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
                    <Package className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <span className="text-sm font-medium truncate max-w-[180px]">{p.name}</span>
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

// ─── BUYER Dashboard ────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function BuyerDashboard({ onProductClick: _onProductClick, period: _period, stats }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null }) {
  // Buyer-specific request statuses from API (placeholder — extend API for buyer-specific data)
  const buyerRequestsStatus = stats ? [
    { name: 'Активные', value: stats.active_requests },
    { name: 'В работе', value: Math.round(stats.active_requests * 0.4) },
    { name: 'КП получено', value: Math.round(stats.active_requests * 0.2) },
    { name: 'Завершено', value: stats.clients_count },
  ] : [];

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Активные заявки"
          value={String(stats?.active_requests ?? 0)}
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.active_requests_change ?? 0}% vs. пред. период`, direction: (stats?.active_requests_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Позиций в каталоге"
          value={String(stats?.catalog_items ?? 0)}
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.catalog_items_change ?? 0}% vs. пред. период`, direction: (stats?.catalog_items_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Объём сделок"
          value={`$${((stats?.deals_volume ?? 0) / 1000).toFixed(0)}K`}
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.deals_volume_change ?? 0}% vs. пред. период`, direction: (stats?.deals_volume_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Клиентов"
          value={String(stats?.clients_count ?? 0)}
          icon={<Calendar className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.clients_count_change ?? 0}% vs. пред. период`, direction: (stats?.clients_count_change ?? 0) >= 0 ? "up" : "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Bar Chart — Request Status */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">Мои заявки по статусам</CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={buyerRequestsStatus}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <RechartsTooltip
                  formatter={(value: number) => [value, 'Заявок']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Pie Chart — Request Status Distribution */}
        <Card className="py-0 gap-0">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-semibold">Статусы заявок</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="flex items-center justify-center">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie
                    data={buyerRequestsStatus}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={70}
                    dataKey="value"
                    strokeWidth={2}
                  >
                    {buyerRequestsStatus.map((_entry, i) => (
                      <Cell key={i} fill={buyerRequestsStatusColors[i % buyerRequestsStatusColors.length]} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 space-y-1.5">
              {buyerRequestsStatus.map((item, i) => (
                <div key={item.name} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: buyerRequestsStatusColors[i] }} />
                    <span className="font-medium">{item.name}</span>
                  </div>
                  <span className="text-muted-foreground">{item.value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ─── SELLER Dashboard ───────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function SellerDashboard({ onProductClick, period: _period, stats }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null }) {
  const dealVolumeData = stats?.deals_by_month ?? [];
  const activityByDay = stats?.activity_by_day ?? [];
  const counterpartyBreakdown = stats ? [
    { name: 'Производители', value: stats.counterparties.manufacturers, color: 'var(--color-chart-1)' },
    { name: 'Покупатели', value: stats.counterparties.buyers, color: 'var(--color-chart-2)' },
    { name: 'Посредники', value: stats.counterparties.intermediaries, color: 'var(--color-chart-4)' },
  ] : [];
  const completionPct = stats?.request_completion ?? 0;
  const completionGoal = stats?.request_completion_goal ?? 80;

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Объём сделок"
          value={`$${((stats?.deals_volume ?? 0) / 1000).toFixed(0)}K`}
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.deals_volume_change ?? 0}% vs. пред. период`, direction: (stats?.deals_volume_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Активные заявки"
          value={String(stats?.active_requests ?? 0)}
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.active_requests_change ?? 0}% vs. пред. период`, direction: (stats?.active_requests_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Позиций в каталоге"
          value={String(stats?.catalog_items ?? 0)}
          icon={<Package className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.catalog_items_change ?? 0}% vs. пред. период`, direction: (stats?.catalog_items_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Клиентов"
          value={String(stats?.clients_count ?? 0)}
          icon={<Users className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.clients_count_change ?? 0}% vs. пред. период`, direction: (stats?.clients_count_change ?? 0) >= 0 ? "up" : "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Area Chart — Deal Volume */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <div>
              <CardTitle className="text-sm font-semibold">Объём сделок</CardTitle>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold tabular-nums">${((stats?.deals_volume ?? 0) / 1000).toFixed(0)}K</span>
                <span className="text-xs font-medium text-muted-foreground">{stats?.deals_volume_change ?? 0}% vs. пред. период</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-4">
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
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v / 1000}K`} />
                <RechartsTooltip
                  formatter={(value: number) => [`$${(value / 1000).toFixed(0)}K`, 'Объём']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Area type="monotone" dataKey="value" stroke="var(--color-chart-1)" strokeWidth={2} fill="url(#colorVal)" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Bar Chart — Activity by Day */}
        <Card className="py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">Активность по дням</CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div className="mb-2 text-center">
              <span className="text-2xl font-bold tabular-nums">{activityByDay.reduce((s, d) => s + d.count, 0)}</span>
              <p className="text-xs text-muted-foreground">запросов за неделю</p>
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={activityByDay}>
                <XAxis dataKey="day" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <RechartsTooltip
                  formatter={(value: number) => [value, 'Запросов']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="count" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Top Products */}
        <div className="lg:col-span-2">
          <TopProductsTable onProductClick={onProductClick} topProducts={stats?.top_products ?? []} />
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-4">
          {/* Counterparty breakdown */}
          <Card className="py-0 gap-0">
            <CardHeader className="px-4 py-3">
              <CardTitle className="text-sm font-semibold">Контрагенты</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <div className="flex items-center justify-center">
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
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c.color }} />
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
              <CardTitle className="text-sm font-semibold">Выполнение заявок</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-3 px-4 pb-4">
              <span className="text-4xl font-bold text-primary tabular-nums">{completionPct}%</span>
              <p className="text-xs text-muted-foreground">Цель: {completionGoal}%</p>
              <Progress value={completionPct} className="h-2 w-full" />
              <Button variant="link" size="sm" className="text-xs">
                Показать детали
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ─── MANUFACTURER Dashboard ──────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ManufacturerDashboard({ onProductClick: _onProductClick, period: _period, stats }: { onProductClick?: (id: string) => void; period: string; stats: DashboardStats | null }) {
  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Активные заявки"
          value={String(stats?.active_requests ?? 0)}
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.active_requests_change ?? 0}% vs. пред. период`, direction: (stats?.active_requests_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Позиций в каталоге"
          value={String(stats?.catalog_items ?? 0)}
          icon={<AlertCircle className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.catalog_items_change ?? 0}% vs. пред. период`, direction: (stats?.catalog_items_change ?? 0) >= 0 ? "up" : "down" }}
        />
        <KPICard
          label="Выполнение заявок"
          value={`${stats?.request_completion ?? 0}%`}
          icon={<BarChart3 className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "—", direction: "flat" }}
        />
        <KPICard
          label="Объём сделок"
          value={`$${((stats?.deals_volume ?? 0) / 1000).toFixed(0)}K`}
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: `${stats?.deals_volume_change ?? 0}% vs. пред. период`, direction: (stats?.deals_volume_change ?? 0) >= 0 ? "up" : "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Bar Chart — Deals by Month */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">Сделки по месяцам</CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stats?.deals_by_month ?? []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v / 1000}K`} />
                <RechartsTooltip
                  formatter={(value: number) => [`$${(value / 1000).toFixed(0)}K`, 'Объём']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Completion */}
        <Card className="py-0 gap-0">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-semibold">Выполнение заявок</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-3 px-4 pb-4">
            <span className="text-4xl font-bold text-primary tabular-nums">{stats?.request_completion ?? 0}%</span>
            <p className="text-xs text-muted-foreground">Цель: {stats?.request_completion_goal ?? 80}%</p>
            <Progress value={stats?.request_completion ?? 0} className="h-2 w-full" />
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row — Top Products */}
      <TopProductsTable onProductClick={_onProductClick} topProducts={stats?.top_products ?? []} />
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────

interface DashboardProps {
  onProductClick?: (productId: string) => void;
}

export function Dashboard({ onProductClick }: DashboardProps) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState('30d');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const activeStatus = useUserStore((s) => s.activeStatus);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    dashboardApi.getStats(period)
      .then((data) => { if (!cancelled) setStats(data); })
      .catch((err) => { console.error('Dashboard stats fetch failed:', err); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [period]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{t('dashboardPage.title')}</h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-xs text-muted-foreground">
            <Calendar className="h-3.5 w-3.5" />
            <span>1 {t('dashboardPage.months.jan')} – 21 {t('dashboardPage.months.mar')} 2026</span>
          </div>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="h-8 w-[140px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">7 {t('dashboardPage.buyer.days')}</SelectItem>
              <SelectItem value="30d">30 {t('dashboardPage.buyer.days')}</SelectItem>
              <SelectItem value="90d">{t('dashboardPage.quarter')}</SelectItem>
              <SelectItem value="1y">{t('dashboardPage.year')}</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" className="gap-1.5 text-xs">
            <Download className="h-3.5 w-3.5" />
            {t('dashboardPage.export')}
          </Button>
        </div>
      </div>

      {/* Role-based dashboard content */}
      {activeStatus === 'BUYER' && <BuyerDashboard onProductClick={onProductClick} period={period} stats={stats} />}
      {activeStatus === 'SELLER' && <SellerDashboard onProductClick={onProductClick} period={period} stats={stats} />}
      {activeStatus === 'MANUFACTURER' && <ManufacturerDashboard onProductClick={onProductClick} period={period} stats={stats} />}
    </div>
  );
}
