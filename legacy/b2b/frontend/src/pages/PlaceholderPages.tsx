import {
  ShoppingCart, FileText, Factory, BarChart3, Upload, Search, Plug,
  HelpCircle, ClipboardList, Calculator, Users, CalendarDays,
  Layers, Tags, Truck, Shield, ChevronRight, FileSpreadsheet,
  Clock, CheckCircle2, Pause, Check,
  ChevronDown, Download, MapPin, Calendar,
  Mail, MessageSquare, MoreHorizontal, Send, ThumbsUp, ThumbsDown, FileDown,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useFlowStore, requestStatusLabels, requestStatusColors } from '@/store/flowStore';
import { useUserStore } from '@/store/userStore';
import { usePageStats } from '@/hooks/usePageStats';
import { Progress } from '@/components/ui/progress';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';
import { useDeals, useAnalytics, useQuotes, useSendQuoteToClient, useApproveQuote } from '@/hooks/useCRM';
import { useCompanies, useUsers } from '@/hooks/useAccounts';
import { useCategories, useEquipmentGroups } from '@/hooks/useCatalog';
import { crmApi } from '@/api/crmApi';
import type { Deal, Quote } from '@/api/crmApi';
import { toast } from 'sonner';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { Company, User } from '@/api/accountsApi';
import type { Category, EquipmentGroup } from '@/api/catalogApi';

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

/* ─── Loading / Empty helpers ──────────────────────────────────────── */

function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

