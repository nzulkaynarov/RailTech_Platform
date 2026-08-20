import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { ShoppingCart, ChevronRight } from 'lucide-react'; import { useCurrencyStore } from '@/store/currencyStore'; import { formatDate } from '@/lib/formatLocale'; import { useDeals } from '@/hooks/useCRM'; import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell'; import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { CreateDealDialog } from '@/components/CRM/CreateDealDialog';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { DealStage } from '@/lib/codes';
import { buyerStatus, buyerStatusKey, BUYER_STATUS_ORDER } from '@/lib/requestStatus';
import type { Deal } from '@/api/crmApi';

export function MyRequestsPage() {
  const { t } = useTranslation();
  // Весь список заявок покупателя: собственная 21-я заявка не должна пропадать из «Моих заявок».
  const { data: deals, isLoading, isError, refetch } = useDeals(undefined, { fetchAll: true });
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [createOpen, setCreateOpen] = useState(false);
  const [statusTab, setStatusTab] = useState<string>('all');

  const listParams = useListParams([] as const, { defaultOrdering: '-created_at', pageSize: 15 });
  const myDeals = deals ?? [];

  const selectTab = (key: string) => { setStatusTab(key); listParams.setPage(1); };

  // KPI stats from the same dataset the list renders (no cross-endpoint drift).
  // Tiles are clickable filters synced with the status tab — clicking an active
  // tile clears the filter back to "all".
  const countBy = (key: string) => myDeals.filter((d) => buyerStatusKey(d.stage_code, d.execution_complete) === key).length;
  const tile = (key: string) => ({
    label: t(`requestStatus.${key}`),
    value: String(countBy(key)),
    active: statusTab === key,
    onClick: () => selectTab(statusTab === key ? 'all' : key),
  });
  const stats = [tile('awaiting'), tile('quote'), tile('confirmed'), tile('completed')];

  const openDeal = (deal: Deal) => { window.location.hash = `request-detail/${deal.id}`; };

  // Show a total only once the seller's КП is back — a request has no price.
  const priced = [DealStage.QUOTE_SENT, DealStage.CONTRACT_SIGNED, DealStage.CLOSED_WON] as string[];
  const showTotal = (deal: Deal) => priced.includes(deal.stage_code ?? '') && Number(deal.total_value) > 0;

  const byTab = statusTab === 'all'
    ? myDeals
    : myDeals.filter((d) => buyerStatusKey(d.stage_code, d.execution_complete) === statusTab);

  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={stats}
      actions={[{ label: t('pages.myRequests.newRequest'), onClick: () => setCreateOpen(true) }]}
    >
      {/* Status filter — buyer-facing statuses only (not the 9 internal stages). */}
      <Tabs value={statusTab} onValueChange={selectTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="all">{t('requestStatus.all')}</TabsTrigger>
          {BUYER_STATUS_ORDER.map((key) => (
            <TabsTrigger key={key} value={key}>{t(`requestStatus.${key}`)}</TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.myRequests.searchPlaceholder')}
      />

      {(() => {
        const { items: pageItems, total } = applyListParams(byTab, listParams, {
          searchFields: (d) => [d.title, d.company_name, String(d.id)],
          sortAccessors: { created_at: (d) => d.created_at ?? '' },
        });
        if (isLoading) return <LoadingRows rows={4} />;
        // A failed fetch (Neon sleep / 500 / network) must not read as "no
        // requests" — that empty state's CTA would push a duplicate заявка.
        if (isError) return <ErrorState onRetry={() => refetch()} />;
        if (!pageItems.length) return (
          <EmptyState
            icon={<ShoppingCart className="h-5 w-5" />}
            message={t('pages.common.noData')}
            action={{ label: t('pages.myRequests.newRequest'), onClick: () => setCreateOpen(true) }}
          />
        );
        return (
          <>
            <div className="rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50">
                    <TableHead>{t('pages.myRequests.colRequest')}</TableHead>
                    <TableHead className="w-40">{t('pages.myRequests.colStatus')}</TableHead>
                    <TableHead className="w-32">{t('pages.myRequests.colDate')}</TableHead>
                    <TableHead className="w-32 text-right">{t('pages.myRequests.colTotal')}</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageItems.map((deal: Deal) => {
                    const status = buyerStatus(deal.stage_code, deal.execution_complete);
                    return (
                      <TableRow
                        key={deal.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => openDeal(deal)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openDeal(deal); }}
                        className="cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <TableCell>
                          <span className="font-medium">{deal.title ?? `${t('pages.myRequests.deal')} #${deal.id}`}</span>
                          <span className="block text-xs text-muted-foreground">#{deal.id}</span>
                        </TableCell>
                        <TableCell>
                          <StatusBadge label={t(status.labelKey)} variant={status.variant} />
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground tabular-nums">
                          {formatDate(deal.created_at)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {showTotal(deal)
                            ? <span className="font-semibold text-primary">{formatCurrency(Number(deal.total_value))}</span>
                            : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell>
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
          </>
        );
      })()}

      <CreateDealDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(dealId) => { window.location.hash = `request-detail/${dealId}`; }}
      />
    </PageShell>
  );
}

export default MyRequestsPage;
