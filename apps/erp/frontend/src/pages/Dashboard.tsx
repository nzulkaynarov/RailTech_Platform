import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  FileText,
  FileSignature,
  Receipt,
  ClipboardCheck,
  FileType,
  Calendar,
  AlertCircle,
  Loader2,
  Clock,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { formatDate } from '@/lib/formatLocale';
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
import { OnboardingChecklist } from '@/components/Shared/OnboardingChecklist';
import { QuoteApprovalQueue } from '@/components/CRM/QuoteApprovalQueue';
import {
  AttentionStrip, PostContractStrip, PipelineFunnel, MetricStrip,
} from '@/components/Dashboard/DashboardWidgets';

import { useTranslation } from 'react-i18next';
import { documentRoute } from '@/lib/documentRoute';
import { documentStatusLabelKey } from '@/lib/codes';
import { useTimeToFirstQuote } from '@/hooks/useCRM';
import { useRecentDocuments } from '@/hooks/usePageStats';
import { dashboardApi, type DashboardStats, type RecentDocument } from '@/api/dashboardApi';

// ─── Recent Documents (wave I-2) ───────────────────

const DOC_TYPE_ICON: Record<RecentDocument['type'], LucideIcon> = {
  quote: FileText,
  contract: FileSignature,
  invoice: Receipt,
  act: ClipboardCheck,
  generated: FileType,
  receipt: Receipt,
  delivery_note: ClipboardCheck,
};