function EmptyState({ icon, message }: { icon: React.ReactNode; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
      <p className="text-sm font-medium">{message}</p>
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
  const { data: deals, isLoading } = useDeals();
  const s = ps?.sourcing;

  const sourcingDeals = (deals ?? []).filter((d: Deal) =>
    d.stage_code === 'SOURCING' || d.stage_code === 'CALCULATING' || d.stage_code === 'DRAFT'
  );

  return (
    <PageShell
      title={t('pages.sourcingRequests.title')}
      description={t('pages.sourcingRequests.description')}
      icon={<ClipboardList className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingRequests.stats.total'), value: String(s?.total ?? sourcingDeals.length) },
        { label: t('pages.sourcingRequests.stats.new'), value: String(s?.new ?? '—') },
        { label: t('pages.sourcingRequests.stats.inProgress'), value: String(s?.in_progress ?? '—') },
        { label: t('pages.sourcingRequests.stats.completed'), value: String(s?.completed ?? '—') },
      ]}
      actions={[{ label: t('pages.sourcingRequests.createRequest'), onClick: () => onNavigate?.('catalog') }]}
    >
      {isLoading ? <LoadingRows rows={3} /> : sourcingDeals.length === 0 ? (
        <EmptyState icon={<ClipboardList className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="space-y-2">
          {sourcingDeals.map((deal: Deal) => (
            <Card key={deal.id} className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0">
              <CardContent className="px-4 py-4">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <FileSpreadsheet className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{deal.title ?? `#${deal.id}`}</span>
                      <Badge variant="outline" className="text-xs">{deal.stage_name}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {deal.client_name ?? deal.company_name ?? '—'} · {new Date(deal.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <p className="text-sm font-bold text-primary tabular-nums">{deal.total_value ? `$${Number(deal.total_value).toLocaleString()}` : '—'}</p>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
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

export function DealsPage() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();
  const { data: deals, isLoading } = useDeals();

  const stageOrder = ['DRAFT', 'KYC_PENDING', 'SOURCING', 'CALCULATING', 'QUOTE_SENT', 'CONTRACT_SIGNED', 'CLOSED_WON', 'CLOSED_LOST'];
  const stageLabels: Record<string, string> = {
    DRAFT: t('pages.deals.stages.draft'),
    KYC_PENDING: t('pages.deals.stages.kycPending'),
    SOURCING: t('pages.deals.stages.sourcing'),
    CALCULATING: t('pages.deals.stages.calculating'),
    QUOTE_SENT: t('pages.deals.stages.quoteSent'),
    CONTRACT_SIGNED: t('pages.deals.stages.contractSigned'),
    CLOSED_WON: t('pages.deals.stages.closedWon'),
    CLOSED_LOST: t('pages.deals.stages.closedLost'),
  };

  const grouped = stageOrder.map((code) => ({
    code,
    label: stageLabels[code] ?? code,
    deals: (deals ?? []).filter((d: Deal) => d.stage_code === code),
  }));

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
      {isLoading ? <LoadingRows rows={4} /> : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-4 min-w-max">
            {grouped.map((column) => (
              <div key={column.code} className="flex-shrink-0 w-80">
                <div className={cn('rounded-lg p-4 space-y-3 bg-muted')}>
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-sm">{column.label}</h3>
                    <Badge variant="outline" className="text-xs">{column.deals.length}</Badge>
                  </div>
                  <div className="space-y-3">
                    {column.deals.length === 0 && (
                      <p className="text-xs text-muted-foreground text-center py-4">{t('pages.common.noData')}</p>
                    )}
                    {column.deals.map((deal: Deal) => (
                      <Card key={deal.id} className="cursor-pointer hover:shadow-md transition-shadow">
                        <CardContent className="p-3 space-y-2">
                          <div>
                            <p className="font-medium text-sm">{deal.title ?? `#${deal.id}`}</p>
                            <p className="text-xs text-muted-foreground">{deal.client_name ?? deal.company_name ?? '—'}</p>
                          </div>
                          <div className="flex items-center justify-between">
                            <p className="text-lg font-bold text-primary">{deal.total_value ? `$${Number(deal.total_value).toLocaleString()}` : '—'}</p>
                            <Badge variant="secondary" className="text-xs">{deal.stage_name}</Badge>
                          </div>
                          <p className="text-xs text-muted-foreground flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {new Date(deal.created_at).toLocaleDateString()}
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
      )}
    </PageShell>
  );
}

export function QuotesPage() {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const { data: ps } = usePageStats();
  const { data: quotes, isLoading } = useQuotes();
  const sendToClient = useSendQuoteToClient();
  const approveQuote = useApproveQuote();
  const isBuyer = activeStatus === 'BUYER';

  const quotesList = quotes ?? [];

  const title = isBuyer ? t('pages.quotes.buyerTitle') : t('pages.quotes.sellerTitle');
  const description = isBuyer ? t('pages.quotes.buyerDescription') : t('pages.quotes.sellerDescription');
  const stats = isBuyer
    ? [
        { label: t('pages.quotes.stats.total'), value: String(quotesList.length) },
        { label: t('pages.quotes.stats.underReview'), value: String(ps?.quotes?.under_review ?? '—') },
        { label: t('pages.quotes.stats.accepted'), value: String(ps?.quotes?.approved ?? '—') },
        { label: t('pages.quotes.stats.totalAmount'), value: ps?.quotes?.total_amount ?? '—' },
      ]
    : [
        { label: t('pages.quotes.stats.drafts'), value: String(ps?.quotes?.drafts ?? '—') },
        { label: t('pages.quotes.stats.sent'), value: String(ps?.quotes?.sent ?? '—') },
        { label: t('pages.quotes.stats.approved'), value: String(ps?.quotes?.approved ?? '—') },
        { label: t('pages.quotes.stats.pipeline'), value: ps?.quotes?.pipeline ?? '—' },
      ];

  const handleSendToClient = async (id: number) => {
    try {
      await sendToClient.mutateAsync(id);
      toast.success(t('pages.quotes.toast.sentSuccess', { id }));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleApprove = async (id: number) => {
    try {
      await approveQuote.mutateAsync(id);
      toast.success(t('pages.quotes.toast.approvedSuccess', { id }));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleReject = async (id: number) => {
    try {
      await crmApi.rejectQuote(id);
      toast.success(t('pages.quotes.toast.rejectedSuccess', { id }));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleDownloadPDF = async (id: number) => {
    try {
      await crmApi.downloadQuotePDF(id);
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleGeneratePDF = async (id: number) => {
    try {
      await crmApi.generateQuotePDF(id);
      toast.success(t('pages.quotes.toast.pdfGenerated'));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const getStatusBadgeVariant = (statusName: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
    const lower = statusName.toLowerCase();
    if (lower.includes('approved') || lower.includes('согласов')) return 'default';
    if (lower.includes('sent') || lower.includes('отправлен')) return 'secondary';
    if (lower.includes('reject') || lower.includes('отклон')) return 'destructive';
    return 'outline';
  };

  return (
    <PageShell
      title={title}
      description={description}
      icon={<Calculator className="h-5 w-5" />}
      stats={stats}
      actions={isBuyer ? undefined : [{ label: t('pages.quotes.createQuote') }]}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : quotesList.length === 0 ? (
            <EmptyState icon={<Calculator className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.number')}</th>
                    <th className="px-4 py-3 text-left font-medium">{isBuyer ? t('pages.quotes.table.supplier') : t('pages.quotes.table.client')}</th>
                    <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.items')}</th>
                    <th className="px-4 py-3 text-right font-medium">{t('pages.quotes.table.amount')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.status')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.quotes.table.date')}</th>
                    <th className="px-4 py-3 text-center font-medium">{t('pages.quotes.table.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {quotesList.map((q: Quote) => (
                    <tr key={q.id} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium">#{q.id}-v{q.version}</td>
                      <td className="px-4 py-3">{t('pages.quotes.dealRef', { id: q.deal })}</td>
                      <td className="px-4 py-3 text-center tabular-nums">{q.items?.length ?? 0}</td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium">${Number(q.total_incl_vat).toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <Badge variant={getStatusBadgeVariant(q.status_name)}>
                          {q.status_name}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{new Date(q.created_at).toLocaleDateString()}</td>
                      <td className="px-4 py-3 text-center">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {!isBuyer && (
                              <>
                                <DropdownMenuItem onClick={() => handleSendToClient(q.id)}>
                                  <Send className="mr-2 h-4 w-4" />
                                  {t('pages.quotes.actions.sendToClient')}
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleGeneratePDF(q.id)}>
                                  <FileText className="mr-2 h-4 w-4" />
                                  {t('pages.quotes.actions.generatePDF')}
                                </DropdownMenuItem>
                              </>
                            )}
                            {isBuyer && (
                              <>
                                <DropdownMenuItem onClick={() => handleApprove(q.id)}>
                                  <ThumbsUp className="mr-2 h-4 w-4" />
                                  {t('pages.quotes.actions.approve')}
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleReject(q.id)}>
                                  <ThumbsDown className="mr-2 h-4 w-4" />
                                  {t('pages.quotes.actions.reject')}
                                </DropdownMenuItem>
                              </>
                            )}
                            <DropdownMenuItem onClick={() => handleDownloadPDF(q.id)}>
                              <FileDown className="mr-2 h-4 w-4" />
                              {t('pages.quotes.actions.downloadPDF')}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export function ClientsPage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  const { data: companies, isLoading } = useCompanies();

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
          {isLoading ? <LoadingRows rows={5} /> : !companies?.length ? (
            <EmptyState icon={<Users className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.company')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.inn')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.kyc')}</th>
                    <th className="px-4 py-3 text-center font-medium">{t('pages.clients.table.deals')}</th>
                    <th className="px-4 py-3 text-left font-medium">{t('pages.clients.table.lastActivity')}</th>
                  </tr>
                </thead>
                <tbody>
                  {companies.map((company: Company) => (
                    <tr key={company.id} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium">{company.name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{company.inn}</td>
                      <td className="px-4 py-3">
                        <Badge variant={company.verification_status === 'VERIFIED' ? 'default' : 'secondary'} className="gap-1">
                          {company.verification_status === 'VERIFIED'
                            ? <><Check className="h-3 w-3" /> {t('pages.clients.kycStatus.verified')}</>
                            : <><Clock className="h-3 w-3" /> {t('pages.clients.kycStatus.pending')}</>}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center tabular-nums">{company.user_count ?? 0}</td>
                      <td className="px-4 py-3 text-muted-foreground">{company.created_at ? new Date(company.created_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
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
  const { data: analytics, isLoading } = useAnalytics();

  if (activeStatus === 'BUYER') {
    return <BuyerAnalytics />;
  }

  const funnelData = (analytics?.pipeline_by_status ?? []).map((item) => ({
    stage: item.stage__name,
    value: item.count,
  }));
  const maxFunnel = Math.max(...funnelData.map((d) => d.value), 1);

  const colors = ['var(--color-chart-1)', 'var(--color-chart-2)', 'var(--color-chart-5)', 'var(--color-chart-4)', 'var(--color-chart-3)'];

  return (
    <PageShell
      title={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerTitle') : t('pages.analytics.sellerTitle')}
      description={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerDescription') : t('pages.analytics.sellerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.stats.conversion'), value: analytics?.conversion_rate != null ? `${analytics.conversion_rate.toFixed(1)}%` : (ps?.analytics?.conversion ?? '—') },
        { label: t('pages.analytics.stats.avgDeal'), value: analytics?.avg_margin != null ? `${analytics.avg_margin.toFixed(1)}%` : (ps?.analytics?.avg_deal ?? '—') },
        { label: t('pages.analytics.stats.pipeline'), value: analytics?.total_pipeline_value != null ? `$${analytics.total_pipeline_value.toLocaleString()}` : (ps?.analytics?.pipeline ?? '—') },
        { label: t('pages.analytics.stats.winRate'), value: ps?.analytics?.win_rate ?? '—' },
      ]}
    >
      {isLoading ? <LoadingRows rows={4} /> : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('pages.analytics.conversionFunnel')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {funnelData.length === 0 ? (
                <EmptyState icon={<BarChart3 className="h-5 w-5" />} message={t('pages.common.noData')} />
              ) : funnelData.map((item, idx) => {
                const percentage = (item.value / maxFunnel) * 100;
                return (
                  <div key={idx} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{item.stage}</span>
                      <span className="text-muted-foreground">{item.value}</span>
                    </div>
                    <div className="h-8 rounded-full overflow-hidden bg-muted">
                      <div
                        className="h-full rounded-full flex items-center justify-end pr-2 text-xs font-medium text-primary-foreground"
                        style={{ width: `${Math.max(percentage, 5)}%`, backgroundColor: colors[idx % colors.length] }}
                      >
                        {percentage > 20 && item.value}
                      </div>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('pages.analytics.keyMetrics')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.sourcingBacklog')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.sourcing_backlog ?? 0}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.kycBacklog')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.kyc_backlog ?? 0}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.mappedItems')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.mapped_items_percentage != null ? `${analytics.mapped_items_percentage.toFixed(0)}%` : '—'}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.sourcingSpeed')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.sourcing_speed_avg != null ? `${analytics.sourcing_speed_avg.toFixed(1)}h` : '—'}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </PageShell>
  );
}

function BuyerAnalytics() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();

  return (
    <PageShell
      title={t('pages.analytics.buyerTitle')}
      description={t('pages.analytics.buyerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.buyerStats.spendPeriod'), value: ps?.analytics_buyer?.spend_period ?? '—' },
        { label: t('pages.analytics.buyerStats.savings'), value: ps?.analytics_buyer?.savings ?? '—' },
        { label: t('pages.analytics.buyerStats.activeRequests'), value: String(ps?.analytics_buyer?.active_requests ?? '—') },
        { label: t('pages.analytics.buyerStats.avgDelivery'), value: '—' },
      ]}
    >
      <EmptyState icon={<BarChart3 className="h-5 w-5" />} message={t('pages.common.sectionInDevelopment')} />
    </PageShell>
  );
}

// ─── Catalog Sub-pages ──────────────────────────────────────────────────

export function CategoriesPage() {
  const { t } = useTranslation();
  const { data: categories, isLoading } = useCategories();

  const topLevel = (categories ?? []).filter((c: Category) => !c.parent);
  const getChildren = (parentId: number) => (categories ?? []).filter((c: Category) => c.parent === parentId);

  return (
    <PageShell
      title={t('pages.categories.title')}
      description={t('pages.categories.description')}
      icon={<Tags className="h-5 w-5" />}
      actions={[{ label: t('pages.categories.addCategory') }]}
    >
      {isLoading ? <LoadingRows rows={4} /> : topLevel.length === 0 ? (
        <EmptyState icon={<Tags className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="space-y-2">
          {topLevel.map((cat: Category, idx: number) => {
            const children = getChildren(cat.id);
            return (
              <Collapsible key={cat.id} defaultOpen={idx === 0}>
                <Card className="border">
                  <CardContent className="p-0">
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                        <div className="flex items-center gap-2">
                          <ChevronDown className="h-4 w-4 transition-transform" />
                          <span className="font-medium">{cat.name}</span>
                        </div>
                        <Badge variant="outline" className="text-xs">{children.length} {t('pages.common.items')}</Badge>
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="border-t bg-muted/30 p-4">
                        {children.length === 0 ? (
                          <p className="text-xs text-muted-foreground ml-4">{t('pages.common.noData')}</p>
                        ) : (
                          <div className="flex flex-wrap gap-2 ml-4">
                            {children.map((child: Category) => (
                              <Badge key={child.id} variant="secondary" className="text-xs">{child.name}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </CardContent>
                </Card>
              </Collapsible>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

export function EquipmentGroupsPage() {
  const { t } = useTranslation();
  const { data: groups, isLoading } = useEquipmentGroups();

  return (
    <PageShell
      title={t('pages.equipmentGroups.title')}
      description={t('pages.equipmentGroups.description')}
      icon={<Layers className="h-5 w-5" />}
      actions={[{ label: t('pages.equipmentGroups.addGroup') }]}
    >
      {isLoading ? <LoadingRows rows={4} /> : !groups?.length ? (
        <EmptyState icon={<Layers className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {groups.map((group: EquipmentGroup) => (
            <Card key={group.id} className="cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Layers className="h-6 w-6" />
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground" />
                </div>
                <h3 className="font-semibold text-lg mb-3">{group.name}</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">{t('pages.equipmentGroups.type')}</p>
                    <p className="text-sm font-medium">{group.equipment_type || '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">{t('pages.equipmentGroups.series')}</p>
                    <p className="text-sm font-medium">{group.series || '—'}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
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
  const { data: deals, isLoading } = useDeals();

  const myDeals = deals ?? [];

  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={[
        { label: t('pages.myRequests.stats.active'), value: String(ps?.my_requests?.active ?? myDeals.filter((d: Deal) => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? '')).length) },
        { label: t('pages.myRequests.stats.quoteReceived'), value: String(ps?.my_requests?.quote_received ?? myDeals.filter((d: Deal) => d.stage_code === 'QUOTE_SENT').length) },
        { label: t('pages.myRequests.stats.contract'), value: String(ps?.my_requests?.contract ?? myDeals.filter((d: Deal) => d.stage_code === 'CONTRACT_SIGNED').length) },
        { label: t('pages.myRequests.stats.completed'), value: String(ps?.my_requests?.completed ?? myDeals.filter((d: Deal) => d.stage_code === 'CLOSED_WON').length) },
      ]}
      actions={[{ label: t('pages.myRequests.newRequest'), onClick: () => onNavigate?.('catalog') }]}
    >
      {isLoading ? <LoadingRows rows={3} /> : myDeals.length === 0 ? (
        <EmptyState icon={<ShoppingCart className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="space-y-2">
          {myDeals.map((deal: Deal) => (
            <Card key={deal.id} className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0">
              <CardContent className="px-4 py-4">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <FileText className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{deal.title ?? `${t('pages.myRequests.deal')} #${deal.id}`}</span>
                      <Badge variant="outline" className="text-xs">{deal.stage_name}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {deal.company_name ?? '—'} · {new Date(deal.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <p className="text-sm font-bold text-primary tabular-nums">{deal.total_value ? `$${Number(deal.total_value).toLocaleString()}` : '—'}</p>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
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
  const { data: users, isLoading } = useUsers();

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
          {isLoading ? <LoadingRows rows={5} /> : !users?.length ? (
            <EmptyState icon={<Shield className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
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
                  {users.map((user: User) => (
                    <tr key={user.id} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium">{user.first_name} {user.last_name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{user.email}</td>
                      <td className="px-4 py-3">
                        <Badge variant={
                          user.role_code === 'ADMIN' ? 'default' :
                          user.role_code === 'MANAGER' ? 'secondary' :
                          'outline'
                        }>
                          {user.role_data?.name ?? user.role_code ?? '—'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={user.is_active ? 'default' : 'secondary'} className="gap-1">
                          {user.is_active
                            ? <><Check className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.active')}</>
                            : <><Pause className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.inactive')}</>}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{user.last_login ? new Date(user.last_login).toLocaleDateString() : '—'}</td>
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
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
