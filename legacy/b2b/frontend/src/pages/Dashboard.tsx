import { useState } from 'react';
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
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
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

import { useTranslation } from 'react-i18next';
import { products } from '@/data/products';
import { useUserStore } from '@/store/userStore';


// ─── Mock Data ──────────────────────────────────────────────────────────

const dealVolumeData = [
  { month: 'Сен', value: 120000 },
  { month: 'Окт', value: 185000 },
  { month: 'Ноя', value: 142000 },
  { month: 'Дек', value: 210000 },
  { month: 'Янв', value: 175000 },
  { month: 'Фев', value: 230000 },
  { month: 'Мар', value: 280000 },
];

const activityByDay = [
  { day: 'Пн', requests: 12 },
  { day: 'Вт', requests: 18 },
  { day: 'Ср', requests: 15 },
  { day: 'Чт', requests: 22 },
  { day: 'Пт', requests: 14 },
  { day: 'Сб', requests: 5 },
  { day: 'Вс', requests: 2 },
];

// ─── BUYER Dashboard Data ───────────────────────────────────────────────

const buyerRequestsStatus = [
  { name: 'Черновик', value: 3 },
  { name: 'Отправлено', value: 5 },
  { name: 'КП получено', value: 2 },
  { name: 'Сделка', value: 1 },
  { name: 'Завершено', value: 8 },
];

const buyerRequestsStatusColors = ['var(--color-chart-1)', 'var(--color-chart-2)', 'var(--color-chart-3)', 'var(--color-chart-4)', 'var(--color-chart-5)'];

const buyerRecentRequests = [
  { id: 1, date: '2026-03-20', supplier: 'ООО Техсервис', items: 5, status: 'КП получено', amount: 125600 },
  { id: 2, date: '2026-03-19', supplier: 'ЗАО Транс', items: 3, status: 'Отправлено', amount: 78900 },
  { id: 3, date: '2026-03-18', supplier: 'ОДО РейлЭкспресс', items: 7, status: 'Отправлено', amount: 234500 },
  { id: 4, date: '2026-03-17', supplier: 'АО Снабжение', items: 2, status: 'КП получено', amount: 45200 },
  { id: 5, date: '2026-03-16', supplier: 'ЗАО РК Сервис', items: 4, status: 'Черновик', amount: 0 },
];

// ─── SELLER Dashboard Data ──────────────────────────────────────────────

const counterpartyBreakdown = [
  { name: 'Производители', value: 18, color: 'var(--color-chart-1)' },
  { name: 'Покупатели', value: 24, color: 'var(--color-chart-2)' },
  { name: 'Посредники', value: 5, color: 'var(--color-chart-4)' },
];

// ─── MANUFACTURER Dashboard Data ─────────────────────────────────────────

const productionLoadData = [
  { line: 'Линия ТЭД', value: 92 },
  { line: 'Линия тележек', value: 85 },
  { line: 'Линия колёс', value: 65 },
  { line: 'Прочее', value: 45 },
];

const manufacturerRFQs = [
  { id: 1, supplier: 'ОДО РейлСервис', product: 'Подшипник шариковый', qty: 150, daysToRespond: 2, status: 'Срочно' },
  { id: 2, supplier: 'АО Поставка+', product: 'Масло гидравлическое', qty: 500, daysToRespond: 5, status: 'Ожидает' },
  { id: 3, supplier: 'ЗАО Техсервис', product: 'Болты крепежные', qty: 2000, daysToRespond: 7, status: 'Обработано' },
  { id: 4, supplier: 'ООО Транс', product: 'Фильтр воздушный', qty: 80, daysToRespond: 3, status: 'Срочно' },
  { id: 5, supplier: 'АО Логистика', product: 'Кабель силовой', qty: 1200, daysToRespond: 10, status: 'В очереди' },
];

const productionPlanItems = [
  { name: 'Производство ТЭД', completed: 68, target: 85 },
  { name: 'Сборка тележек', completed: 92, target: 100 },
  { name: 'Тестирование', completed: 45, target: 60 },
];

// ─── Top Products Table ─────────────────────────────────────────────────

