import {
  ShoppingCart, FileText, Factory, BarChart3, Upload, Search, Plug,
  HelpCircle, ClipboardList, Calculator, Users, CalendarDays,
  Layers, Tags, Truck, Shield, ChevronRight, FileSpreadsheet,
  Clock, CheckCircle2, XCircle, AlertCircle, Star, Pause, Check,
  Zap, Flame, Package, UserRound,
  ChevronDown, Download, MapPin, Calendar,
  Mail, MessageSquare,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useFlowStore, requestStatusLabels, requestStatusColors } from '@/store/flowStore';
import { useUserStore } from '@/store/userStore';
import { Progress } from '@/components/ui/progress';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
} from 'recharts';

interface PageShellProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  stats?: { label: string; value: string }[];
  actions?: { label: string; variant?: 'default' | 'outline'; onClick?: () => void }[];
  children?: React.ReactNode;
}

function PageShell({ title, description, icon, stats, actions, children }: PageShellProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {actions && (
          <div className="flex gap-2">
            {actions.map((a, i) => (
              <Button key={i} variant={a.variant ?? 'default'} onClick={a.onClick}>{a.label}</Button>
            ))}
          </div>
        )}
      </div>
      {stats && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.map((s) => (
            <Card key={s.label} className="py-4 gap-1">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p className="text-2xl font-bold tabular-nums">{s.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {children ?? (
        <Card>
          <CardContent className="flex h-64 items-center justify-center">
            <div className="text-center text-muted-foreground">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
              <p className="text-sm font-medium">{t('pages.common.sectionInDevelopment')}</p>
              <p className="mt-1 text-xs">{t('pages.common.comingSoon')}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ─── Demo request card (shared between pages) ──────────────────────── */

function DemoRequestCard({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  const { request } = useFlowStore();
  const matchedCount = request.items.filter((i) => i.matchStatus === 'matched').length;
  const totalItems = request.items.length;

  return (
    <Card className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0" onClick={onOpen}>
      <CardContent className="px-4 py-4">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <FileSpreadsheet className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium">{request.number}</span>
              <Badge variant="outline" className={cn('text-xs', requestStatusColors[request.status])}>
                {requestStatusLabels[request.status]}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {request.clientName} · {totalItems} {t('pages.common.items')} · {matchedCount} {t('pages.common.found')} · {request.createdAt}
            </p>
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Sourcing Pages ─────────────────────────────────────────────────────

export function SourcingRequestsPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.sourcingRequests.title')}
      description={t('pages.sourcingRequests.description')}
      icon={<ClipboardList className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingRequests.stats.total'), value: '47' },
        { label: t('pages.sourcingRequests.stats.new'), value: '12' },
        { label: t('pages.sourcingRequests.stats.inProgress'), value: '23' },
        { label: t('pages.sourcingRequests.stats.completed'), value: '12' },
      ]}
      actions={[{ label: t('pages.sourcingRequests.createRequest') }]}
    >
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">{t('pages.sourcingRequests.activeRequests')}</p>
        <DemoRequestCard onOpen={() => onNavigate?.('request-detail')} />
      </div>
    </PageShell>
  );
}

export function SourcingImportPage() {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.sourcingImport.title')}
      description={t('pages.sourcingImport.description')}
      icon={<Upload className="h-5 w-5" />}
      actions={[{ label: t('pages.sourcingImport.uploadFile') }]}
    >
      <div className="space-y-6">
        {/* Upload Area */}
        <Card className="border-2 border-dashed border-muted-foreground/25 bg-muted/50">
          <CardContent className="flex flex-col items-center justify-center gap-3 py-12">
            <Upload className="h-10 w-10 text-muted-foreground/50" />
            <div className="text-center">
              <p className="font-medium">{t('pages.sourcingImport.dragDrop')}</p>
              <p className="text-sm text-muted-foreground">{t('pages.sourcingImport.orClick')}</p>
            </div>
          </CardContent>
        </Card>

        {/* Simulated Upload Result */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.sourcingImport.lastImport')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Спецификация_УТИ_2026_Q1.xlsx</p>
                <p className="text-sm text-muted-foreground">{t('pages.sourcingImport.uploadedAgo')}</p>
              </div>
              <Badge>{t('pages.sourcingImport.status.completed')}</Badge>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-lg bg-muted p-3">
                <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.stats.parsed')}</p>
                <p className="text-xl font-bold">156</p>
              </div>
              <div className="rounded-lg bg-muted p-3">
                <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.stats.found')}</p>
                <p className="text-xl font-bold">124</p>
                <p className="text-xs text-muted-foreground">(79%)</p>
              </div>
              <div className="rounded-lg bg-muted p-3">
                <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.stats.partial')}</p>
                <p className="text-xl font-bold">18</p>
                <p className="text-xs text-muted-foreground">(12%)</p>
              </div>
            </div>

            {/* Preview Table */}
            <div className="overflow-x-auto mt-6">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="px-3 py-2 text-left font-medium">{t('pages.sourcingImport.table.number')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('pages.sourcingImport.table.name')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('pages.sourcingImport.table.gost')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('pages.sourcingImport.table.uom')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('pages.sourcingImport.table.qty')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('pages.sourcingImport.table.status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { n: 1, name: 'ТЭД ЭД-118А', gost: 'ГОСТ 1234', uom: t('pages.common.uom.pcs'), qty: 12, status: 'matched' },
                    { n: 2, name: 'Тележка 18-100', gost: 'ГОСТ 5678', uom: t('pages.common.uom.pcs'), qty: 6, status: 'matched' },
                    { n: 3, name: 'Колёсная пара', gost: '', uom: t('pages.common.uom.set'), qty: 24, status: 'partial' },
                    { n: 4, name: 'Буфер автосцепного устройства', gost: 'ГОСТ 9101', uom: t('pages.common.uom.pcs'), qty: 36, status: 'matched' },
                    { n: 5, name: 'Подшипник сферический', gost: 'ГОСТ 5721', uom: t('pages.common.uom.pcs'), qty: 48, status: 'matched' },
                    { n: 6, name: 'Баббит Б83', gost: '', uom: t('pages.common.uom.kg'), qty: 500, status: 'partial' },
                    { n: 7, name: 'Проводка высоковольтная', gost: '', uom: t('pages.common.uom.km'), qty: 15, status: 'partial' },
                    { n: 8, name: 'Тормозной цилиндр ТЦ-14М', gost: 'ГОСТ 1876', uom: t('pages.common.uom.pcs'), qty: 12, status: 'matched' },
                  ].map((row) => (
                    <tr key={row.n} className="border-b hover:bg-muted/50">
                      <td className="px-3 py-2">{row.n}</td>
                      <td className="px-3 py-2">{row.name}</td>
                      <td className="px-3 py-2 text-muted-foreground">{row.gost}</td>
                      <td className="px-3 py-2">{row.uom}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.qty}</td>
                      <td className="px-3 py-2">
                        <Badge variant={row.status === 'matched' ? 'default' : row.status === 'partial' ? 'secondary' : 'destructive'} className="gap-1">
                          {row.status === 'matched' && <><CheckCircle2 className="h-3 w-3" /> {t('pages.sourcingImport.matchStatus.found')}</>}
                          {row.status === 'partial' && <><AlertCircle className="h-3 w-3" /> {t('pages.sourcingImport.matchStatus.partial')}</>}
                          {row.status !== 'matched' && row.status !== 'partial' && <><XCircle className="h-3 w-3" /> {t('pages.sourcingImport.matchStatus.notFound')}</>}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

export function SourcingMatchPage() {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.sourcingMatch.title')}
      description={t('pages.sourcingMatch.description')}
      icon={<Search className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingMatch.stats.unrecognized'), value: '8' },
        { label: t('pages.sourcingMatch.stats.matches'), value: '142' },
        { label: t('pages.sourcingMatch.stats.needReview'), value: '5' },
        { label: t('pages.sourcingMatch.stats.accuracy'), value: '94%' },
      ]}
    />
  );
}

// ─── CRM Pages ──────────────────────────────────────────────────────────

interface DealCard {
  id: string;
  number: string;
  client: string;
  amount: number;
  manager: string;
  days: number;
}

interface DealColumn {
  title: string;
  stage: string;
  deals: DealCard[];
}

export function DealsPage() {
  const { t } = useTranslation();
  const columns: DealColumn[] = [
    {
      title: 'DRAFT',
      stage: t('pages.deals.stages.draft'),
      deals: [
        { id: '1', number: 'D-2026-001', client: 'Navoi Mining', amount: 95, manager: 'Азиз Қ.', days: 3 },
        { id: '2', number: 'D-2026-002', client: 'Almalyk MMC', amount: 210, manager: 'Диана Р.', days: 1 },
      ]
    },
    {
      title: 'SOURCING',
      stage: t('pages.deals.stages.sourcing'),
      deals: [
        { id: '3', number: 'D-2026-003', client: 'Uzbekiston Temir Yullari', amount: 320, manager: 'Азиз Қ.', days: 5 },
        { id: '4', number: 'D-2026-004', client: 'Tashkent Metro', amount: 150, manager: 'Фарход М.', days: 2 },
        { id: '5', number: 'D-2026-005', client: 'Uz Railway Logistics', amount: 85, manager: 'Диана Р.', days: 7 },
      ]
    },
    {
      title: 'CALCULATING',
      stage: t('pages.deals.stages.calculating'),
      deals: [
        { id: '6', number: 'D-2026-006', client: 'Tashkent Locomotive Works', amount: 275, manager: 'Азиз Қ.', days: 4 },
        { id: '7', number: 'D-2026-007', client: 'Fergana Railway Terminal', amount: 120, manager: 'Фарход М.', days: 2 },
      ]
    },
    {
      title: 'QUOTE_SENT',
      stage: t('pages.deals.stages.quoteSent'),
      deals: [
        { id: '8', number: 'D-2026-008', client: 'UTY Bukhara Branch', amount: 180, manager: 'Диана Р.', days: 6 },
        { id: '9', number: 'D-2026-009', client: 'Samarkand Transport', amount: 65, manager: 'Азиз Қ.', days: 3 },
      ]
    },
    {
      title: 'CONTRACT_SIGNED',
      stage: t('pages.deals.stages.contractSigned'),
      deals: [
        { id: '10', number: 'D-2026-010', client: 'Khiva Railway Depot', amount: 155, manager: 'Фарход М.', days: 8 },
      ]
    },
    {
      title: 'CLOSED_WON',
      stage: t('pages.deals.stages.closedWon'),
      deals: [
        { id: '11', number: 'D-2026-011', client: 'UTY Karshi', amount: 245, manager: 'Азиз Қ.', days: 12 },
        { id: '12', number: 'D-2026-012', client: 'Andijan Logistics', amount: 98, manager: 'Диана Р.', days: 9 },
        { id: '13', number: 'D-2026-013', client: 'Navoi Port Authority', amount: 175, manager: 'Фарход М.', days: 15 },
      ]
    },
    {
      title: 'CLOSED_LOST',
      stage: t('pages.deals.stages.closedLost'),
      deals: [
        { id: '14', number: 'D-2026-014', client: 'Margilan Industrial', amount: 72, manager: 'Диана Р.', days: 10 },
      ]
    },
  ];

  return (
    <PageShell
      title={t('pages.deals.title')}
      description={t('pages.deals.description')}
      icon={<FileText className="h-5 w-5" />}
      stats={[
        { label: t('pages.deals.stats.total'), value: '14' },
        { label: t('pages.deals.stats.active'), value: '7' },
        { label: t('pages.deals.stats.quoteSent'), value: '2' },
        { label: t('pages.deals.stats.closedWon'), value: '3' },
      ]}
      actions={[{ label: t('pages.deals.newDeal') }]}
    >
      <div className="overflow-x-auto pb-4">
        <div className="flex gap-4 min-w-max">
          {columns.map((column) => (
            <div key={column.stage} className="flex-shrink-0 w-80">
              <div className={cn('rounded-lg p-4 space-y-3 bg-muted')}>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-sm">{column.stage}</h3>
                  <Badge variant="outline" className="text-xs">{column.deals.length}</Badge>
                </div>
                <div className="space-y-3">
                  {column.deals.map((deal) => (
                    <Card key={deal.id} className="cursor-pointer hover:shadow-md transition-shadow">
                      <CardContent className="p-3 space-y-2">
                        <div>
                          <p className="font-medium text-sm">{deal.number}</p>
                          <p className="text-xs text-muted-foreground">{deal.client}</p>
                        </div>
                        <div className="flex items-center justify-between">
                          <p className="text-lg font-bold text-primary">${deal.amount}K</p>
                          <Badge variant="secondary" className="text-xs">{deal.manager}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {deal.days} {t('pages.deals.daysInStage')}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </PageShell>
  );
}

export function QuotesPage() {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const isBuyer = activeStatus === 'BUYER';

  const sellerQuotes = [
    { number: 'КП-2026-001', client: 'UTY Tashkent', items: 12, amount: 45600, margin: 15, status: 'draft', statusLabel: t('pages.quotes.status.draft'), date: '2026-03-20' },
    { number: 'КП-2026-002', client: 'Navoi Mining', items: 8, amount: 28900, margin: 18, status: 'calculating', statusLabel: t('pages.quotes.status.calculating'), date: '2026-03-19' },
    { number: 'КП-2026-003', client: 'Uzbekiston Temir Yullari', items: 24, amount: 89500, margin: 12, status: 'sent', statusLabel: t('pages.quotes.status.sent'), date: '2026-03-18' },
    { number: 'КП-2026-004', client: 'Tashkent Metro', items: 15, amount: 52300, margin: 16, status: 'sent', statusLabel: t('pages.quotes.status.sent'), date: '2026-03-17' },
    { number: 'КП-2026-005', client: 'Almalyk MMC', items: 18, amount: 64200, margin: 20, status: 'approved', statusLabel: t('pages.quotes.status.approved'), date: '2026-03-15' },
    { number: 'КП-2026-006', client: 'Samarkand Transport', items: 6, amount: 21400, margin: 14, status: 'draft', statusLabel: t('pages.quotes.status.draft'), date: '2026-03-20' },
  ];

  const buyerQuotes = [
    { number: 'КП-2026-003', seller: 'OOO «RailTech»', items: 24, amount: 89500, status: 'review', statusLabel: t('pages.quotes.status.underReview'), date: '2026-03-18', deadline: '2026-03-25' },
    { number: 'КП-2026-007', seller: 'SAUT Plant', items: 8, amount: 34200, status: 'accepted', statusLabel: t('pages.quotes.status.accepted'), date: '2026-03-15', deadline: '—' },
    { number: 'КП-2026-008', seller: 'Uz Railway Logistics', items: 5, amount: 18900, status: 'review', statusLabel: t('pages.quotes.status.underReview'), date: '2026-03-19', deadline: '2026-03-26' },
    { number: 'КП-2026-009', seller: 'RATEP Ekb', items: 12, amount: 52800, status: 'expired', statusLabel: t('pages.quotes.status.expired'), date: '2026-03-05', deadline: '2026-03-12' },
  ];

  if (isBuyer) {
    return (
      <PageShell
        title={t('pages.quotes.buyerTitle')}
        description={t('pages.quotes.buyerDescription')}
        icon={<Calculator className="h-5 w-5" />}
        stats={[
          { label: t('pages.quotes.stats.total'), value: String(buyerQuotes.length) },
          { label: t('pages.quotes.stats.underReview'), value: '2' },
          { label: t('pages.quotes.stats.accepted'), value: '1' },
          { label: t('pages.quotes.stats.totalAmount'), value: '$195K' },
        ]}
      >
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.number')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.supplier')}</th>
                    <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.items')}</th>
                    <th className="px-4 py-3 text-right font-medium">{t('pages.quotes.table.amountVat')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.status')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.date')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.deadline')}</th>
                    <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {buyerQuotes.map((q, idx) => (
                    <tr key={idx} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium">{q.number}</td>
                      <td className="px-4 py-3">{q.seller}</td>
                      <td className="px-4 py-3 text-center">{q.items}</td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium">${q.amount.toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <Badge variant={
                          q.status === 'accepted' ? 'default' :
                          q.status === 'review' ? 'secondary' :
                          'outline'
                        }>
                          {q.statusLabel}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{q.date}</td>
                      <td className="px-4 py-3 text-muted-foreground">{q.deadline}</td>
                      <td className="px-4 py-3 text-center">
                        <Button variant="ghost" size="sm" className="h-8 w-8">
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell
      title={t('pages.quotes.sellerTitle')}
      description={t('pages.quotes.sellerDescription')}
      icon={<Calculator className="h-5 w-5" />}
      stats={[
        { label: t('pages.quotes.stats.drafts'), value: '2' },
        { label: t('pages.quotes.stats.sent'), value: '2' },
        { label: t('pages.quotes.stats.approved'), value: '1' },
        { label: t('pages.quotes.stats.pipeline'), value: '$302K' },
      ]}
      actions={[{ label: t('pages.quotes.createQuote') }]}
    >
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.number')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.client')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.items')}</th>
                  <th className="px-4 py-3 text-right font-medium">{t('pages.quotes.table.amount')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.margin')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.status')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.date')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {sellerQuotes.map((quote, idx) => (
                  <tr key={idx} className="border-b hover:bg-muted/50">
                    <td className="px-4 py-3 font-medium">{quote.number}</td>
                    <td className="px-4 py-3">{quote.client}</td>
                    <td className="px-4 py-3 text-center">{quote.items}</td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">${quote.amount.toLocaleString()}</td>
                    <td className="px-4 py-3 text-center">{quote.margin}%</td>
                    <td className="px-4 py-3">
                      <Badge variant={
                        quote.status === 'approved' ? 'default' :
                        quote.status === 'sent' ? 'secondary' :
                        'outline'
                      }>
                        {quote.statusLabel}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{quote.date}</td>
                    <td className="px-4 py-3 text-center">
                      <Button variant="ghost" size="sm" className="h-8 w-8">
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

export function ClientsPage() {
  const { t } = useTranslation();
  const clients = [
    { name: 'Uzbekiston Temir Yullari (UTY)', inn: '201234567890', status: 'BUYER', kyc: 'Verified', deals: 8, lastActivity: '2026-03-20' },
    { name: 'Navoi Mining Company', inn: '201345678901', status: 'SELLER', kyc: 'Verified', deals: 5, lastActivity: '2026-03-19' },
    { name: 'Almalyk MMC', inn: '201456789012', status: 'MANUFACTURER', kyc: 'Verified', deals: 12, lastActivity: '2026-03-20' },
    { name: 'Tashkent Metro LLC', inn: '201567890123', status: 'BUYER', kyc: 'Pending', deals: 3, lastActivity: '2026-03-18' },
    { name: 'Uz Railway Logistics', inn: '201678901234', status: 'SELLER', kyc: 'Verified', deals: 7, lastActivity: '2026-03-17' },
    { name: 'Samarkand Transport', inn: '201789012345', status: 'BUYER', kyc: 'Pending', deals: 2, lastActivity: '2026-03-16' },
    { name: 'Tashkent Locomotive Works', inn: '201890123456', status: 'MANUFACTURER', kyc: 'Verified', deals: 9, lastActivity: '2026-03-20' },
    { name: 'Fergana Railway Terminal', inn: '201901234567', status: 'BUYER', kyc: 'Verified', deals: 4, lastActivity: '2026-03-15' },
  ];

  return (
    <PageShell
      title={t('pages.clients.title')}
      description={t('pages.clients.description')}
      icon={<Users className="h-5 w-5" />}
      stats={[
        { label: t('pages.clients.stats.total'), value: '50' },
        { label: t('pages.clients.stats.verified'), value: '24' },
        { label: t('pages.clients.stats.awaitingKyc'), value: '8' },
        { label: t('pages.clients.stats.guests'), value: '18' },
      ]}
      actions={[{ label: t('pages.clients.addClient') }]}
    >
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.company')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.inn')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.status')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.kyc')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.clients.table.deals')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.lastActivity')}</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((client, idx) => (
                  <tr key={idx} className="border-b hover:bg-muted/50">
                    <td className="px-4 py-3 font-medium">{client.name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{client.inn}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline">{
                        client.status === 'BUYER' ? t('pages.clients.statusLabel.buyer') :
                        client.status === 'SELLER' ? t('pages.clients.statusLabel.seller') :
                        t('pages.clients.statusLabel.manufacturer')
                      }</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={client.kyc === 'Verified' ? 'default' : 'secondary'} className="gap-1">
                        {client.kyc === 'Verified' ? <><Check className="h-3 w-3" /> {t('pages.clients.kycStatus.verified')}</> : <><Clock className="h-3 w-3" /> {t('pages.clients.kycStatus.pending')}</>}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums">{client.deals}</td>
                    <td className="px-4 py-3 text-muted-foreground">{client.lastActivity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

// ─── Production Pages ───────────────────────────────────────────────────

export function ProductionOrdersPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.productionOrders.title')}
      description={t('pages.productionOrders.description')}
      icon={<Factory className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionOrders.stats.active'), value: '12' },
        { label: t('pages.productionOrders.stats.awaitingResponse'), value: '3' },
        { label: t('pages.productionOrders.stats.responded'), value: '7' },
        { label: t('pages.productionOrders.stats.overdue'), value: '2' },
      ]}
    >
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">{t('pages.productionOrders.partnerRequests')}</p>
        <DemoRequestCard onOpen={() => onNavigate?.('request-detail')} />
      </div>
    </PageShell>
  );
}

export function ProductionSchedulePage() {
  const { t } = useTranslation();
  const orders = [
    { name: 'ТЭД ЭД-118А × 12', progress: 75, deadline: '2026-04-15', status: t('pages.productionSchedule.status.inProduction') },
    { name: 'Тележка 18-100 × 6', progress: 40, deadline: '2026-04-30', status: t('pages.productionSchedule.status.inProduction') },
    { name: 'Колёсная пара × 24', progress: 90, deadline: '2026-03-25', status: t('pages.productionSchedule.status.finishing') },
    { name: 'Буфер автосцепного устройства × 36', progress: 55, deadline: '2026-05-10', status: t('pages.productionSchedule.status.inProduction') },
  ];

  return (
    <PageShell
      title={t('pages.productionSchedule.title')}
      description={t('pages.productionSchedule.description')}
      icon={<CalendarDays className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionSchedule.stats.activeOrders'), value: '4' },
        { label: t('pages.productionSchedule.stats.completed'), value: '12' },
        { label: t('pages.productionSchedule.stats.delayed'), value: '0' },
        { label: t('pages.productionSchedule.stats.nextWeek'), value: '2' },
      ]}
    >
      <div className="space-y-4">
        {orders.map((order, idx) => (
          <Card key={idx}>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium">{order.name}</p>
                  <p className="text-xs text-muted-foreground mt-1 flex items-center gap-2">
                    <Calendar className="h-3 w-3" />
                    {t('pages.productionSchedule.deadline')}: {order.deadline}
                  </p>
                </div>
                <Badge>{order.status}</Badge>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{t('pages.productionSchedule.progress')}</span>
                  <span className="font-medium tabular-nums">{order.progress}%</span>
                </div>
                <Progress value={order.progress} className="h-2" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

// ─── Analytics ──────────────────────────────────────────────────────────

export function AnalyticsPage() {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();

  if (activeStatus === 'BUYER') {
    return <BuyerAnalytics />;
  }

  // Seller / Manufacturer analytics
  const funnelData = [
    { stage: t('pages.analytics.funnel.incomingRequests'), value: 100 },
    { stage: t('pages.analytics.funnel.quoteSent'), value: 65 },
    { stage: t('pages.analytics.funnel.approved'), value: 28 },
    { stage: t('pages.analytics.funnel.deal'), value: 18 },
  ];

  const revenueData = [
    { month: t('pages.analytics.months.sep'), revenue: 45 },
    { month: t('pages.analytics.months.oct'), revenue: 52 },
    { month: t('pages.analytics.months.nov'), revenue: 48 },
    { month: t('pages.analytics.months.dec'), revenue: 61 },
    { month: t('pages.analytics.months.jan'), revenue: 55 },
    { month: t('pages.analytics.months.feb'), revenue: 67 },
  ];

  const colors = ['var(--color-chart-1)', 'var(--color-chart-2)', 'var(--color-chart-5)', 'var(--color-chart-4)'];

  return (
    <PageShell
      title={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerTitle') : t('pages.analytics.sellerTitle')}
      description={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerDescription') : t('pages.analytics.sellerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.stats.conversion'), value: '18%' },
        { label: t('pages.analytics.stats.avgDeal'), value: '$18.4K' },
        { label: t('pages.analytics.stats.pipeline'), value: '$380K' },
        { label: t('pages.analytics.stats.winRate'), value: '35%' },
      ]}
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.analytics.conversionFunnel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {funnelData.map((item, idx) => {
              const percentage = (item.value / 100) * 100;
              return (
                <div key={idx} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium">{item.stage}</span>
                    <span className="text-muted-foreground">{item.value} ({percentage.toFixed(0)}%)</span>
                  </div>
                  <div className="h-8 rounded-full overflow-hidden bg-muted">
                    <div
                      className="h-full rounded-full flex items-center justify-end pr-2 text-xs font-medium text-primary-foreground"
                      style={{ width: `${percentage}%`, backgroundColor: colors[idx] }}
                    >
                      {percentage > 20 && `${percentage.toFixed(0)}%`}
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.analytics.revenueByMonth')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={revenueData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="month" stroke="var(--color-muted-foreground)" />
                <YAxis stroke="var(--color-muted-foreground)" />
                <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-card)', border: '1px solid var(--color-border)' }} />
                <Bar dataKey="revenue" fill="var(--color-chart-1)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

function BuyerAnalytics() {
  const { t } = useTranslation();
  const spendData = [
    { month: t('pages.analytics.months.sep'), spend: 32 },
    { month: t('pages.analytics.months.oct'), spend: 41 },
    { month: t('pages.analytics.months.nov'), spend: 38 },
    { month: t('pages.analytics.months.dec'), spend: 55 },
    { month: t('pages.analytics.months.jan'), spend: 48 },
    { month: t('pages.analytics.months.feb'), spend: 62 },
  ];

  const categoryData = [
    { name: t('pages.analytics.categories.railwayEquipment'), value: 45, color: 'var(--color-chart-1)' },
    { name: t('pages.analytics.categories.spareParts'), value: 28, color: 'var(--color-chart-2)' },
    { name: t('pages.analytics.categories.rawMaterials'), value: 18, color: 'var(--color-chart-3)' },
    { name: t('pages.analytics.categories.services'), value: 9, color: 'var(--color-chart-4)' },
  ];

  const suppliers = [
    { name: 'SAUT Plant', orders: 14, total: '$124,500', avgDelivery: t('pages.analytics.supplierDays', { count: 12 }), rating: 4.8 },
    { name: 'RATEP Ekb', orders: 9, total: '$87,200', avgDelivery: t('pages.analytics.supplierDays', { count: 18 }), rating: 4.5 },
    { name: 'Almalyk MMC', orders: 6, total: '$52,300', avgDelivery: t('pages.analytics.supplierDays', { count: 8 }), rating: 4.9 },
    { name: 'Navoi Mining', orders: 4, total: '$34,100', avgDelivery: t('pages.analytics.supplierDays', { count: 15 }), rating: 4.2 },
  ];

  return (
    <PageShell
      title={t('pages.analytics.buyerTitle')}
      description={t('pages.analytics.buyerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.buyerStats.spendPeriod'), value: '$276K' },
        { label: t('pages.analytics.buyerStats.savings'), value: '$18.2K' },
        { label: t('pages.analytics.buyerStats.activeRequests'), value: '12' },
        { label: t('pages.analytics.buyerStats.avgDelivery'), value: t('pages.analytics.supplierDays', { count: 14 }) },
      ]}
    >
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Spend by Month */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.analytics.spendByMonth')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={spendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="month" stroke="var(--color-muted-foreground)" />
                <YAxis stroke="var(--color-muted-foreground)" />
                <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-card)', border: '1px solid var(--color-border)' }} />
                <Bar dataKey="spend" fill="var(--color-chart-1)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Spend by Category */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.analytics.spendStructure')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {categoryData.map((cat, idx) => (
              <div key={idx} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{cat.name}</span>
                  <span className="text-muted-foreground">{cat.value}%</span>
                </div>
                <div className="h-6 rounded-full overflow-hidden bg-muted">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${cat.value}%`, backgroundColor: cat.color }}
                  />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Top Suppliers */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">{t('pages.analytics.supplierRating')}</CardTitle>
            <CardDescription>{t('pages.analytics.supplierRatingDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium">{t('pages.analytics.supplierTable.supplier')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.analytics.supplierTable.orders')}</th>
                  <th className="px-4 py-3 text-right font-medium">{t('pages.analytics.supplierTable.amount')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.analytics.supplierTable.avgDelivery')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.analytics.supplierTable.rating')}</th>
                </tr>
              </thead>
              <tbody>
                {suppliers.map((s, idx) => (
                  <tr key={idx} className="border-b hover:bg-muted/30">
                    <td className="px-4 py-3 font-medium">{s.name}</td>
                    <td className="px-4 py-3 text-center tabular-nums">{s.orders}</td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">{s.total}</td>
                    <td className="px-4 py-3 text-center text-muted-foreground">{s.avgDelivery}</td>
                    <td className="px-4 py-3 text-center">
                      <Badge variant="outline" className="gap-1">
                        <Star className="h-3 w-3 fill-current" /> {s.rating}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

// ─── Catalog Sub-pages ──────────────────────────────────────────────────

export function CategoriesPage() {
  const { t } = useTranslation();
  const categories = [
    {
      name: t('pages.categories.items.railwayTech'),
      subcats: [
        { name: t('pages.categories.items.tractionRollingStock'), items: [t('pages.categories.items.ted'), t('pages.categories.items.dieselLocos'), t('pages.categories.items.electricLocos')] },
        { name: t('pages.categories.items.brakeEquipment'), items: [t('pages.categories.items.cylinders'), t('pages.categories.items.valves'), t('pages.categories.items.hoses')] },
      ]
    },
    {
      name: t('pages.categories.items.materials'),
      subcats: [
        { name: t('pages.categories.items.nonFerrousMetals'), items: [t('pages.categories.items.babbits'), t('pages.categories.items.bronze'), t('pages.categories.items.tin')] },
      ]
    },
    {
      name: t('pages.categories.items.metalProducts'),
      subcats: [
        { name: t('pages.categories.items.assortment'), items: [t('pages.categories.items.round'), t('pages.categories.items.strip'), t('pages.categories.items.pipe'), t('pages.categories.items.profile')] },
      ]
    },
    {
      name: t('pages.categories.items.electricalEquipment'),
      subcats: [
        { name: t('pages.categories.items.cableProducts'), items: [t('pages.categories.items.wires'), t('pages.categories.items.cables'), t('pages.categories.items.couplings')] },
        { name: t('pages.categories.items.generatingEquipment'), items: [t('pages.categories.items.generators'), t('pages.categories.items.transformers')] },
      ]
    },
  ];

  return (
    <PageShell
      title={t('pages.categories.title')}
      description={t('pages.categories.description')}
      icon={<Tags className="h-5 w-5" />}
      actions={[{ label: t('pages.categories.addCategory') }]}
    >
      <div className="space-y-2">
        {categories.map((cat, idx) => (
          <Collapsible key={idx} defaultOpen={idx === 0}>
            <Card className="border">
              <CardContent className="p-0">
                <CollapsibleTrigger asChild>
                  <button className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors">
                    <div className="flex items-center gap-2">
                      <ChevronDown className="h-4 w-4 transition-transform" />
                      <span className="font-medium">{cat.name}</span>
                    </div>
                    <Badge variant="outline" className="text-xs">{cat.subcats.reduce((sum, s) => sum + s.items.length, 0)} {t('pages.common.items')}</Badge>
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="border-t bg-muted/30 p-4 space-y-3">
                    {cat.subcats.map((subcat, sidx) => (
                      <div key={sidx} className="ml-4">
                        <p className="text-sm font-medium text-muted-foreground">{subcat.name}</p>
                        <div className="flex flex-wrap gap-2 mt-2">
                          {subcat.items.map((item, iidx) => (
                            <Badge key={iidx} variant="secondary" className="text-xs">{item}</Badge>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </CollapsibleContent>
              </CardContent>
            </Card>
          </Collapsible>
        ))}
      </div>
    </PageShell>
  );
}

export function EquipmentGroupsPage() {
  const { t } = useTranslation();
  const groups = [
    { name: t('pages.equipmentGroups.items.electricLocos'), icon: <Zap className="h-6 w-6 text-primary" />, series: 8, components: 156 },
    { name: t('pages.equipmentGroups.items.dieselLocos'), icon: <Flame className="h-6 w-6 text-primary" />, series: 12, components: 284 },
    { name: t('pages.equipmentGroups.items.freightWagons'), icon: <Package className="h-6 w-6 text-primary" />, series: 15, components: 342 },
    { name: t('pages.equipmentGroups.items.passengerWagons'), icon: <UserRound className="h-6 w-6 text-primary" />, series: 6, components: 198 },
  ];

  return (
    <PageShell
      title={t('pages.equipmentGroups.title')}
      description={t('pages.equipmentGroups.description')}
      icon={<Layers className="h-5 w-5" />}
      actions={[{ label: t('pages.equipmentGroups.addGroup') }]}
    >
      <div className="grid gap-4 md:grid-cols-2">
        {groups.map((group, idx) => (
          <Card key={idx} className="cursor-pointer hover:shadow-md transition-shadow">
            <CardContent className="p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="text-4xl">{group.icon}</div>
                <ChevronRight className="h-5 w-5 text-muted-foreground" />
              </div>
              <h3 className="font-semibold text-lg mb-3">{group.name}</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">{t('pages.equipmentGroups.series')}</p>
                  <p className="text-2xl font-bold">{group.series}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t('pages.equipmentGroups.components')}</p>
                  <p className="text-2xl font-bold">{group.components}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

// ─── Integrations & Help ────────────────────────────────────────────────

export function IntegrationsPage() {
  const { t } = useTranslation();
  const integrations = [
    { name: '1C:Предприятие', description: t('pages.integrations.items.1c'), status: 'connected', lastSync: t('pages.integrations.syncAgo', { time: '15' }), records: '1,240' },
    { name: 'SAP ERP', description: t('pages.integrations.items.sap'), status: 'disconnected', lastSync: '—', records: '—' },
    { name: 'Telegram Bot', description: t('pages.integrations.items.telegram'), status: 'connected', lastSync: t('pages.integrations.realtime'), records: t('pages.integrations.messages', { count: '342' }) },
    { name: 'Email SMTP', description: t('pages.integrations.items.email'), status: 'connected', lastSync: t('pages.integrations.syncAgo', { time: '2' }), records: t('pages.integrations.emails', { count: '89' }) },
    { name: 'ASAN Imzo', description: t('pages.integrations.items.asan'), status: 'pending', lastSync: '—', records: '—' },
    { name: 'Uzum Bank API', description: t('pages.integrations.items.uzum'), status: 'disconnected', lastSync: '—', records: '—' },
  ];

  return (
    <PageShell
      title={t('pages.integrations.title')}
      description={t('pages.integrations.description')}
      icon={<Plug className="h-5 w-5" />}
      stats={[
        { label: t('pages.integrations.stats.connected'), value: '3' },
        { label: t('pages.integrations.stats.pending'), value: '1' },
        { label: t('pages.integrations.stats.availableApis'), value: '12' },
        { label: t('pages.integrations.stats.syncedRecords'), value: '1,671' },
      ]}
      actions={[{ label: t('pages.integrations.apiDocs'), variant: 'outline' }, { label: t('pages.integrations.addIntegration') }]}
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {integrations.map((int, idx) => (
          <Card key={idx} className="border">
            <CardContent className="p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg flex items-center justify-center bg-muted">
                    <Plug className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{int.name}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">{int.description}</p>
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between mb-3">
                <Badge variant={
                  int.status === 'connected' ? 'default' :
                  int.status === 'pending' ? 'secondary' :
                  'outline'
                }>
                  {int.status === 'connected' ? t('pages.integrations.statusLabel.connected') : int.status === 'pending' ? t('pages.integrations.statusLabel.configuring') : t('pages.integrations.statusLabel.disconnected')}
                </Badge>
                {int.status === 'connected' && (
                  <span className="text-xs text-muted-foreground">{int.lastSync}</span>
                )}
              </div>
              {int.status === 'connected' && (
                <div className="text-xs text-muted-foreground mb-3">
                  {t('pages.integrations.processed')}: <span className="font-medium text-foreground">{int.records}</span>
                </div>
              )}
              <Button size="sm" variant={int.status === 'connected' ? 'outline' : 'default'} className="w-full">
                {int.status === 'connected' ? t('pages.integrations.settings') : int.status === 'pending' ? t('pages.integrations.finishSetup') : t('pages.integrations.connect')}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

export function HelpPage() {
  const { t } = useTranslation();
  const categories = [
    {
      title: t('pages.help.sections.gettingStarted'),
      items: [
        { question: t('pages.help.faq.howRegister'), answer: t('pages.help.faq.howRegisterAnswer') },
        { question: t('pages.help.faq.howAddEmployees'), answer: t('pages.help.faq.howAddEmployeesAnswer') },
        { question: t('pages.help.faq.howSwitchStatus'), answer: t('pages.help.faq.howSwitchStatusAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.procurement'),
      items: [
        { question: t('pages.help.faq.howCreateRequest'), answer: t('pages.help.faq.howCreateRequestAnswer') },
        { question: t('pages.help.faq.excelFormats'), answer: t('pages.help.faq.excelFormatsAnswer') },
        { question: t('pages.help.faq.whatIsSmartMatch'), answer: t('pages.help.faq.whatIsSmartMatchAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.quotesAndPricing'),
      items: [
        { question: t('pages.help.faq.howLandedCost'), answer: t('pages.help.faq.howLandedCostAnswer') },
        { question: t('pages.help.faq.canEditSentQuote'), answer: t('pages.help.faq.canEditSentQuoteAnswer') },
        { question: t('pages.help.faq.howRequestDiscount'), answer: t('pages.help.faq.howRequestDiscountAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.securityAndAccess'),
      items: [
        { question: t('pages.help.faq.whatRoles'), answer: t('pages.help.faq.whatRolesAnswer') },
        { question: t('pages.help.faq.howResetPassword'), answer: t('pages.help.faq.howResetPasswordAnswer') },
      ],
    },
  ];

  return (
    <PageShell
      title={t('pages.help.title')}
      description={t('pages.help.description')}
      icon={<HelpCircle className="h-5 w-5" />}
    >
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Quick Actions */}
        <div className="lg:col-span-3 grid gap-4 grid-cols-1 sm:grid-cols-3">
          {[
            { icon: <FileText className="h-5 w-5" />, title: t('pages.help.quickActions.apiDocs'), desc: t('pages.help.quickActions.apiDocsDesc') },
            { icon: <MessageSquare className="h-5 w-5" />, title: t('pages.help.quickActions.telegramSupport'), desc: t('pages.help.quickActions.telegramSupportDesc') },
            { icon: <Mail className="h-5 w-5" />, title: t('pages.help.quickActions.emailSupport'), desc: 'support@railtech.uz' },
          ].map((action, i) => (
            <Card key={i} className="cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-primary/10 text-primary">
                  {action.icon}
                </div>
                <div>
                  <p className="text-sm font-medium">{action.title}</p>
                  <p className="text-xs text-muted-foreground">{action.desc}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* FAQ Sections */}
        <div className="lg:col-span-3 space-y-6">
          {categories.map((cat, catIdx) => (
            <div key={catIdx}>
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">{cat.title}</h3>
              <div className="space-y-2">
                {cat.items.map((faq, idx) => (
                  <Collapsible key={idx}>
                    <Card className="border">
                      <CardContent className="p-0">
                        <CollapsibleTrigger asChild>
                          <button className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors">
                            <span className="font-medium text-sm text-left">{faq.question}</span>
                            <ChevronDown className="h-4 w-4 transition-transform flex-shrink-0 ml-2" />
                          </button>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <div className="border-t bg-muted/30 p-4 text-sm text-muted-foreground">
                            {faq.answer}
                          </div>
                        </CollapsibleContent>
                      </CardContent>
                    </Card>
                  </Collapsible>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Support Contact */}
        <Card className="lg:col-span-3 border-primary/20 bg-primary/5">
          <CardContent className="p-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 justify-between">
              <div>
                <h3 className="font-semibold text-base mb-1">{t('pages.help.needHelp')}</h3>
                <p className="text-sm text-muted-foreground">{t('pages.help.supportHours')}</p>
                <div className="flex items-center gap-4 mt-2 text-sm">
                  <span className="flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> support@railtech.uz</span>
                  <span className="flex items-center gap-1.5"><MessageSquare className="h-3.5 w-3.5" /> +998 (71) 200-00-00</span>
                </div>
              </div>
              <Button>{t('pages.help.contactSupport')}</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

// ─── Client-specific Pages ──────────────────────────────────────────────

export function MyRequestsPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={[
        { label: t('pages.myRequests.stats.active'), value: '3' },
        { label: t('pages.myRequests.stats.quoteReceived'), value: '2' },
        { label: t('pages.myRequests.stats.contract'), value: '1' },
        { label: t('pages.myRequests.stats.completed'), value: '8' },
      ]}
      actions={[{ label: t('pages.myRequests.newRequest') }]}
    >
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">{t('pages.myRequests.recentRequests')}</p>
        <DemoRequestCard onOpen={() => onNavigate?.('request-detail')} />
      </div>
    </PageShell>
  );
}

export function MyDocumentsPage() {
  const { t } = useTranslation();
  const documents = [
    { type: t('pages.documents.types.quote'), number: 'КП-2026-001', date: '2026-03-20', counterparty: 'UTY Tashkent', status: 'sent', statusLabel: t('pages.documents.status.sent'), amount: '$45,600' },
    { type: t('pages.documents.types.contract'), number: 'ДГ-2026-001', date: '2026-03-15', counterparty: 'Almalyk MMC', status: 'signed', statusLabel: t('pages.documents.status.signed'), amount: '$64,200' },
    { type: t('pages.documents.types.act'), number: 'АК-2026-001', date: '2026-03-10', counterparty: 'Navoi Mining', status: 'archive', statusLabel: t('pages.documents.status.archive'), amount: '$28,900' },
    { type: t('pages.documents.types.invoice'), number: 'ИН-2026-001', date: '2026-03-18', counterparty: 'Tashkent Metro', status: 'pending', statusLabel: t('pages.documents.status.pendingPayment'), amount: '$52,300' },
    { type: t('pages.documents.types.quote'), number: 'КП-2026-002', date: '2026-03-19', counterparty: 'Navoi Mining', status: 'draft', statusLabel: t('pages.documents.status.draft'), amount: '$28,900' },
    { type: t('pages.documents.types.contract'), number: 'ДГ-2026-002', date: '2026-03-12', counterparty: 'Uzbekiston Temir Yullari', status: 'forSignature', statusLabel: t('pages.documents.status.forSignature'), amount: '$89,500' },
  ];

  return (
    <PageShell
      title={t('pages.documents.title')}
      description={t('pages.documents.description')}
      icon={<FileText className="h-5 w-5" />}
      actions={[{ label: t('pages.documents.uploadDocument') }]}
    >
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium">{t('pages.documents.table.type')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.documents.table.number')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.documents.table.date')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.documents.table.counterparty')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.documents.table.status')}</th>
                  <th className="px-4 py-3 text-right font-medium">{t('pages.documents.table.amount')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.documents.table.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc, idx) => (
                  <tr key={idx} className="border-b hover:bg-muted/50">
                    <td className="px-4 py-3 font-medium">{doc.type}</td>
                    <td className="px-4 py-3">{doc.number}</td>
                    <td className="px-4 py-3">{doc.date}</td>
                    <td className="px-4 py-3">{doc.counterparty}</td>
                    <td className="px-4 py-3">
                      <Badge variant={
                        doc.status === 'signed' ? 'default' :
                        doc.status === 'pending' ? 'secondary' :
                        doc.status === 'forSignature' ? 'outline' :
                        'secondary'
                      }>
                        {doc.statusLabel}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">{doc.amount}</td>
                    <td className="px-4 py-3 text-center">
                      <Button variant="ghost" size="sm" className="h-8 w-8">
                        <Download className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

// ─── Logistics Page ────────────────────────────────────────────────────

export function LogisticsPage() {
  const { t } = useTranslation();
  const shipments = [
    { number: 'ШП-001', route: 'Москва \u2192 Ташкент', status: 'in_transit', etd: '2026-03-18', eta: '2026-03-28', carrier: 'РЖД Логистика' },
    { number: 'ШП-002', route: 'СПб \u2192 Ташкент', status: 'customs', etd: '2026-03-15', eta: '2026-04-05', carrier: 'TransCaspian' },
    { number: 'ШП-003', route: 'Екатеринбург \u2192 Ташкент', status: 'in_transit', etd: '2026-03-20', eta: '2026-03-30', carrier: 'УТ-Логистика' },
    { number: 'ШП-004', route: 'Москва \u2192 Ташкент', status: 'delivered', etd: '2026-03-05', eta: '2026-03-15', carrier: 'РЖД Логистика' },
    { number: 'ШП-005', route: 'СПб \u2192 Бухара', status: 'in_transit', etd: '2026-03-17', eta: '2026-04-08', carrier: 'CentraAsia' },
  ];

  const statusBadges: Record<string, 'default' | 'secondary' | 'outline'> = {
    'in_transit': 'secondary',
    'customs': 'outline',
    'delivered': 'default',
  };

  return (
    <PageShell
      title={t('pages.logistics.title')}
      description={t('pages.logistics.description')}
      icon={<Truck className="h-5 w-5" />}
      stats={[
        { label: t('pages.logistics.stats.inTransit'), value: '3' },
        { label: t('pages.logistics.stats.customs'), value: '1' },
        { label: t('pages.logistics.stats.delivered'), value: '1' },
        { label: t('pages.logistics.stats.delays'), value: '0' },
      ]}
      actions={[{ label: t('pages.logistics.newShipment') }]}
    >
      <div className="space-y-3">
        {shipments.map((ship, idx) => (
          <Card key={idx}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <p className="font-semibold">{ship.number}</p>
                    <Badge variant={statusBadges[ship.status]} className="gap-1">
                      {ship.status === 'in_transit' && <><Truck className="h-3 w-3" /> {t('pages.logistics.statusLabel.inTransit')}</>}
                      {ship.status === 'customs' && <><FileText className="h-3 w-3" /> {t('pages.logistics.statusLabel.customs')}</>}
                      {ship.status === 'delivered' && <><CheckCircle2 className="h-3 w-3" /> {t('pages.logistics.statusLabel.delivered')}</>}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mb-3 flex items-center gap-2">
                    <MapPin className="h-4 w-4" />
                    {ship.route}
                  </p>
                  <div className="grid grid-cols-3 gap-4 text-xs">
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.departure')}</p>
                      <p className="font-medium">{ship.etd}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.arrival')}</p>
                      <p className="font-medium">{ship.eta}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.carrier')}</p>
                      <p className="font-medium">{ship.carrier}</p>
                    </div>
                  </div>
                </div>
                <Button variant="ghost" size="sm">
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

// ─── Admin Users Page ──────────────────────────────────────────────────

export function AdminUsersPage() {
  const { t } = useTranslation();
  const users = [
    { name: 'Азиз Қодиров', email: 'aziz.kodirov@railtech.uz', role: 'admin', roleLabel: t('pages.adminUsers.roles.admin'), status: 'active', lastLogin: '2026-03-20 14:30' },
    { name: 'Диана Рахимова', email: 'diana.rahimova@railtech.uz', role: 'manager', roleLabel: t('pages.adminUsers.roles.salesManager'), status: 'active', lastLogin: '2026-03-20 13:45' },
    { name: 'Фарход Махмудов', email: 'farhod.mahmudov@railtech.uz', role: 'manager', roleLabel: t('pages.adminUsers.roles.salesManager'), status: 'active', lastLogin: '2026-03-19 16:20' },
    { name: 'Лола Искандарова', email: 'lola.iskandarova@railtech.uz', role: 'admin', roleLabel: t('pages.adminUsers.roles.admin'), status: 'active', lastLogin: '2026-03-20 15:10' },
    { name: 'Умид Абдуллаев', email: 'umid.abdullaev@railtech.uz', role: 'employee', roleLabel: t('pages.adminUsers.roles.employee'), status: 'active', lastLogin: '2026-03-18 09:15' },
    { name: 'Наталья Петрова', email: 'natalia.petrova@railtech.uz', role: 'manager', roleLabel: t('pages.adminUsers.roles.salesManager'), status: 'inactive', lastLogin: '2026-03-10 11:45' },
    { name: 'Камол Зарифов', email: 'kamol.zarifov@railtech.uz', role: 'employee', roleLabel: t('pages.adminUsers.roles.employee'), status: 'active', lastLogin: '2026-03-20 10:20' },
    { name: 'Евгений Смирнов', email: 'evgeny.smirnov@railtech.uz', role: 'employee', roleLabel: t('pages.adminUsers.roles.employee'), status: 'active', lastLogin: '2026-03-17 14:50' },
  ];

  return (
    <PageShell
      title={t('pages.adminUsers.title')}
      description={t('pages.adminUsers.description')}
      icon={<Shield className="h-5 w-5" />}
      stats={[
        { label: t('pages.adminUsers.stats.total'), value: '8' },
        { label: t('pages.adminUsers.stats.admins'), value: '2' },
        { label: t('pages.adminUsers.stats.managers'), value: '3' },
        { label: t('pages.adminUsers.stats.employees'), value: '3' },
      ]}
      actions={[{ label: t('pages.adminUsers.inviteUser') }]}
    >
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium">{t('pages.adminUsers.table.name')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.adminUsers.table.email')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.adminUsers.table.role')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.adminUsers.table.status')}</th>
                  <th className="px-4 py-3 text-left font-medium">{t('pages.adminUsers.table.lastLogin')}</th>
                  <th className="px-4 py-3 text-center font-medium">{t('pages.adminUsers.table.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user, idx) => (
                  <tr key={idx} className="border-b hover:bg-muted/50">
                    <td className="px-4 py-3 font-medium">{user.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{user.email}</td>
                    <td className="px-4 py-3">
                      <Badge variant={
                        user.role === 'admin' ? 'default' :
                        user.role === 'manager' ? 'secondary' :
                        'outline'
                      }>
                        {user.roleLabel}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={user.status === 'active' ? 'default' : 'secondary'} className="gap-1">
                        {user.status === 'active' ? <><Check className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.active')}</> : <><Pause className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.inactive')}</>}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs">{user.lastLogin}</td>
                    <td className="px-4 py-3 text-center">
                      <Button variant="ghost" size="sm" className="h-8 w-8">
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}
