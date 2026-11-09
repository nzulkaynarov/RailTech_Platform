import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  BarChart3,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Coins,
  FileText,
  Scale,
  Search,
  SearchX,
  TrendingUp,
  Truck,
} from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import type {
  PartnerOrderDetail,
  PartnerOrderListItem,
  PartnerOrderStatus,
  PartnerPriceRequestDetail,
  PartnerPriceRequestListItem,
  PartnerPriceRequestStatus,
  PartnerSettlementLine,
} from '@/api/portal';
import {
  useConfirmPartnerOrder,
  usePartnerFinance,
  usePartnerOrderDetail,
  usePartnerOrders,
  usePartnerPriceRequestDetail,
  usePartnerPriceRequests,
  useRequestPartnerOrderDateChange,
  useRespondPartnerPriceRequest,
  useShipPartnerOrder,
} from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { DateField } from '@/components/DateField';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList, type ListColumn } from '@/components/ResponsiveList';
import { ToneBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useUrlParams } from '@/hooks/useUrlParams';
import { pageCount, parsePage } from '@/lib/catalog';
import { formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { toast } from '@/lib/toast';
import { CanAct } from '@/session/CanAct';

const PAGE_SIZE = 20;

const ORDER_TABS: ReadonlyArray<'all' | 'sent' | 'confirmed' | 'received' | 'cancelled'> = [
  'all',
  'sent',
  'confirmed',
  'received',
  'cancelled',
];

const RFQ_TABS: ReadonlyArray<'all' | 'sent' | 'answered'> = ['all', 'sent', 'answered'];

const PRICE_RE = /^\d{1,12}([.,]\d{1,2})?$/;
const CURRENCY_RE = /^[A-Z]{3}$/;

/** Сумма заказа: валюта в заказе может быть не указана — тогда только число, без чужой валюты. */
function orderAmount(amount: string, currency: string | null | undefined) {
  return currency ? formatMoney({ amount, currency }) : amount;
}

export function PartnerOrdersPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const patchUrl = useUrlParams();

  const view =
    params.get('view') === 'rfq' ? 'rfq' : params.get('view') === 'finance' ? 'finance' : 'orders';
  const tab = params.get('tab') ?? 'all';
  const q = params.get('q') ?? '';
  const page = parsePage(params.get('page'));

  const orderIdParam = Number(params.get('orderId'));
  const orderId = Number.isInteger(orderIdParam) && orderIdParam > 0 ? orderIdParam : null;

  const rfqIdParam = Number(params.get('rfqId'));
  const rfqId = Number.isInteger(rfqIdParam) && rfqIdParam > 0 ? rfqIdParam : null;

  // Dialog state for confirming order
  const [confirmOrderId, setConfirmOrderId] = useState<number | null>(null);
  const [expectedDate, setExpectedDate] = useState<string | null>('');
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const confirmOrder = useConfirmPartnerOrder();

  // Dialog state for a date change request
  const [dateChangeOrderId, setDateChangeOrderId] = useState<number | null>(null);
  const [requestedDate, setRequestedDate] = useState<string | null>('');
  const [dateChangeReason, setDateChangeReason] = useState<string>('');
  const [dateChangeError, setDateChangeError] = useState<string | null>(null);
  const requestDateChange = useRequestPartnerOrderDateChange();

  // Dialog state for shipping order (ASN)
  const [shipOrderId, setShipOrderId] = useState<number | null>(null);
  const [supplierDoc, setSupplierDoc] = useState<string>('');
  const [carrier, setCarrier] = useState<string>('');
  const [trackingNumber, setTrackingNumber] = useState<string>('');
  const [shipNote, setShipNote] = useState<string>('');
  const shipOrder = useShipPartnerOrder();

  // Dialog state for responding to RFQ
  const [respondRfqId, setRespondRfqId] = useState<number | null>(null);
  const [answerNote, setAnswerNote] = useState<string>('');
  const [linePrices, setLinePrices] = useState<Record<number, string>>({});
  const [priceCurrency, setPriceCurrency] = useState<string>('UZS');
  const [respondError, setRespondError] = useState<string | null>(null);
  const respondRfq = useRespondPartnerPriceRequest();
  const respondRfqQuery = usePartnerPriceRequestDetail(respondRfqId);

  // Queries
  const ordersQuery = usePartnerOrders(
    {
      status: tab === 'all' ? undefined : (tab as PartnerOrderStatus),
      q: q || undefined,
      page,
      page_size: PAGE_SIZE,
    },
    { enabled: view === 'orders' },
  );

  const rfqQuery = usePartnerPriceRequests(
    {
      status: tab === 'all' ? undefined : (tab as PartnerPriceRequestStatus),
      q: q || undefined,
      page,
      page_size: PAGE_SIZE,
    },
    { enabled: view === 'rfq' },
  );

  const financeQuery = usePartnerFinance({ enabled: view === 'finance' });

  const selectedOrderQuery = usePartnerOrderDetail(orderId);
  const selectedRfqQuery = usePartnerPriceRequestDetail(rfqId);

  const update = (patch: Record<string, string | null>) => {
    patchUrl(patch);
  };

  const handleConfirmSubmit = () => {
    if (!confirmOrderId) return;
    if (!expectedDate) {
      setConfirmError(t('pages.partnerOrders.dialogs.dateRequired'));
      return;
    }
    setConfirmError(null);
    confirmOrder.mutate(
      {
        id: confirmOrderId,
        body: { expected_date: expectedDate },
      },
      {
        onSuccess: () => {
          toast.success(t('pages.partnerOrders.confirmSuccess'));
          setConfirmOrderId(null);
          setExpectedDate('');
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const closeDateChange = () => {
    setDateChangeOrderId(null);
    setRequestedDate('');
    setDateChangeReason('');
    setDateChangeError(null);
  };

  const handleDateChangeSubmit = () => {
    if (!dateChangeOrderId) return;
    if (!requestedDate) {
      setDateChangeError(t('pages.partnerOrders.dialogs.dateRequired'));
      return;
    }
    setDateChangeError(null);
    requestDateChange.mutate(
      {
        id: dateChangeOrderId,
        body: { requested_date: requestedDate, reason: dateChangeReason.trim() || undefined },
      },
      {
        onSuccess: () => {
          toast.success(t('pages.partnerOrders.dateChangeSuccess'));
          closeDateChange();
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const handleShipSubmit = () => {
    if (!shipOrderId || !supplierDoc.trim()) return;
    shipOrder.mutate(
      {
        id: shipOrderId,
        body: {
          supplier_doc: supplierDoc.trim(),
          carrier: carrier.trim() || undefined,
          tracking_number: trackingNumber.trim() || undefined,
          note: shipNote.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success(t('pages.partnerOrders.shipSuccess'));
          setShipOrderId(null);
          setSupplierDoc('');
          setCarrier('');
          setTrackingNumber('');
          setShipNote('');
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const handleRespondSubmit = () => {
    if (!respondRfqId || !answerNote.trim()) return;
    const priced = Object.entries(linePrices)
      .map(([id, value]) => ({ id: Number(id), unit_price: value.trim().replace(',', '.') }))
      .filter((row) => row.unit_price !== '');
    if (priced.some((row) => !PRICE_RE.test(row.unit_price) || Number(row.unit_price) <= 0)) {
      setRespondError(t('pages.partnerOrders.dialogs.priceInvalid'));
      return;
    }
    const currency = priceCurrency.trim().toUpperCase();
    if (priced.length > 0 && !CURRENCY_RE.test(currency)) {
      setRespondError(t('pages.partnerOrders.dialogs.currencyInvalid'));
      return;
    }
    setRespondError(null);
    respondRfq.mutate(
      {
        id: respondRfqId,
        body: {
          answer_note: answerNote.trim(),
          ...(priced.length > 0 ? { currency, lines: priced } : {}),
        },
      },
      {
        onSuccess: () => {
          toast.success(t('pages.partnerOrders.respondSuccess'));
          setRespondRfqId(null);
          setAnswerNote('');
          setLinePrices({});
          setRespondError(null);
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  // Orders table columns
  const orderColumns: ListColumn<PartnerOrderListItem>[] = [
    {
      id: 'status',
      header: t('pages.partnerOrders.columns.status'),
      cell: (row) => <OrderStatusBadge status={row.status} />,
    },
    {
      id: 'expectedDate',
      header: t('pages.partnerOrders.columns.expectedDate'),
      cell: (row) => (row.expected_date ? formatDate(row.expected_date) : '—'),
    },
    {
      id: 'linesCount',
      header: t('pages.partnerOrders.columns.positions'),
      cell: (row) => `${row.lines_count} ${t('pages.partnerOrders.posShort')}`,
    },
    {
      id: 'totalAmount',
      header: t('pages.partnerOrders.columns.totalAmount'),
      className: 'text-right font-medium',
      cell: (row) => orderAmount(row.total_amount, row.currency),
    },
  ];

  // RFQ table columns
  const rfqColumns: ListColumn<PartnerPriceRequestListItem>[] = [
    {
      id: 'status',
      header: t('pages.partnerOrders.columns.status'),
      cell: (row) => <RfqStatusBadge status={row.status} />,
    },
    {
      id: 'positions',
      header: t('pages.partnerOrders.columns.positions'),
      cell: (row) => `${row.lines_count} ${t('pages.partnerOrders.posShort')}`,
    },
    {
      id: 'answeredAt',
      header: t('pages.partnerOrders.columns.answeredAt'),
      cell: (row) => (row.answered_at ? formatDateTime(row.answered_at) : '—'),
    },
  ];

  // Settlement table columns (K4-partner-finance)
  const settlementColumns: ListColumn<PartnerSettlementLine>[] = [
    {
      id: 'status',
      header: t('pages.partnerOrders.columns.status'),
      cell: (row) => <OrderStatusBadge status={row.status} />,
    },
    {
      id: 'orderedAmount',
      header: t('pages.partnerOrders.finance.orderedTotal'),
      cell: (row) => (
        <span className="font-medium tabular-nums">
          {formatMoney({ amount: row.ordered_amount, currency: row.currency })}
        </span>
      ),
    },
    {
      id: 'receivedAmount',
      header: t('pages.partnerOrders.finance.receivedTotal'),
      cell: (row) => (
        <span className="font-medium text-success tabular-nums">
          {formatMoney({ amount: row.received_amount, currency: row.currency })}
        </span>
      ),
    },
    {
      id: 'inTransitAmount',
      header: t('pages.partnerOrders.finance.inTransitTotal'),
      cell: (row) => (
        <span className="font-medium text-warning tabular-nums">
          {formatMoney({ amount: row.in_transit_amount, currency: row.currency })}
        </span>
      ),
    },
    {
      id: 'receiptsCount',
      header: t('pages.partnerOrders.finance.receiptsCount'),
      cell: (row) => (
        <ToneBadge tone={row.receipts_count > 0 ? 'info' : 'neutral'}>
          {row.receipts_count}
        </ToneBadge>
      ),
    },
  ];

  const total = view === 'orders' ? (ordersQuery.data?.total ?? 0) : (rfqQuery.data?.total ?? 0);
  const totalPages = pageCount(total, PAGE_SIZE);

  return (
    <div className="container mx-auto max-w-7xl px-4 py-6">
      <PageHeader
        title={t('pages.partnerOrders.title')}
        subtitle={t('pages.partnerOrders.description')}
        icon={ClipboardList}
      />

      {/* Primary View Switcher: Orders vs RFQ */}
      <div className="mb-6 flex flex-wrap gap-2 border-b border-border pb-3">
        <Button
          type="button"
          variant={view === 'orders' ? 'default' : 'ghost'}
          className="rounded-full"
          onClick={() => update({ view: 'orders', tab: null, page: null, q: null })}
        >
          <ClipboardList className="mr-2 size-4" />
          {t('pages.partnerOrders.views.orders')}
          {ordersQuery.data?.counts ? (
            <span className="ml-1.5 rounded-full bg-primary-foreground/20 px-2 py-0.5 text-xs">
              {ordersQuery.data.counts.all}
            </span>
          ) : null}
        </Button>
        <Button
          type="button"
          variant={view === 'rfq' ? 'default' : 'ghost'}
          className="rounded-full"
          onClick={() => update({ view: 'rfq', tab: null, page: null, q: null })}
        >
          <FileText className="mr-2 size-4" />
          {t('pages.partnerOrders.views.rfq')}
          {rfqQuery.data?.counts ? (
            <span className="ml-1.5 rounded-full bg-primary-foreground/20 px-2 py-0.5 text-xs">
              {rfqQuery.data.counts.all}
            </span>
          ) : null}
        </Button>
        <Button
          type="button"
          variant={view === 'finance' ? 'default' : 'ghost'}
          className="rounded-full"
          onClick={() => update({ view: 'finance', tab: null, page: null, q: null })}
        >
          <BarChart3 className="mr-2 size-4" />
          {t('pages.partnerOrders.views.finance')}
        </Button>
      </div>

      {/* Subtabs and Search */}
      {view !== 'finance' ? (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div role="group" aria-label={t('pages.partnerOrders.tabsLabel')} className="flex flex-wrap gap-2">
            {view === 'orders'
              ? ORDER_TABS.map((statusName) => (
                  <Button
                    key={statusName}
                    type="button"
                    size="sm"
                    variant={statusName === tab ? 'default' : 'outline'}
                    aria-pressed={statusName === tab}
                    className="rounded-full"
                    onClick={() => update({ tab: statusName === 'all' ? null : statusName, page: null })}
                  >
                    {t(`pages.partnerOrders.orderTabs.${statusName}`)}
                    <span className="ml-1 tabular-nums opacity-80">
                      {ordersQuery.data?.counts[statusName] ?? 0}
                    </span>
                  </Button>
                ))
              : RFQ_TABS.map((statusName) => (
                  <Button
                    key={statusName}
                    type="button"
                    size="sm"
                    variant={statusName === tab ? 'default' : 'outline'}
                    aria-pressed={statusName === tab}
                    className="rounded-full"
                    onClick={() => update({ tab: statusName === 'all' ? null : statusName, page: null })}
                  >
                    {t(`pages.partnerOrders.rfqTabs.${statusName}`)}
                    <span className="ml-1 tabular-nums opacity-80">
                      {rfqQuery.data?.counts[statusName] ?? 0}
                    </span>
                  </Button>
                ))}
          </div>

          <SearchForm key={q} initial={q} onSearch={(term) => update({ q: term || null, page: null })} />
        </div>
      ) : null}

      {/* Main Content Area */}
      {view === 'finance' ? (
        financeQuery.isPending ? (
          <ListSkeleton />
        ) : financeQuery.isError ? (
          <ErrorState error={financeQuery.error} onRetry={() => void financeQuery.refetch()} />
        ) : !financeQuery.data ? null : (
          <div>
            {/* Balances by currency */}
            <div className="mb-8">
              <h3 className="mb-4 text-base font-semibold text-foreground flex items-center gap-2">
                <Coins className="size-5 text-primary" />
                {t('pages.partnerOrders.finance.balancesTitle')}
              </h3>
              {financeQuery.data.balances.length === 0 ? (
                <EmptyState
                  icon={SearchX}
                  title={t('pages.partnerOrders.emptyTitle')}
                  text={t('pages.partnerOrders.finance.emptyBalancesText')}
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {financeQuery.data.balances.map((b) => (
                    <Card key={b.currency} className="border-border/60">
                      <CardContent className="p-5">
                        <div className="flex items-center justify-between pb-3 border-b border-border/40">
                          <span className="font-bold text-lg">{b.currency}</span>
                          <ToneBadge tone="neutral">
                            {b.orders_count} {t('pages.partnerOrders.finance.ordersCountSuffix')}
                          </ToneBadge>
                        </div>
                        <div className="mt-4 space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">{t('pages.partnerOrders.finance.orderedTotal')}</span>
                            <span className="font-semibold tabular-nums">
                              {formatMoney({ amount: b.ordered_total, currency: b.currency })}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">{t('pages.partnerOrders.finance.receivedTotal')}</span>
                            <span className="font-semibold text-success tabular-nums">
                              {formatMoney({ amount: b.received_total, currency: b.currency })}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">{t('pages.partnerOrders.finance.inTransitTotal')}</span>
                            <span className="font-semibold text-warning tabular-nums">
                              {formatMoney({ amount: b.in_transit_total, currency: b.currency })}
                            </span>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>

            {/* Scorecard */}
            <div className="mb-8">
              <h3 className="mb-4 text-base font-semibold text-foreground flex items-center gap-2">
                <TrendingUp className="size-5 text-primary" />
                {t('pages.partnerOrders.finance.scorecardTitle')}
              </h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Card className="border-border/60">
                  <CardContent className="p-5">
                    <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t('pages.partnerOrders.finance.otifRate')}
                    </div>
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold tracking-tight text-foreground">
                        {financeQuery.data.scorecard.otif_rate}%
                      </span>
                      <ToneBadge
                        tone={
                          financeQuery.data.scorecard.otif_rate >= 90
                            ? 'success'
                            : financeQuery.data.scorecard.otif_rate >= 75
                              ? 'warning'
                              : 'danger'
                        }
                      >
                        {financeQuery.data.scorecard.otif_rate >= 90
                          ? t('pages.partnerOrders.finance.excellent')
                          : t('pages.partnerOrders.finance.target')}
                      </ToneBadge>
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground">
                      {t('pages.partnerOrders.finance.completedOrdersCount', {
                        count: financeQuery.data.scorecard.completed_orders_count,
                      })}
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/60">
                  <CardContent className="p-5">
                    <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t('pages.partnerOrders.finance.rfqRate')}
                    </div>
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold tracking-tight text-foreground">
                        {financeQuery.data.scorecard.rfq_response_rate}%
                      </span>
                      <ToneBadge tone={financeQuery.data.scorecard.rfq_response_rate >= 80 ? 'success' : 'warning'}>
                        {financeQuery.data.scorecard.rfq_response_rate >= 80
                          ? t('pages.partnerOrders.finance.responsive')
                          : t('pages.partnerOrders.finance.target')}
                      </ToneBadge>
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground">
                      {t('pages.partnerOrders.finance.totalRfqsCount', {
                        count: financeQuery.data.scorecard.total_rfqs_count,
                      })}
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/60">
                  <CardContent className="p-5">
                    <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t('pages.partnerOrders.finance.freshnessRate')}
                    </div>
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold tracking-tight text-foreground">
                        {financeQuery.data.scorecard.price_freshness_rate}%
                      </span>
                      <ToneBadge tone={financeQuery.data.scorecard.price_freshness_rate >= 90 ? 'success' : 'warning'}>
                        {financeQuery.data.scorecard.price_freshness_rate >= 90
                          ? t('pages.partnerOrders.finance.fresh')
                          : t('pages.partnerOrders.finance.updateNeeded')}
                      </ToneBadge>
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground">
                      {t('pages.partnerOrders.finance.activeOffersCount', {
                        count: financeQuery.data.scorecard.active_offers_count,
                      })}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>

            {/* Settlements Table */}
            <div className="mb-8">
              <h3 className="mb-4 text-base font-semibold text-foreground flex items-center gap-2">
                <Scale className="size-5 text-primary" />
                {t('pages.partnerOrders.finance.settlementsTitle')}
              </h3>
              {financeQuery.data.settlements.length === 0 ? (
                <EmptyState
                  icon={SearchX}
                  title={t('pages.partnerOrders.emptyTitle')}
                  text={t('pages.partnerOrders.finance.emptySettlementsText')}
                />
              ) : (
                <ResponsiveList<PartnerSettlementLine>
                  label={t('pages.partnerOrders.finance.settlementsListLabel')}
                  rows={financeQuery.data.settlements}
                  getRowId={(row) => row.order_id}
                  title={{
                    header: t('pages.partnerOrders.columns.number'),
                    cell: (row) => (
                      <div>
                        <button
                          type="button"
                          className="text-left font-semibold text-primary hover:underline"
                          onClick={() => update({ orderId: String(row.order_id) })}
                        >
                          {row.order_number}
                        </button>
                        <div className="text-xs text-muted-foreground">{formatDate(row.order_date)}</div>
                      </div>
                    ),
                  }}
                  columns={settlementColumns}
                />
              )}
            </div>
          </div>
        )
      ) : view === 'orders' ? (
        ordersQuery.isPending ? (
          <ListSkeleton />
        ) : ordersQuery.isError ? (
          <ErrorState error={ordersQuery.error} onRetry={() => void ordersQuery.refetch()} />
        ) : (ordersQuery.data?.items ?? []).length === 0 ? (
          <EmptyState
            icon={SearchX}
            title={t('pages.partnerOrders.emptyTitle')}
            text={q ? t('pages.partnerOrders.notFoundText') : t('pages.partnerOrders.emptyOrdersText')}
          />
        ) : (
          <div>
            <ResponsiveList<PartnerOrderListItem>
              label={t('pages.partnerOrders.ordersListLabel')}
              rows={ordersQuery.data.items}
              getRowId={(row) => row.id}
              title={{
                header: t('pages.partnerOrders.columns.number'),
                cell: (row) => (
                  <div>
                    <button
                      type="button"
                      className="text-left font-semibold text-primary hover:underline"
                      onClick={() => update({ orderId: String(row.id) })}
                    >
                      {row.number}
                    </button>
                    <div className="text-xs text-muted-foreground">{formatDate(row.created_at)}</div>
                  </div>
                ),
              }}
              columns={orderColumns}
              actions={{
                header: t('pages.partnerOrders.columns.actions'),
                cell: (row) => (
                  <div className="flex items-center gap-1.5">
                    <CanAct>
                      {row.status === 'sent' ? (
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs"
                          onClick={() => {
                            setConfirmOrderId(row.id);
                            setExpectedDate(row.expected_date ?? '');
                          }}
                        >
                          <CheckCircle2 className="mr-1 size-3.5 text-success" />
                          {t('pages.partnerOrders.actions.confirm')}
                        </Button>
                      ) : null}
                      {row.status === 'confirmed' ? (
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs"
                          onClick={() => {
                            setShipOrderId(row.id);
                            setSupplierDoc('');
                            setCarrier('');
                            setTrackingNumber('');
                            setShipNote('');
                          }}
                        >
                          <Truck className="mr-1 size-3.5 text-info" />
                          {t('pages.partnerOrders.actions.ship')}
                        </Button>
                      ) : null}
                    </CanAct>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-xs"
                      onClick={() => update({ orderId: String(row.id) })}
                    >
                      {t('pages.partnerOrders.actions.view')}
                    </Button>
                  </div>
                ),
              }}
            />

            {/* Pagination */}
            {totalPages > 1 ? (
              <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => update({ page: page > 2 ? String(page - 1) : null })}
                >
                  <ChevronLeft className="mr-1 size-4" />
                  {t('partner.prev')}
                </Button>
                <div className="text-sm text-muted-foreground">
                  {t('partner.page', { page, pages: totalPages })}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page >= totalPages}
                  onClick={() => update({ page: String(page + 1) })}
                >
                  {t('partner.next')}
                  <ChevronRight className="ml-1 size-4" />
                </Button>
              </div>
            ) : null}
          </div>
        )
      ) : rfqQuery.isPending ? (
        <ListSkeleton />
      ) : rfqQuery.isError ? (
        <ErrorState error={rfqQuery.error} onRetry={() => void rfqQuery.refetch()} />
      ) : (rfqQuery.data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={SearchX}
          title={t('pages.partnerOrders.emptyTitle')}
          text={q ? t('pages.partnerOrders.notFoundText') : t('pages.partnerOrders.emptyRfqText')}
        />
      ) : (
        <div>
          <ResponsiveList<PartnerPriceRequestListItem>
            label={t('pages.partnerOrders.rfqListLabel')}
            rows={rfqQuery.data.items}
            getRowId={(row) => row.id}
            title={{
              header: t('pages.partnerOrders.columns.subject'),
              cell: (row) => (
                <div>
                  <button
                    type="button"
                    className="text-left font-semibold text-primary hover:underline"
                    onClick={() => update({ rfqId: String(row.id) })}
                  >
                    {row.subject}
                  </button>
                  <div className="text-xs text-muted-foreground">{formatDate(row.requested_at)}</div>
                </div>
              ),
            }}
            columns={rfqColumns}
            actions={{
              header: t('pages.partnerOrders.columns.actions'),
              cell: (row) => (
                <div className="flex items-center gap-1.5">
                  <CanAct>
                    {row.status === 'sent' ? (
                      <Button
                        size="sm"
                        variant="default"
                        className="text-xs"
                        onClick={() => {
                          setRespondRfqId(row.id);
                          setAnswerNote('');
                          setLinePrices({});
                          setRespondError(null);
                        }}
                      >
                        {t('pages.partnerOrders.actions.respond')}
                      </Button>
                    ) : null}
                  </CanAct>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-xs"
                    onClick={() => update({ rfqId: String(row.id) })}
                  >
                    {t('pages.partnerOrders.actions.view')}
                  </Button>
                </div>
              ),
            }}
          />

          {/* Pagination */}
          {totalPages > 1 ? (
            <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1}
                onClick={() => update({ page: page > 2 ? String(page - 1) : null })}
              >
                <ChevronLeft className="mr-1 size-4" />
                {t('partner.prev')}
              </Button>
              <div className="text-sm text-muted-foreground">
                {t('partner.page', { page, pages: totalPages })}
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= totalPages}
                onClick={() => update({ page: String(page + 1) })}
              >
                {t('partner.next')}
                <ChevronRight className="ml-1 size-4" />
              </Button>
            </div>
          ) : null}
        </div>
      )}

      {/* Order Detail Dialog */}
      <OrderDetailDialog
        orderId={orderId}
        order={selectedOrderQuery.data ?? null}
        loading={selectedOrderQuery.isPending}
        error={selectedOrderQuery.isError ? selectedOrderQuery.error : null}
        onRetry={() => void selectedOrderQuery.refetch()}
        onClose={() => update({ orderId: null })}
        onDateChangeClick={(id) => {
          setDateChangeOrderId(id);
          setRequestedDate('');
          setDateChangeReason('');
          setDateChangeError(null);
        }}
        onConfirmClick={(id, date) => {
          setConfirmOrderId(id);
          setExpectedDate(date ?? '');
        }}
        onShipClick={(id) => {
          setShipOrderId(id);
          setSupplierDoc('');
          setCarrier('');
          setTrackingNumber('');
          setShipNote('');
        }}
      />

      {/* RFQ Detail Dialog */}
      <RfqDetailDialog
        rfqId={rfqId}
        rfq={selectedRfqQuery.data ?? null}
        loading={selectedRfqQuery.isPending}
        error={selectedRfqQuery.isError ? selectedRfqQuery.error : null}
        onRetry={() => void selectedRfqQuery.refetch()}
        onClose={() => update({ rfqId: null })}
        onRespondClick={(id) => {
          setRespondRfqId(id);
          setAnswerNote('');
          setLinePrices({});
          setRespondError(null);
        }}
      />

      {/* Confirm Order Action Dialog */}
      <ActionDialog
        open={confirmOrderId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmOrderId(null);
            setExpectedDate('');
            setConfirmError(null);
          }
        }}
        title={t('pages.partnerOrders.dialogs.confirmTitle')}
        description={t('pages.partnerOrders.dialogs.confirmDescription')}
        confirmLabel={t('pages.partnerOrders.actions.confirm')}
        pending={confirmOrder.isPending}
        error={confirmOrder.error}
        message={confirmError}
        onSubmit={handleConfirmSubmit}
      >
        <div className="space-y-3 pt-2">
          <Label htmlFor="expected-date">{t('pages.partnerOrders.dialogs.expectedDateLabel')}</Label>
          <DateField
            id="expected-date"
            value={expectedDate}
            onChange={(val) => setExpectedDate(val)}
          />
        </div>
      </ActionDialog>

      {/* Date Change Request Dialog */}
      <ActionDialog
        open={dateChangeOrderId !== null}
        onOpenChange={(open) => {
          if (!open) closeDateChange();
        }}
        title={t('pages.partnerOrders.dialogs.dateChangeTitle')}
        description={t('pages.partnerOrders.dialogs.dateChangeDescription')}
        confirmLabel={t('pages.partnerOrders.actions.sendDateChange')}
        pending={requestDateChange.isPending}
        error={requestDateChange.error}
        message={dateChangeError}
        onSubmit={handleDateChangeSubmit}
      >
        <div className="space-y-3 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="date-change-date">{t('pages.partnerOrders.dialogs.newDateLabel')} *</Label>
            <DateField id="date-change-date" value={requestedDate} onChange={(val) => setRequestedDate(val)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="date-change-reason">{t('pages.partnerOrders.dialogs.reasonLabel')}</Label>
            <Input
              id="date-change-reason"
              maxLength={500}
              value={dateChangeReason}
              onChange={(e) => setDateChangeReason(e.target.value)}
            />
          </div>
        </div>
      </ActionDialog>

      {/* Ship Order Action Dialog (ASN) */}
      <ActionDialog
        open={shipOrderId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setShipOrderId(null);
            setSupplierDoc('');
            setCarrier('');
            setTrackingNumber('');
            setShipNote('');
          }
        }}
        title={t('pages.partnerOrders.dialogs.shipTitle')}
        description={t('pages.partnerOrders.dialogs.shipDescription')}
        confirmLabel={t('pages.partnerOrders.actions.ship')}
        pending={shipOrder.isPending}
        error={shipOrder.error}
        onSubmit={handleShipSubmit}
      >
        <div className="space-y-3 pt-2">
          <div>
            <Label htmlFor="asn-doc">{t('pages.partnerOrders.dialogs.supplierDocLabel')} *</Label>
            <Input
              id="asn-doc"
              placeholder={t('pages.partnerOrders.dialogs.supplierDocPlaceholder')}
              value={supplierDoc}
              onChange={(e) => setSupplierDoc(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="asn-carrier">{t('pages.partnerOrders.dialogs.carrierLabel')}</Label>
            <Input
              id="asn-carrier"
              placeholder={t('pages.partnerOrders.dialogs.carrierPlaceholder')}
              value={carrier}
              onChange={(e) => setCarrier(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="asn-tracking">{t('pages.partnerOrders.dialogs.trackingNumberLabel')}</Label>
            <Input
              id="asn-tracking"
              placeholder={t('pages.partnerOrders.dialogs.trackingNumberPlaceholder')}
              value={trackingNumber}
              onChange={(e) => setTrackingNumber(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="asn-note">{t('pages.partnerOrders.dialogs.noteLabel')}</Label>
            <Input
              id="asn-note"
              placeholder={t('pages.partnerOrders.dialogs.notePlaceholder')}
              value={shipNote}
              onChange={(e) => setShipNote(e.target.value)}
            />
          </div>
        </div>
      </ActionDialog>

      {/* Respond RFQ Action Dialog */}
      <ActionDialog
        open={respondRfqId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRespondRfqId(null);
            setAnswerNote('');
            setLinePrices({});
            setRespondError(null);
          }
        }}
        title={t('pages.partnerOrders.dialogs.respondTitle')}
        description={t('pages.partnerOrders.dialogs.respondDescription')}
        confirmLabel={t('pages.partnerOrders.actions.sendResponse')}
        pending={respondRfq.isPending}
        error={respondRfq.error}
        message={respondError}
        onSubmit={handleRespondSubmit}
      >
        <div className="space-y-3 pt-2">
          <Label htmlFor="rfq-response-note">{t('pages.partnerOrders.dialogs.responseNoteLabel')} *</Label>
          <textarea
            id="rfq-response-note"
            rows={4}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            placeholder={t('pages.partnerOrders.dialogs.responseNotePlaceholder')}
            value={answerNote}
            onChange={(e) => setAnswerNote(e.target.value)}
            required
          />
          {(respondRfqQuery.data?.lines.length ?? 0) > 0 ? (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t('pages.partnerOrders.dialogs.pricesLegend')}</legend>
              <p className="text-xs text-muted-foreground">{t('pages.partnerOrders.dialogs.pricesHint')}</p>
              {respondRfqQuery.data?.lines.map((line) => (
                <div key={line.id} className="flex items-center gap-2">
                  <Label htmlFor={`rfq-price-${line.id}`} className="min-w-0 flex-1 text-sm font-normal break-words">
                    {line.name}
                  </Label>
                  <Input
                    id={`rfq-price-${line.id}`}
                    inputMode="decimal"
                    className="w-28 tabular-nums"
                    value={linePrices[line.id] ?? ''}
                    onChange={(e) => setLinePrices((prev) => ({ ...prev, [line.id]: e.target.value }))}
                  />
                </div>
              ))}
              <div className="flex items-center gap-2">
                <Label htmlFor="rfq-currency" className="flex-1 text-sm font-normal">
                  {t('pages.partnerOrders.dialogs.currencyLabel')}
                </Label>
                <Input
                  id="rfq-currency"
                  maxLength={3}
                  className="w-28 uppercase"
                  value={priceCurrency}
                  onChange={(e) => setPriceCurrency(e.target.value)}
                />
              </div>
            </fieldset>
          ) : null}
        </div>
      </ActionDialog>
    </div>
  );
}

function OrderStatusBadge({ status }: { status: PartnerOrderStatus }) {
  const { t } = useTranslation();
  switch (status) {
    case 'sent':
      return <ToneBadge tone="info">{t('pages.partnerOrders.status.sent')}</ToneBadge>;
    case 'confirmed':
      return <ToneBadge tone="warning">{t('pages.partnerOrders.status.confirmed')}</ToneBadge>;
    case 'received':
      return <ToneBadge tone="success">{t('pages.partnerOrders.status.received')}</ToneBadge>;
    case 'cancelled':
      return <ToneBadge tone="danger">{t('pages.partnerOrders.status.cancelled')}</ToneBadge>;
    default:
      return <ToneBadge tone="neutral">{t('pages.partnerOrders.status.draft')}</ToneBadge>;
  }
}

function RfqStatusBadge({ status }: { status: PartnerPriceRequestStatus }) {
  const { t } = useTranslation();
  switch (status) {
    case 'answered':
      return <ToneBadge tone="success">{t('pages.partnerOrders.rfqStatus.answered')}</ToneBadge>;
    case 'failed':
      return <ToneBadge tone="danger">{t('pages.partnerOrders.rfqStatus.failed')}</ToneBadge>;
    default:
      return <ToneBadge tone="info">{t('pages.partnerOrders.rfqStatus.sent')}</ToneBadge>;
  }
}

function SearchForm({ initial, onSearch }: { initial: string; onSearch: (val: string) => void }) {
  const { t } = useTranslation();
  const [val, setVal] = useState(initial);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSearch(val.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="flex w-full gap-2 sm:w-auto">
      <div className="relative min-w-0 flex-1">
        <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder={t('pages.partnerOrders.searchPlaceholder')}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          className="w-full pl-9 text-sm sm:w-64"
        />
      </div>
      <Button type="submit" size="sm" variant="outline">
        {t('partner.searchLabel')}
      </Button>
    </form>
  );
}

function OrderDetailDialog({
  orderId,
  order,
  loading,
  error,
  onRetry,
  onClose,
  onConfirmClick,
  onShipClick,
  onDateChangeClick,
}: {
  orderId: number | null;
  order: PartnerOrderDetail | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onClose: () => void;
  onConfirmClick: (id: number, date?: string | null) => void;
  onShipClick: (id: number) => void;
  onDateChangeClick: (id: number) => void;
}) {
  const { t } = useTranslation();

  return (
    <Dialog open={orderId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between pr-6">
            <DialogTitle className="text-xl font-bold">
              {order
                ? `${t('pages.partnerOrders.orderPrefix')} ${order.number}`
                : error
                  ? t('pages.partnerOrders.loadErrorTitle')
                  : t('app.loading')}
            </DialogTitle>
            {order ? <OrderStatusBadge status={order.status} /> : null}
          </div>
          <DialogDescription>
            {order ? `${t('pages.partnerOrders.createdAt')}: ${formatDateTime(order.created_at)}` : ''}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : loading || !order ? (
          <ListSkeleton />
        ) : (
          <div className="min-w-0 space-y-6 py-2">
            {/* Summary info */}
            <div className="grid grid-cols-2 gap-4 rounded-lg bg-muted/40 p-4 sm:grid-cols-4">
              <div>
                <div className="text-xs text-muted-foreground">{t('pages.partnerOrders.columns.expectedDate')}</div>
                <div className="font-medium">{order.expected_date ? formatDate(order.expected_date) : '—'}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">{t('pages.partnerOrders.columns.totalAmount')}</div>
                <div className="font-semibold text-primary tabular-nums">
                  {orderAmount(order.total_amount, order.currency)}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">{t('pages.partnerOrders.columns.positions')}</div>
                <div className="font-medium">{order.lines.length}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">{t('pages.partnerOrders.confirmedAt')}</div>
                <div className="font-medium">{order.confirmed_at ? formatDate(order.confirmed_at) : '—'}</div>
              </div>
            </div>

            {order.date_change ? (
              <div className="rounded-md bg-warning/10 p-3 text-sm">
                {t('pages.partnerOrders.dateChangePending', { date: formatDate(order.date_change.requested_date) })}
                {order.date_change.reason ? (
                  <div className="mt-1 text-xs text-muted-foreground">{order.date_change.reason}</div>
                ) : null}
              </div>
            ) : null}

            {order.note ? (
              <div className="rounded-md border border-border p-3 text-sm">
                <span className="font-semibold text-muted-foreground">{t('pages.partnerOrders.noteLabel')}: </span>
                {order.note}
              </div>
            ) : null}

            {/* Lines table */}
            <div>
              <h3 className="mb-2 font-semibold">{t('pages.partnerOrders.linesTitle')}</h3>
              <div
                className="overflow-x-auto rounded-md border border-border"
                tabIndex={0}
                role="region"
                aria-label={t('pages.partnerOrders.linesTitle')}
              >
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border bg-muted/60 text-xs text-muted-foreground">
                    <tr>
                      <th className="p-2.5">#</th>
                      <th className="p-2.5">{t('pages.partnerOrders.columns.name')}</th>
                      <th className="p-2.5">{t('pages.partnerOrders.columns.article')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.qty')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.receivedQty')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.unitPrice')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.totalPrice')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {order.lines.map((l) => (
                      <tr key={l.id}>
                        <td className="p-2.5 text-muted-foreground">{l.position}</td>
                        <td className="p-2.5 font-medium">{l.name}</td>
                        <td className="p-2.5 text-muted-foreground">{l.article || '—'}</td>
                        <td className="p-2.5 text-right">
                          {l.quantity} {l.unit}
                        </td>
                        <td className="p-2.5 text-right">
                          <span
                            className={
                              l.received_quantity < l.quantity && order.status === 'received'
                                ? 'font-semibold text-warning'
                                : ''
                            }
                          >
                            {l.received_quantity} {l.unit}
                          </span>
                        </td>
                        <td className="p-2.5 text-right">{l.unit_price}</td>
                        <td className="p-2.5 text-right font-medium">{l.total_price}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Warehouse Receipts */}
            {order.receipts && order.receipts.length > 0 ? (
              <div>
                <h3 className="mb-2 flex items-center gap-2 font-semibold">
                  <ClipboardList className="size-4" />
                  {t('pages.partnerOrders.receiptsTitle')}
                </h3>
                <div className="space-y-3">
                  {order.receipts.map((rcpt) => (
                    <div key={rcpt.id} className="rounded-lg border border-border p-3 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-2">
                        <div className="flex items-center gap-2 font-medium">
                          <span>
                            {t('pages.partnerOrders.receiptPrefix')} #{rcpt.id}
                          </span>
                          {rcpt.supplier_doc ? (
                            <span className="text-xs text-muted-foreground">
                              ({t('pages.partnerOrders.dialogs.supplierDocLabel')}: {rcpt.supplier_doc})
                            </span>
                          ) : null}
                        </div>
                        <div className="text-xs text-muted-foreground">{formatDateTime(rcpt.received_at)}</div>
                      </div>
                      <div
                        className="mt-2 overflow-x-auto"
                        tabIndex={0}
                        role="region"
                        aria-label={t('pages.partnerOrders.receiptsTitle')}
                      >
                        <table className="w-full text-left text-xs">
                          <thead className="bg-muted/40 text-muted-foreground">
                            <tr>
                              <th className="p-1.5">{t('pages.partnerOrders.columns.name')}</th>
                              <th className="p-1.5 text-right">{t('pages.partnerOrders.columns.receivedQty')}</th>
                              <th className="p-1.5">{t('pages.partnerOrders.columns.warehouse')}</th>
                              <th className="p-1.5">{t('pages.partnerOrders.columns.conformityDoc')}</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border/40">
                            {rcpt.lines.map((rline) => (
                              <tr key={rline.id}>
                                <td className="p-1.5 font-medium">{rline.name}</td>
                                <td className="p-1.5 text-right font-semibold">
                                  {rline.quantity} {rline.unit}
                                </td>
                                <td className="p-1.5 text-muted-foreground">{rline.warehouse_name || '—'}</td>
                                <td className="p-1.5 text-muted-foreground">
                                  {rline.conformity_doc_number ? (
                                    <span>
                                      {rline.conformity_doc_number}
                                      {rline.conformity_doc_valid_until
                                        ? ` (${formatDate(rline.conformity_doc_valid_until)})`
                                        : ''}
                                    </span>
                                  ) : (
                                    '—'
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Shipment notices */}
            {order.shipment_notices.length > 0 ? (
              <div>
                <h3 className="mb-2 flex items-center gap-2 font-semibold">
                  <Truck className="size-4" />
                  {t('pages.partnerOrders.shipmentsTitle')}
                </h3>
                <div className="space-y-2">
                  {order.shipment_notices.map((notice) => (
                    <div key={notice.id} className="rounded-md border border-border/70 p-2.5 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-semibold">{notice.supplier_doc}</span>
                        <span className="shrink-0 text-muted-foreground">{formatDateTime(notice.created_at)}</span>
                      </div>
                      {[notice.carrier, notice.tracking_number, notice.note].some(Boolean) ? (
                        <div className="mt-1 text-muted-foreground">
                          {[notice.carrier, notice.tracking_number, notice.note].filter(Boolean).join(' · ')}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* History logs */}
            {order.logs.length > 0 ? (
              <div>
                <h3 className="mb-2 font-semibold">{t('pages.partnerOrders.historyTitle')}</h3>
                <div className="space-y-2">
                  {order.logs.map((log) => (
                    <div
                      key={log.id}
                      className="flex items-start justify-between rounded-md border border-border/70 p-2.5 text-xs"
                    >
                      <span className="font-semibold">
                        {t(`pages.partnerOrders.logKinds.${log.kind}`)}
                      </span>
                      <div className="shrink-0 text-muted-foreground">{formatDateTime(log.created_at)}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex gap-2">
            <CanAct>
              {order && order.status === 'sent' ? (
                <Button
                  size="sm"
                  onClick={() => {
                    onClose();
                    onConfirmClick(order.id, order.expected_date);
                  }}
                >
                  <CheckCircle2 className="mr-1.5 size-4" />
                  {t('pages.partnerOrders.actions.confirm')}
                </Button>
              ) : null}
              {order && order.status === 'confirmed' ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onClose();
                      onShipClick(order.id);
                    }}
                  >
                    <Truck className="mr-1.5 size-4" />
                    {t('pages.partnerOrders.actions.ship')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onClose();
                      onDateChangeClick(order.id);
                    }}
                  >
                    {t('pages.partnerOrders.actions.requestDateChange')}
                  </Button>
                </>
              ) : null}
            </CanAct>
          </div>
          <DialogClose asChild>
            <Button size="sm" variant="ghost">
              {t('common.close')}
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RfqDetailDialog({
  rfqId,
  rfq,
  loading,
  error,
  onRetry,
  onClose,
  onRespondClick,
}: {
  rfqId: number | null;
  rfq: PartnerPriceRequestDetail | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onClose: () => void;
  onRespondClick: (id: number) => void;
}) {
  const { t } = useTranslation();

  return (
    <Dialog open={rfqId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between pr-6">
            <DialogTitle className="text-xl font-bold">
              {rfq ? rfq.subject : error ? t('pages.partnerOrders.loadErrorTitle') : t('app.loading')}
            </DialogTitle>
            {rfq ? <RfqStatusBadge status={rfq.status} /> : null}
          </div>
          <DialogDescription>
            {rfq ? `${t('pages.partnerOrders.requestedAt')}: ${formatDateTime(rfq.requested_at)}` : ''}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : loading || !rfq ? (
          <ListSkeleton />
        ) : (
          <div className="min-w-0 space-y-4 py-2">
            {rfq.note ? (
              <div className="rounded-md border border-border p-3 text-sm">
                <span className="font-semibold text-muted-foreground">{t('pages.partnerOrders.noteLabel')}: </span>
                {rfq.note}
              </div>
            ) : null}

            {/* Lines */}
            <div>
              <h3 className="mb-2 font-semibold">{t('pages.partnerOrders.linesTitle')}</h3>
              <div
                className="overflow-x-auto rounded-md border border-border"
                tabIndex={0}
                role="region"
                aria-label={t('pages.partnerOrders.linesTitle')}
              >
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border bg-muted/60 text-xs text-muted-foreground">
                    <tr>
                      <th className="p-2.5">#</th>
                      <th className="p-2.5">{t('pages.partnerOrders.columns.name')}</th>
                      <th className="p-2.5">{t('pages.partnerOrders.columns.article')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.qty')}</th>
                      <th className="p-2.5 text-right">{t('pages.partnerOrders.columns.unitPrice')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {rfq.lines.map((l, idx) => (
                      <tr key={l.id}>
                        <td className="p-2.5 text-muted-foreground">{idx + 1}</td>
                        <td className="p-2.5 font-medium">{l.name}</td>
                        <td className="p-2.5 text-muted-foreground">{l.article || '—'}</td>
                        <td className="p-2.5 text-right">
                          {l.quantity} {l.unit}
                        </td>
                        <td className="p-2.5 text-right tabular-nums">
                          {l.answer_price ? orderAmount(l.answer_price, rfq.answer_currency) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Answer note if answered */}
            {rfq.answered_at ? (
              <div className="rounded-md bg-success/10 p-3 text-sm">
                <div className="font-semibold text-success">
                  {t('pages.partnerOrders.responseSent')} ({formatDateTime(rfq.answered_at)}):
                </div>
                <div className="mt-1 whitespace-pre-wrap">{rfq.answer_note}</div>
              </div>
            ) : null}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <CanAct>
            {rfq && rfq.status === 'sent' ? (
              <Button
                size="sm"
                onClick={() => {
                  onClose();
                  onRespondClick(rfq.id);
                }}
              >
                {t('pages.partnerOrders.actions.respond')}
              </Button>
            ) : null}
          </CanAct>
          <DialogClose asChild>
            <Button size="sm" variant="ghost">
              {t('common.close')}
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