function TopProductsTable({ onProductClick }: { onProductClick?: (id: string) => void }) {
  const topProducts = products
    .filter((p) => p.status === 'in_stock')
    .sort((a, b) => b.quantity - a.quantity)
    .slice(0, 5);

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
          {topProducts.map((p) => (
            <TableRow
              key={p.id}
              className="cursor-pointer"
              onClick={() => onProductClick?.(p.id)}
            >
              <TableCell className="font-mono text-xs text-muted-foreground">{p.article}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
                    <Package className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <span className="text-sm font-medium truncate max-w-[180px]">{p.name}</span>
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm font-medium">
                {p.quantity} {p.uom}
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

function BuyerDashboard({ onProductClick: _onProductClick, period: _period }: { onProductClick?: (id: string) => void; period: string }) {
  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Активные заявки"
          value="12"
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+18.2% vs. 10 пред. период", direction: "up" }}
        />
        <KPICard
          label="Ожидают КП"
          value="5"
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "0% vs. 5 пред. период", direction: "flat" }}
        />
        <KPICard
          label="Экономия по сделкам"
          value="$45K"
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+12.3% vs. $40K пред. период", direction: "up" }}
        />
        <KPICard
          label="Средний срок поставки"
          value="18 дн"
          icon={<Calendar className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "-8.5% vs. 20 дн пред. период", direction: "down" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Bar Chart — Request Status */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">Мои заявки по статусам</CardTitle>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>По месяцам</DropdownMenuItem>
                <DropdownMenuItem>По неделям</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
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

      {/* Bottom Row — Recent Requests */}
      <Card className="py-0 gap-0">
        <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
          <CardTitle className="text-sm font-semibold">Последние заявки</CardTitle>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
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
              <TableHead className="text-xs">№</TableHead>
              <TableHead className="text-xs">Дата</TableHead>
              <TableHead className="text-xs">Поставщик</TableHead>
              <TableHead className="text-right text-xs">Позиций</TableHead>
              <TableHead className="text-xs">Статус</TableHead>
              <TableHead className="text-right text-xs">Сумма</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {buyerRecentRequests.map((req) => (
              <TableRow key={req.id} className="cursor-pointer hover:bg-muted/50">
                <TableCell className="font-mono text-xs text-muted-foreground">РЗ-{String(req.id).padStart(4, '0')}</TableCell>
                <TableCell className="text-xs">{req.date}</TableCell>
                <TableCell className="text-xs">{req.supplier}</TableCell>
                <TableCell className="text-right text-xs">{req.items}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-xs">
                    {req.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums text-xs font-medium">
                  {req.amount > 0 ? `$${(req.amount / 1000).toFixed(1)}K` : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

// ─── SELLER Dashboard ───────────────────────────────────────────────────

function SellerDashboard({ onProductClick, period: _period }: { onProductClick?: (id: string) => void; period: string }) {
  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Объём сделок"
          value="$280K"
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+24.4% vs. $225K пред. период", direction: "up" }}
        />
        <KPICard
          label="Активные заявки"
          value="47"
          icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+8.2% vs. 43 пред. период", direction: "up" }}
        />
        <KPICard
          label="Позиций в каталоге"
          value={String(products.length)}
          icon={<Package className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+17.6% vs. 17 пред. период", direction: "up" }}
        />
        <KPICard
          label="Клиентов"
          value="24"
          icon={<Users className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+4.4% vs. 23 пред. период", direction: "up" }}
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
                <span className="text-2xl font-bold tabular-nums">$280K</span>
                <span className="text-xs font-medium text-muted-foreground">+24.4% vs. пред. период</span>
              </div>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>По месяцам</DropdownMenuItem>
                <DropdownMenuItem>По неделям</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
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
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>Эта неделя</DropdownMenuItem>
                <DropdownMenuItem>Прошлая неделя</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div className="mb-2 text-center">
              <span className="text-2xl font-bold tabular-nums">88</span>
              <p className="text-xs text-muted-foreground">запросов за неделю</p>
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={activityByDay}>
                <XAxis dataKey="day" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <RechartsTooltip
                  formatter={(value: number) => [value, 'Запросов']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="requests" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Top Products */}
        <div className="lg:col-span-2">
          <TopProductsTable onProductClick={onProductClick} />
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem>Подробнее</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-3 px-4 pb-4">
              <span className="text-4xl font-bold text-primary tabular-nums">72%</span>
              <p className="text-xs text-muted-foreground">Цель: 80%</p>
              <Progress value={72} className="h-2 w-full" />
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

function ManufacturerDashboard({ onProductClick: _onProductClick, period: _period }: { onProductClick?: (id: string) => void; period: string }) {
  return (
    <div className="flex flex-col gap-6">
      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label="Входящие RFQ"
          value="15"
          icon={<FileText className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+25% vs. 12 пред. период", direction: "up" }}
        />
        <KPICard
          label="Ожидают ответа"
          value="4"
          icon={<AlertCircle className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "0% vs. 4 пред. период", direction: "flat" }}
        />
        <KPICard
          label="Загрузка производства"
          value="78%"
          icon={<BarChart3 className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+5.2% vs. 74% пред. период", direction: "up" }}
        />
        <KPICard
          label="Выручка за месяц"
          value="$142K"
          icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          trend={{ value: "+18.7% vs. $120K пред. период", direction: "up" }}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Bar Chart — Production Load */}
        <Card className="lg:col-span-2 py-0 gap-0">
          <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
            <CardTitle className="text-sm font-semibold">Загрузка по линиям</CardTitle>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>Подробнее</DropdownMenuItem>
                <DropdownMenuItem>Экспорт</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={productionLoadData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="line" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} domain={[0, 100]} />
                <RechartsTooltip
                  formatter={(value: number) => [`${value}%`, 'Загрузка']}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Production Plan Progress */}
        <Card className="py-0 gap-0">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-semibold">Производственный план</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 px-4 pb-4">
            {productionPlanItems.map((item) => {
              const percentage = Math.round((item.completed / item.target) * 100);
              return (
                <div key={item.name} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">{item.name}</span>
                    <span className="text-xs font-semibold text-primary">{percentage}%</span>
                  </div>
                  <Progress value={percentage} className="h-2 w-full" />
                  <div className="text-xs text-muted-foreground">
                    {item.completed} из {item.target}
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row — Recent RFQs */}
      <Card className="py-0 gap-0">
        <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
          <CardTitle className="text-sm font-semibold">Последние RFQ</CardTitle>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
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
              <TableHead className="text-xs">№</TableHead>
              <TableHead className="text-xs">Поставщик</TableHead>
              <TableHead className="text-xs">Товар</TableHead>
              <TableHead className="text-right text-xs">Кол-во</TableHead>
              <TableHead className="text-xs">Срок ответа</TableHead>
              <TableHead className="text-xs">Статус</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {manufacturerRFQs.map((rfq) => {
              return (
                <TableRow key={rfq.id} className="cursor-pointer hover:bg-muted/50">
                  <TableCell className="font-mono text-xs text-muted-foreground">РФК-{String(rfq.id).padStart(4, '0')}</TableCell>
                  <TableCell className="text-xs">{rfq.supplier}</TableCell>
                  <TableCell className="text-xs">{rfq.product}</TableCell>
                  <TableCell className="text-right text-xs">{rfq.qty}</TableCell>
                  <TableCell className="text-xs">{rfq.daysToRespond} дн</TableCell>
                  <TableCell>
                    <Badge
                      variant={rfq.status === 'Срочно' ? 'destructive' : 'outline'}
                      className="text-xs"
                    >
                      {rfq.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
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
  const activeStatus = useUserStore((s) => s.activeStatus);

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
      {activeStatus === 'BUYER' && <BuyerDashboard onProductClick={onProductClick} period={period} />}
      {activeStatus === 'SELLER' && <SellerDashboard onProductClick={onProductClick} period={period} />}
      {activeStatus === 'MANUFACTURER' && <ManufacturerDashboard onProductClick={onProductClick} period={period} />}
    </div>
  );
}
