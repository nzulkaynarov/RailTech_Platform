import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { ShoppingCart, ChevronRight } from 'lucide-react'; import { useCurrencyStore } from '@/store/currencyStore'; import { formatDate } from '@/lib/formatLocale'; import { useDeals } from '@/hooks/useCRM'; import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell'; import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { CreateDealDialog } from '@/components/CRM/CreateDealDialog';
import { ResponsiveDataTable } from '@/components/ResponsiveDataTable';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
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

  const listParams = useListParams([] as const, { urlKey: 'my-requests', defaultOrdering: '-created_at', pageSize: 15 });
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
      statsError={isError}
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
            {/* «Мои заявки» — первый экран покупателя, и на телефоне он был сырой таблицей
                шириной 868 px: строки обрезались, а прокрутка не видна (оверлейный скроллбар).
                `ResponsiveDataTable` разворачивает её в карточки ниже sm — тот же канон, что у
                остальных реестров продукта. */}
            <div className="rounded-lg border border-border">
              <ResponsiveDataTable<Deal>
                rows={pageItems}
                getRowId={(deal) => deal.id}
                onRowClick={openDeal}
                columns={[
                  {
                    id: 'title',
                    header: t('pages.myRequests.colRequest'),
                    mobileTitle: true,
                    cell: (deal) => (
                      <>
                        <span className="font-medium">{deal.title ?? `${t('pages.myRequests.deal')} #${deal.id}`}</span>
                        <span className="block text-xs text-muted-foreground">#{deal.id}</span>
                      </>
                    ),
                  },
                  {
                    id: 'status',
                    header: t('pages.myRequests.colStatus'),
                    className: 'w-40',
                    cell: (deal) => {
                      const status = buyerStatus(deal.stage_code, deal.execution_complete);
                      return <StatusBadge label={t(status.labelKey)} variant={status.variant} />;
                    },
                  },
                  {
                    id: 'created',
                    header: t('pages.myRequests.colDate'),
                    className: 'w-32',
                    cell: (deal) => (
                      <span className="text-sm text-muted-foreground tabular-nums">{formatDate(deal.created_at)}</span>
                    ),
                  },
                  {
                    id: 'total',
                    header: t('pages.myRequests.colTotal'),
                    className: 'w-32 text-right',
                    cell: (deal) =>
                      showTotal(deal) ? (
                        <span className="font-semibold text-primary">{formatCurrency(Number(deal.total_value))}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      ),
                  },
                  {
                    id: 'open',
                    header: '',
                    className: 'w-10',
                    // На телефоне строка кликабельна целиком — стрелка там лишний столбец.
                    mobileHidden: true,
                    cell: () => <ChevronRight className="h-4 w-4 text-muted-foreground" />,
                  },
                ]}
              />
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
