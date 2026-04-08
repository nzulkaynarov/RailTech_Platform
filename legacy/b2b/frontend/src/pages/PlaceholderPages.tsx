import {
  ShoppingCart, FileText, Factory, BarChart3, Upload, Search, Plug,
  HelpCircle, ClipboardList, Calculator, Users, CalendarDays,
  Layers, Tags, Truck, Shield, ChevronRight, FileSpreadsheet,
  Clock, CheckCircle2, Star, Pause, Check,
  // Zap, Flame, Package, UserRound — removed (were used by hardcoded equipment groups)
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
import { usePageStats } from '@/hooks/usePageStats';
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
                {t(requestStatusLabels[request.status])}
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
  const { data: ps } = usePageStats();
  const s = ps?.sourcing;
  return (
    <PageShell
      title={t('pages.sourcingRequests.title')}
      description={t('pages.sourcingRequests.description')}
      icon={<ClipboardList className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingRequests.stats.total'), value: String(s?.total ?? '—') },
        { label: t('pages.sourcingRequests.stats.new'), value: String(s?.new ?? '—') },
        { label: t('pages.sourcingRequests.stats.inProgress'), value: String(s?.in_progress ?? '—') },
        { label: t('pages.sourcingRequests.stats.completed'), value: String(s?.completed ?? '—') },
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
                <p className="font-medium">{t('pages.sourcingImport.sampleFileName')}</p>
                <p className="text-sm text-muted-foreground">{t('pages.sourcingImport.uploadedAgo')}</p>
              </div>
              <Badge>{t('pages.sourcingImport.status.completed')}</Badge>
            </div>

            {/* Import results will be displayed here after actual file upload */}
            <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
              <Upload className="h-8 w-8 mb-3 opacity-50" />
              <p className="text-sm font-medium">{t('pages.sourcingImport.noImportsYet')}</p>
              <p className="text-xs mt-1">{t('pages.sourcingImport.uploadToSee')}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

export function SourcingMatchPage() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();
  const s = ps?.sourcing_match;
  return (
    <PageShell
      title={t('pages.sourcingMatch.title')}
      description={t('pages.sourcingMatch.description')}
      icon={<Search className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingMatch.stats.unrecognized'), value: String(s?.unrecognized ?? '—') },
        { label: t('pages.sourcingMatch.stats.matches'), value: String(s?.matches ?? '—') },
        { label: t('pages.sourcingMatch.stats.needReview'), value: String(s?.need_review ?? '—') },
        { label: t('pages.sourcingMatch.stats.accuracy'), value: s?.accuracy ?? '—' },
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
  const { data: ps } = usePageStats();
  // TODO: Replace with useDeals() hook and group by stage_code
  const columns: DealColumn[] = [
    { title: 'DRAFT', stage: t('pages.deals.stages.draft'), deals: [] },
    { title: 'SOURCING', stage: t('pages.deals.stages.sourcing'), deals: [] },
    { title: 'CALCULATING', stage: t('pages.deals.stages.calculating'), deals: [] },
    { title: 'QUOTE_SENT', stage: t('pages.deals.stages.quoteSent'), deals: [] },
    { title: 'CONTRACT_SIGNED', stage: t('pages.deals.stages.contractSigned'), deals: [] },
    { title: 'CLOSED_WON', stage: t('pages.deals.stages.closedWon'), deals: [] },
    { title: 'CLOSED_LOST', stage: t('pages.deals.stages.closedLost'), deals: [] },
  ];

  return (
    <PageShell
      title={t('pages.deals.title')}
      description={t('pages.deals.description')}
      icon={<FileText className="h-5 w-5" />}
      stats={[
        { label: t('pages.deals.stats.total'), value: String(ps?.deals?.total ?? '—') },
        { label: t('pages.deals.stats.active'), value: String(ps?.deals?.active ?? '—') },
        { label: t('pages.deals.stats.quoteSent'), value: String(ps?.deals?.quote_sent ?? '—') },
        { label: t('pages.deals.stats.closedWon'), value: String(ps?.deals?.closed_won ?? '—') },
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
  const { data: ps } = usePageStats();
  const isBuyer = activeStatus === 'BUYER';

  // Quotes are loaded from the backend API via crmApi
  // TODO: Replace with useEffect + crmApi.getQuotes() when component mounts
  const sellerQuotes: { number: string; client: string; items: number; amount: number; margin: number; status: string; statusLabel: string; date: string }[] = [];
  const buyerQuotes: { number: string; seller: string; items: number; amount: number; status: string; statusLabel: string; date: string; deadline: string }[] = [];

  if (isBuyer) {
    return (
      <PageShell
        title={t('pages.quotes.buyerTitle')}
        description={t('pages.quotes.buyerDescription')}
        icon={<Calculator className="h-5 w-5" />}
        stats={[
          { label: t('pages.quotes.stats.total'), value: String(buyerQuotes.length) },
          { label: t('pages.quotes.stats.underReview'), value: String(ps?.quotes?.under_review ?? '—') },
          { label: t('pages.quotes.stats.accepted'), value: String(ps?.quotes?.approved ?? '—') },
          { label: t('pages.quotes.stats.totalAmount'), value: ps?.quotes?.total_amount ?? '—' },
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
        { label: t('pages.quotes.stats.drafts'), value: String(ps?.quotes?.drafts ?? '—') },
        { label: t('pages.quotes.stats.sent'), value: String(ps?.quotes?.sent ?? '—') },
        { label: t('pages.quotes.stats.approved'), value: String(ps?.quotes?.approved ?? '—') },
        { label: t('pages.quotes.stats.pipeline'), value: ps?.quotes?.pipeline ?? '—' },
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Clients are loaded from the backend API via accountsApi
  // TODO: Replace with useEffect + accountsApi.getCompanies() when component mounts
  const clients: { name: string; inn: string; status: string; kyc: string; deals: number; lastActivity: string }[] = [];

  return (
    <PageShell
      title={t('pages.clients.title')}
      description={t('pages.clients.description')}
      icon={<Users className="h-5 w-5" />}
      stats={[
        { label: t('pages.clients.stats.total'), value: String(ps?.clients?.total ?? '—') },
        { label: t('pages.clients.stats.verified'), value: String(ps?.clients?.verified ?? '—') },
        { label: t('pages.clients.stats.awaitingKyc'), value: String(ps?.clients?.awaiting_kyc ?? '—') },
        { label: t('pages.clients.stats.guests'), value: String(ps?.clients?.unverified ?? '—') },
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.productionOrders.title')}
      description={t('pages.productionOrders.description')}
      icon={<Factory className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionOrders.stats.active'), value: String(ps?.production?.active ?? '0') },
        { label: t('pages.productionOrders.stats.awaitingResponse'), value: String(ps?.production?.awaiting_response ?? '0') },
        { label: t('pages.productionOrders.stats.responded'), value: String(ps?.production?.responded ?? '0') },
        { label: t('pages.productionOrders.stats.overdue'), value: String(ps?.production?.overdue ?? '0') },
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Production orders are loaded from the backend API
  // TODO: Replace with useEffect + API call when production endpoints are ready
  const orders: { name: string; progress: number; deadline: string; status: string }[] = [];

  return (
    <PageShell
      title={t('pages.productionSchedule.title')}
      description={t('pages.productionSchedule.description')}
      icon={<CalendarDays className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionSchedule.stats.activeOrders'), value: String(ps?.production_schedule?.active_orders ?? '0') },
        { label: t('pages.productionSchedule.stats.completed'), value: String(ps?.production_schedule?.completed ?? '0') },
        { label: t('pages.productionSchedule.stats.delayed'), value: String(ps?.production_schedule?.delayed ?? '0') },
        { label: t('pages.productionSchedule.stats.nextWeek'), value: String(ps?.production_schedule?.next_week ?? '0') },
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();

  if (activeStatus === 'BUYER') {
    return <BuyerAnalytics />;
  }

  // Seller / Manufacturer analytics
  // Analytics data loaded from the backend API via crmApi.getAnalytics()
  // TODO: Replace with useEffect + API call
  const funnelData: { stage: string; value: number }[] = [];
  const revenueData: { month: string; revenue: number }[] = [];

  const colors = ['var(--color-chart-1)', 'var(--color-chart-2)', 'var(--color-chart-5)', 'var(--color-chart-4)'];

  return (
    <PageShell
      title={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerTitle') : t('pages.analytics.sellerTitle')}
      description={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerDescription') : t('pages.analytics.sellerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.stats.conversion'), value: ps?.analytics?.conversion ?? '—' },
        { label: t('pages.analytics.stats.avgDeal'), value: ps?.analytics?.avg_deal ?? '—' },
        { label: t('pages.analytics.stats.pipeline'), value: ps?.analytics?.pipeline ?? '—' },
        { label: t('pages.analytics.stats.winRate'), value: ps?.analytics?.win_rate ?? '—' },
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
  const { data: ps } = usePageStats();
  // Buyer analytics data loaded from the backend API
  // TODO: Replace with useEffect + API call when buyer analytics endpoint is ready
  const spendData: { month: string; spend: number }[] = [];
  const categoryData: { name: string; value: number; color: string }[] = [];
  const suppliers: { name: string; orders: number; total: string; avgDelivery: string; rating: number }[] = [];

  return (
    <PageShell
      title={t('pages.analytics.buyerTitle')}
      description={t('pages.analytics.buyerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.buyerStats.spendPeriod'), value: ps?.analytics_buyer?.spend_period ?? '—' },
        { label: t('pages.analytics.buyerStats.savings'), value: ps?.analytics_buyer?.savings ?? '—' },
        { label: t('pages.analytics.buyerStats.activeRequests'), value: String(ps?.analytics_buyer?.active_requests ?? '—') },
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
  // Categories are loaded from the backend API via catalogApi.getCategories()
  // TODO: Replace with useEffect + catalogApi.getCategories()
  const categories: { name: string; subcats: { name: string; items: string[] }[] }[] = [];

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
                  <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                    <div className="flex items-center gap-2">
                      <ChevronDown className="h-4 w-4 transition-transform" />
                      <span className="font-medium">{cat.name}</span>
                    </div>
                    <Badge variant="outline" className="text-xs">{cat.subcats.reduce((sum, s) => sum + s.items.length, 0)} {t('pages.common.items')}</Badge>
                  </Button>
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
  // Equipment groups loaded from the backend API via catalogApi.getEquipmentGroups()
  // TODO: Replace with useEffect + catalogApi.getEquipmentGroups()
  const groups: { name: string; icon: React.ReactNode; series: number; components: number }[] = [];

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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Integrations are loaded from the backend API
  // TODO: Replace with useEffect + API call when integrations endpoint is ready
  const integrations: { name: string; description: string; status: string; lastSync: string; records: string }[] = [];

  return (
    <PageShell
      title={t('pages.integrations.title')}
      description={t('pages.integrations.description')}
      icon={<Plug className="h-5 w-5" />}
      stats={[
        { label: t('pages.integrations.stats.connected'), value: String(ps?.integrations?.connected ?? '0') },
        { label: t('pages.integrations.stats.pending'), value: String(ps?.integrations?.pending ?? '0') },
        { label: t('pages.integrations.stats.availableApis'), value: String(ps?.integrations?.available_apis ?? '0') },
        { label: t('pages.integrations.stats.syncedRecords'), value: String(ps?.integrations?.synced_records ?? '0') },
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
                          <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                            <span className="font-medium text-sm text-left">{faq.question}</span>
                            <ChevronDown className="h-4 w-4 transition-transform flex-shrink-0 ml-2" />
                          </Button>
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={[
        { label: t('pages.myRequests.stats.active'), value: String(ps?.my_requests?.active ?? '—') },
        { label: t('pages.myRequests.stats.quoteReceived'), value: String(ps?.my_requests?.quote_received ?? '—') },
        { label: t('pages.myRequests.stats.contract'), value: String(ps?.my_requests?.contract ?? '—') },
        { label: t('pages.myRequests.stats.completed'), value: String(ps?.my_requests?.completed ?? '—') },
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
  // Documents are loaded from the backend API
  // TODO: Replace with useEffect + API call when documents endpoint is ready
  const documents: { type: string; number: string; date: string; counterparty: string; status: string; statusLabel: string; amount: string }[] = [];

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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Shipments are loaded from the backend API
  // TODO: Replace with useEffect + API call when logistics endpoint is ready
  const shipments: { number: string; route: string; status: string; etd: string; eta: string; carrier: string }[] = [];

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
        { label: t('pages.logistics.stats.inTransit'), value: String(ps?.logistics?.in_transit ?? '0') },
        { label: t('pages.logistics.stats.customs'), value: String(ps?.logistics?.customs ?? '0') },
        { label: t('pages.logistics.stats.delivered'), value: String(ps?.logistics?.delivered ?? '0') },
        { label: t('pages.logistics.stats.delays'), value: String(ps?.logistics?.delays ?? '0') },
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
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Users are loaded from the backend API via accountsApi
  // TODO: Replace with useEffect + accountsApi.getUsers() when endpoint is ready
  const users: { name: string; email: string; role: string; roleLabel: string; status: string; lastLogin: string }[] = [];

  return (
    <PageShell
      title={t('pages.adminUsers.title')}
      description={t('pages.adminUsers.description')}
      icon={<Shield className="h-5 w-5" />}
      stats={[
        { label: t('pages.adminUsers.stats.total'), value: String(ps?.admin_users?.total ?? '—') },
        { label: t('pages.adminUsers.stats.admins'), value: String(ps?.admin_users?.admins ?? '—') },
        { label: t('pages.adminUsers.stats.managers'), value: String(ps?.admin_users?.managers ?? '—') },
        { label: t('pages.adminUsers.stats.employees'), value: String(ps?.admin_users?.employees ?? '—') },
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