function RecentDocumentsCard() {
  const { t } = useTranslation();
  const { data: documents, isError, refetch } = useRecentDocuments(8);
  // Маршрут считает `documentRoute` по типу документа, а не берётся готовый хэш от сервера:
  // сервер не знает про маршруты SPA (аудит UI, U1).

  // A failed fetch reads as an explicit error with a retry — never a silent
  // absence that would look like "no documents yet".
  if (isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          <AlertCircle className="h-6 w-6 text-destructive" aria-hidden="true" />
          <p className="text-sm font-medium">{t('common.loadError')}</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            {t('common.retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // Empty → render nothing (no fake rows).
  const items = documents ?? [];
  if (items.length === 0) return null;

  const openDocument = (hash: string) => { window.location.hash = hash; };

  return (
    <Card className="py-0 gap-0">
      <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
        <CardTitle className="text-sm font-semibold">{t('dashboardPage.recentDocuments.title')}</CardTitle>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs">{t('dashboardPage.recentDocuments.document')}</TableHead>
            <TableHead className="text-xs">{t('dashboardPage.recentDocuments.type')}</TableHead>
            <TableHead className="text-xs">{t('dashboardPage.recentDocuments.status')}</TableHead>
            <TableHead className="text-right text-xs">{t('dashboardPage.recentDocuments.date')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((doc) => {
            const Icon = DOC_TYPE_ICON[doc.type] ?? FileText;
            return (
              <TableRow
                key={`${doc.type}-${doc.id}`}
                className="cursor-pointer"
                tabIndex={0}
                role="link"
                onClick={() => openDocument(documentRoute({ kind: doc.type, id: doc.id, dealId: doc.deal }))}
                onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDocument(documentRoute({ kind: doc.type, id: doc.id, dealId: doc.deal })); } }}
              >
                <TableCell>
                  <span className="flex items-center gap-2">
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="text-sm font-medium truncate max-w-xs">{doc.label}</span>
                  </span>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {t(`dashboardPage.recentDocuments.types.${doc.type}`)}
                </TableCell>
                <TableCell>
                  {/* Подпись статуса берётся из словаря ТОГО ЖЕ реестра, где документ живёт:
                      раньше здесь печатался сырой код, а рядом в реестре — перевод. */}
                  {doc.status_code
                    ? <Badge variant="secondary">{t(documentStatusLabelKey(doc.type, doc.status_code), { defaultValue: doc.status_code })}</Badge>
                    : <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell className="text-right text-xs text-muted-foreground">
                  {formatDate(doc.date)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

// ─── Wedge metric card: time-to-first-КП (ADR-0006 Move 4) ───────────────
function TimeToFirstQuoteCard() {
  const { t } = useTranslation();
  const { data } = useTimeToFirstQuote(30);
  const fmt = (h: number) =>
    h >= 24 ? t('dashboardPage.ttfk.days', { n: (h / 24).toFixed(1) }) : t('dashboardPage.ttfk.hoursN', { n: h.toFixed(1) });

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Clock className="h-4 w-4 text-primary" aria-hidden="true" />
          {t('dashboardPage.ttfk.title')}
        </div>
        {!data || data.sample_size === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">{t('dashboardPage.ttfk.empty')}</p>
        ) : (
          <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <div>
              <span className="text-2xl font-bold tabular-nums">{fmt(data.median_hours)}</span>{' '}
              <span className="text-xs text-muted-foreground">{t('dashboardPage.ttfk.median')}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {t('dashboardPage.ttfk.p90')}: <span className="tabular-nums text-foreground">{fmt(data.p90_hours)}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {t('dashboardPage.ttfk.fastest')}: <span className="tabular-nums text-foreground">{fmt(data.fastest_hours)}</span>
            </div>
            <div className="text-xs text-muted-foreground">{t('dashboardPage.ttfk.sample', { n: data.sample_size })}</div>
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">{t('dashboardPage.ttfk.hint')}</p>
      </CardContent>
    </Card>
  );
}

// ─── Back-office inbox ──────────────────────────────────────────────────

/** Operations inbox: what needs me now (attention strip + approval queue) → the wedge
 *  north-star (TTFK) → pipeline distribution → a low-ink metric strip. Actions above metrics. */
function BackOfficeInbox({ stats, onNavigate }: { stats: DashboardStats | null; onNavigate: (page: string) => void }) {
  return (
    <div className="flex flex-col gap-6">
      <AttentionStrip onNavigate={onNavigate} />
      {/* F3 — деньги и поставка: блок появляется сам, когда сделки доходят до счетов. */}
      <PostContractStrip onNavigate={onNavigate} />
      <QuoteApprovalQueue />
      <RecentDocumentsCard />
      <TimeToFirstQuoteCard />
      <PipelineFunnel onNavigate={onNavigate} />
      <MetricStrip stats={stats} />
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────

interface DashboardProps {
  onNavigate?: (page: string) => void;
}

export function Dashboard({ onNavigate }: DashboardProps) {
  const { t, i18n } = useTranslation();
  const [period, setPeriod] = useState('30d');

  // Locale-aware "start – end year" caption derived from the selected period
  // (previously a hardcoded "1 Янв – 21 Мар 2026" that ignored the picker).
  const dateRangeLabel = useMemo(() => {
    const end = new Date();
    const start = new Date(end);
    if (period === '7d') start.setDate(end.getDate() - 7);
    else if (period === '30d') start.setDate(end.getDate() - 30);
    else if (period === '90d') start.setDate(end.getDate() - 90);
    else if (period === '1y') start.setFullYear(end.getFullYear() - 1);
    const fmt = (d: Date) => d.toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' });
    return `${fmt(start)} – ${fmt(end)} ${end.getFullYear()}`;
  }, [period, i18n.language]);

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
            <span>{dateRangeLabel}</span>
          </div>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="h-8 w-36 text-xs" aria-label={t('dashboardPage.selectPeriod')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">7 {t('dashboardPage.days')}</SelectItem>
              <SelectItem value="30d">30 {t('dashboardPage.days')}</SelectItem>
              <SelectItem value="90d">{t('dashboardPage.quarter')}</SelectItem>
              <SelectItem value="1y">{t('dashboardPage.year')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <BackOfficeInbox stats={stats} onNavigate={onNavigate ?? (() => {})} />
    </div>
  );
}
