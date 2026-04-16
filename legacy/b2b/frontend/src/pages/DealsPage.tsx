import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, Search, Clock, Eye } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { useCurrencyStore } from '@/store/currencyStore';
import { useDeals } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { Deal } from '@/api/crmApi';

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

function DealDetailSheet({
  deal,
  open,
  onOpenChange,
}: {
  deal: Deal | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  if (!deal) return null;

  const rows = [
    { label: t('pages.deals.detail.client'), value: deal.client_name || deal.company_name },
    { label: t('pages.deals.detail.manager'), value: deal.manager_name },
    { label: t('pages.deals.detail.stage'), value: deal.stage_name },
    { label: t('pages.deals.detail.totalValue'), value: deal.total_value ? formatCurrency(Number(deal.total_value)) : undefined },
    { label: t('pages.deals.detail.created'), value: new Date(deal.created_at).toLocaleDateString() },
    ...(deal.updated_at ? [{ label: t('pages.deals.detail.updated'), value: new Date(deal.updated_at).toLocaleDateString() }] : []),
  ].filter(r => r.value);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{deal.title || `${t('pages.deals.deal')} #${deal.id}`}</SheetTitle>
          <SheetDescription>
            {deal.client_name || deal.company_name || `D-${deal.id}`}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-2 space-y-6 px-4">
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('pages.deals.detail.info')}</h3>
            {rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{r.label}</span>
                <span className="text-sm font-medium">{r.value}</span>
              </div>
            ))}
          </section>

          <Separator />

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('pages.deals.detail.stage')}</h3>
            <StatusBadge label={deal.stage_name ?? ''} variant={getDealStageVariant(deal.stage_code ?? '')} />
          </section>

          {deal.notes && (
            <>
              <Separator />
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t('pages.deals.detail.notes')}</h3>
                <div className="rounded-lg border bg-muted/50 p-3">
                  <p className="text-sm whitespace-pre-wrap">{deal.notes}</p>
                </div>
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function DealsPage() {
  const { t } = useTranslation();
  const { data: deals, isLoading } = useDeals();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('all');
  const [detailTarget, setDetailTarget] = useState<Deal | null>(null);

  const selectedDeal = useMemo(() => {
    if (!detailTarget || !deals) return null;
    return deals.find((d) => d.id === detailTarget.id) ?? detailTarget;
  }, [deals, detailTarget]);

  // Get unique stages from real data
  const stages = useMemo(() => {
    if (!deals) return [];
    const map = new Map<string, string>();
    deals.forEach(d => {
      if (d.stage_code && d.stage_name) map.set(d.stage_code, d.stage_name);
    });
    return Array.from(map.entries()).map(([code, name]) => ({ code, name }));
  }, [deals]);

  const filtered = useMemo(() => {
    if (!deals) return [];
    return deals.filter((d) => {
      const matchesSearch = !search ||
        (d.title ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (d.client_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (d.company_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
        String(d.id).includes(search);
      const matchesStage = stageFilter === 'all' || d.stage_code === stageFilter;
      return matchesSearch && matchesStage;
    });
  }, [deals, search, stageFilter]);

  const stats = [
    { label: t('pages.deals.stats.total'), value: String(deals?.length ?? 0) },
    { label: t('pages.deals.stats.active'), value: String(deals?.filter(d => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? '')).length ?? 0) },
    { label: t('pages.deals.stats.quoteSent'), value: String(deals?.filter(d => d.stage_code === 'QUOTE_SENT').length ?? 0) },
    { label: t('pages.deals.stats.closedWon'), value: String(deals?.filter(d => d.stage_code === 'CLOSED_WON').length ?? 0) },
  ];

  return (
    <PageShell
      title={t('pages.deals.title')}
      description={t('pages.deals.description')}
      icon={<FileText className="h-5 w-5" />}
      stats={stats}
    >
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t('pages.deals.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={stageFilter} onValueChange={setStageFilter}>
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('pages.deals.allStages')}</SelectItem>
            {stages.map((s) => (
              <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !filtered.length ? (
            <EmptyState icon={<FileText className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('pages.deals.table.deal')}</TableHead>
                  <TableHead>{t('pages.deals.table.client')}</TableHead>
                  <TableHead>{t('pages.deals.table.stage')}</TableHead>
                  <TableHead className="text-right">{t('pages.deals.table.value')}</TableHead>
                  <TableHead>{t('pages.deals.table.manager')}</TableHead>
                  <TableHead>{t('pages.deals.table.date')}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((deal) => (
                  <TableRow
                    key={deal.id}
                    className="cursor-pointer"
                    onClick={() => setDetailTarget(deal)}
                  >
                    <TableCell>
                      <span className="font-medium">{deal.title || `#${deal.id}`}</span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {deal.client_name || deal.company_name || ''}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        label={deal.stage_name ?? ''}
                        variant={getDealStageVariant(deal.stage_code ?? '')}
                      />
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {deal.total_value ? formatCurrency(Number(deal.total_value)) : ''}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {deal.manager_name || ''}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {new Date(deal.created_at).toLocaleDateString()}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm" onClick={() => setDetailTarget(deal)}>
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DealDetailSheet
        deal={selectedDeal}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default DealsPage;
