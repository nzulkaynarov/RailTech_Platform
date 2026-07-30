import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ClipboardCheck, PenLine, FileWarning, FileClock, FileCheck2, FilePlus2, Wallet, ScrollText,
  Truck, PackageCheck, type LucideIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { PRE_KP_STAGES, formatWaiting, isUnclaimedRfq } from '@/lib/waiting';
import { Card, CardContent } from '@/components/ui/card';
import { useDeals, useQuotes, useMyApprovalQueue, useDealStages } from '@/hooks/useCRM';
import { useContracts, useInvoices, useActs, useFulfillments } from '@/hooks/useBilling';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { dealsListRoute } from '@/lib/documentRoute';
import { dealStageLabelKey } from '@/lib/codes';
import type { DashboardStats } from '@/api/dashboardApi';

// ── Urgency signals are derived from real data and compared BY CODE (FSM canon),
//    never by translated name and never by an arbitrary time threshold. ────────

// A buyer RFQ sits in these stages until the seller answers it with a КП (shared lib/waiting).
// Quote statuses that are still "in flight" (a КП that has expired here must be re-issued).
const ACTIVE_QUOTE_STATUSES = ['DRAFT', 'PENDING_TRADE_REVIEW', 'PENDING_APPROVAL', 'READY_TO_SEND', 'SENT'];

type Tone = 'warning' | 'destructive';

interface AttentionItem {
  icon: LucideIcon;
  label: string;
  count: number;
  tone: Tone;
  page: string;
  /** W3 aging-counter: вторичная строка («старшая ждёт 6 ч»). */
  hint?: string | null;
}

function AttentionStat({ item, onNavigate }: { item: AttentionItem; onNavigate: (p: string) => void }) {
  const active = item.count > 0;
  const Icon = item.icon;
  return (
    <button
      type="button"
      disabled={!active}
      onClick={() => active && onNavigate(item.page)}
      className={cn(
        'flex items-center gap-3 rounded-lg border p-4 text-left transition-colors',
        active ? 'cursor-pointer hover:bg-muted/50' : 'cursor-default',
        !active && 'border-border bg-card',
        active && item.tone === 'warning' && 'border-warning/30 bg-warning/5',
        active && item.tone === 'destructive' && 'border-destructive/30 bg-destructive/5',
      )}
    >
      <Icon
        className={cn(
          'h-5 w-5 shrink-0',
          !active && 'text-muted-foreground',
          active && item.tone === 'warning' && 'text-warning',
          active && item.tone === 'destructive' && 'text-destructive',
        )}
        aria-hidden="true"
      />
      <div className="min-w-0">
        <div className="text-2xl font-bold tabular-nums leading-none">{item.count}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{item.label}</div>
        {item.hint && item.count > 0 ? (
          <div className="mt-0.5 truncate text-xs font-medium text-destructive">{item.hint}</div>
        ) : null}
      </div>
    </button>
  );
}

function AttentionGrid({ items, onNavigate }: { items: AttentionItem[]; onNavigate: (p: string) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((item, i) => (
        <AttentionStat key={i} item={item} onNavigate={onNavigate} />
      ))}
    </div>
  );
}

/** SELLER — "what blocks me now": approvals, contracts to sign, RFQs without a КП, expired КП. */
export function SellerAttentionStrip({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { t } = useTranslation();
  const { data: approvals } = useMyApprovalQueue();
  const { data: pendingContracts } = useContracts({ status: 'PENDING_MANAGER' });
  const { data: deals } = useDeals();
  const { data: quotes } = useQuotes();

  // «Заявки без КП» — ЧЕСТНЫЙ счёт (ресерч 2026-07-28): pre-КП стадия И КП ещё НЕТ.
  // Раньше считали только по стадии — плитка кричала «6 без КП», когда у всех шести уже
  // лежали черновики КП (воронка врала глазам).
  const rfqQueue = (deals ?? []).filter(
    (d) => PRE_KP_STAGES.includes(d.stage_code ?? '') && !d.active_quote,
  );
  const rfqsNeedingKp = rfqQueue.length;
  // W3 aging-counter (Bitrix24): сколько ждёт самая старая заявка из этой же выборки.
  const oldestUnclaimed = rfqQueue
    .filter((d) => isUnclaimedRfq(d))
    .reduce<string | null>((oldest, d) => (!oldest || (d.created_at ?? '') < oldest ? d.created_at ?? oldest : oldest), null);
  const oldestWaiting = formatWaiting(t, oldestUnclaimed);
  const expiredQuotes = (quotes ?? []).filter(
    (q) => ACTIVE_QUOTE_STATUSES.includes(q.status_code) && q.valid_until && new Date(q.valid_until).getTime() < Date.now(),
  ).length;

  const items: AttentionItem[] = [
    { icon: ClipboardCheck, label: t('dashboardPage.attn.approvals'), count: (approvals ?? []).length, tone: 'warning', page: 'crm-quotes' },
    { icon: PenLine, label: t('dashboardPage.attn.signContract'), count: (pendingContracts ?? []).length, tone: 'warning', page: 'contracts' },
    { icon: FileWarning, label: t('dashboardPage.attn.rfqNoKp'), count: rfqsNeedingKp, tone: 'destructive', page: 'crm-deals', hint: oldestWaiting ? t('dashboardPage.attn.oldestWaiting', { waiting: oldestWaiting }) : null },
    { icon: FileClock, label: t('dashboardPage.attn.expiredKp'), count: expiredQuotes, tone: 'destructive', page: 'crm-quotes' },
  ];
  return <AttentionGrid items={items} onNavigate={onNavigate} />;
}

/**
 * Вторая половина воронки — деньги и поставка (F3).
 *
 * Полоса внимания заканчивалась на «Договорах на подписи»: всё, что происходит после
 * подписания, на дашборде не отражалось вовсе, хотя данные уже считались на страницах.
 *
 * Блок показывается, ТОЛЬКО когда в нём есть хоть одна ненулевая величина: у компании, которая
 * ещё не дошла до денег, он не занимает экран нулями, а как только пошли счета — появляется сам.
 *
 * Просрочка считается по факту (`due_date` в прошлом у неоплаченного счёта), а НЕ по статусу
 * OVERDUE: тот объявлен в справочнике, но его никто не проставляет — плитка по нему всегда
 * показывала бы ноль. Кому и когда проставлять OVERDUE — открытый вопрос владельцу.
 */
function isOverdue(dueDate: string | null): boolean {
  if (!dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return new Date(dueDate).getTime() < today.getTime();
}

export function PostContractStrip({ side, onNavigate }: { side: 'seller' | 'buyer'; onNavigate: (p: string) => void }) {
  const { t } = useTranslation();
  const { data: invoices } = useInvoices(undefined);
  const { data: acts } = useActs({ status: 'ISSUED' });
  const { data: fulfillments } = useFulfillments(undefined);

  const list = invoices ?? [];
  const drafts = list.filter((invoice) => invoice.status === 'DRAFT');
  const awaitingPayment = list.filter((invoice) => invoice.status === 'ISSUED' || invoice.status === 'PARTIAL');
  const overdueCount = awaitingPayment.filter((invoice) => isOverdue(invoice.due_date)).length;
  const inTransit = (fulfillments ?? []).filter(
    (shipment) => shipment.status === 'SHIPPED' || shipment.status === 'IN_TRANSIT',
  );
  const delivered = (fulfillments ?? []).filter((shipment) => shipment.status === 'DELIVERED');
  // Акт двусторонний (G2): выпустивший его подтвердить не может, сервер отдаёт это в
  // `viewer_can_sign`. Заказчику показываем то, что ждёт ЕГО приёмки, исполнителю — сколько
  // выпущенных актов висит на другой стороне.
  const actsAwaitingMe = (acts ?? []).filter((act) => act.viewer_can_sign);

  const items: AttentionItem[] = side === 'seller'
    ? [
      { icon: FilePlus2, label: t('dashboardPage.attn.invoicesToIssue'), count: drafts.length, tone: 'warning', page: 'invoices' },
      {
        icon: Wallet,
        label: t('dashboardPage.attn.awaitingPayment'),
        count: awaitingPayment.length,
        tone: 'warning',
        page: 'invoices',
        hint: overdueCount ? t('dashboardPage.attn.overdueInvoices', { count: overdueCount }) : null,
      },
      { icon: ScrollText, label: t('dashboardPage.attn.actsAwaitingAcceptance'), count: (acts ?? []).length, tone: 'warning', page: 'acts' },
      { icon: Truck, label: t('dashboardPage.attn.inTransit'), count: inTransit.length, tone: 'warning', page: 'fulfillments' },
    ]
    : [
      {
        icon: Wallet,
        label: t('dashboardPage.attn.invoicesToPay'),
        count: awaitingPayment.length,
        tone: 'warning',
        page: 'invoices',
        hint: overdueCount ? t('dashboardPage.attn.overdueInvoices', { count: overdueCount }) : null,
      },
      { icon: ScrollText, label: t('dashboardPage.attn.actsToAccept'), count: actsAwaitingMe.length, tone: 'destructive', page: 'acts' },
      { icon: Truck, label: t('dashboardPage.attn.awaitingDelivery'), count: inTransit.length, tone: 'warning', page: 'fulfillments' },
      { icon: PackageCheck, label: t('dashboardPage.attn.toAccept'), count: delivered.length, tone: 'destructive', page: 'fulfillments' },
    ];

  if (!items.some((item) => item.count > 0)) return null;

  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-muted-foreground">{t('dashboardPage.attn.postContractTitle')}</h3>
      <AttentionGrid items={items} onNavigate={onNavigate} />
    </div>
  );
}

/** BUYER — "what needs my decision": КП to review, contracts to sign. */
export function BuyerAttentionStrip({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { t } = useTranslation();
  const { data: quotes } = useQuotes();
  const { data: pendingContracts } = useContracts({ status: 'PENDING_CLIENT' });

  const kpToReview = (quotes ?? []).filter((q) => q.status_code === 'SENT').length;

  const items: AttentionItem[] = [
    { icon: FileCheck2, label: t('dashboardPage.attn.reviewKp'), count: kpToReview, tone: 'warning', page: 'my-requests' },
    { icon: PenLine, label: t('dashboardPage.attn.signContract'), count: (pendingContracts ?? []).length, tone: 'warning', page: 'contracts' },
  ];
  return <AttentionGrid items={items} onNavigate={onNavigate} />;
}

// Chart-token classes as literals so Tailwind's JIT keeps them. Cycled per stage.
const FUNNEL_COLORS = [
  'bg-[var(--color-chart-1)]',
  'bg-[var(--color-chart-2)]',
  'bg-[var(--color-chart-3)]',
  'bg-[var(--color-chart-4)]',
  'bg-[var(--color-chart-5)]',
];

/** Deal pipeline — deals grouped by stage_code, ordered by the DealStage lookup's sort_order.
 *  Data-driven (no hardcoded stage list); a click drills into that stage on the deals page. */
export function PipelineFunnel({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { t } = useTranslation();
  // Воронка стоит и на дашборде ПОКУПАТЕЛЯ — клик по сегменту вёл его в очередь продавца,
  // куда гейт не пускает. Маршрут теперь по стороне зрителя (U1).
  const activeStatus = useUserStore((state) => state.activeStatus);
  const viewer = { isSeller: activeStatus === 'SELLER' };
  const { data: deals } = useDeals();
  const { data: stages } = useDealStages();

  const segments = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of deals ?? []) {
      const code = d.stage_code ?? '';
      counts.set(code, (counts.get(code) ?? 0) + 1);
    }
    // `stages` arrives already ordered by the DealStage lookup's sort_order (AbstractLookup
    // default ordering), so we keep the server order rather than re-sorting client-side.
    return (stages ?? [])
      // Localize the funnel label by CODE; the RU-only DB `name` is the fallback only
      // for a stage code this build's map does not know yet.
      .map((s) => ({
        code: s.code,
        name: dealStageLabelKey(s.code) ? t(dealStageLabelKey(s.code)) : s.name,
        count: counts.get(s.code) ?? 0,
      }))
      .filter((s) => s.count > 0);
  }, [deals, stages, t]);

  const total = segments.reduce((sum, s) => sum + s.count, 0);
  if (total === 0) return null;

  return (
    <Card>
      <CardContent className="p-5">
        <h3 className="mb-4 text-sm font-semibold">{t('dashboardPage.funnel.title')}</h3>
        <div className="flex h-2.5 w-full overflow-hidden rounded-full">
          {segments.map((s, i) => (
            <div
              key={s.code}
              className={cn('h-full', FUNNEL_COLORS[i % FUNNEL_COLORS.length])}
              style={{ width: `${(s.count / total) * 100}%` }}
              title={`${s.name}: ${s.count}`}
            />
          ))}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-5">
          {segments.map((s, i) => (
            <button
              key={s.code}
              type="button"
              onClick={() => onNavigate(dealsListRoute(viewer))}
              className="flex items-center gap-2 text-left"
            >
              <span className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', FUNNEL_COLORS[i % FUNNEL_COLORS.length])} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{s.name}</span>
              <span className="text-xs font-semibold tabular-nums text-foreground">{s.count}</span>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Compact, low-ink metric strip — replaces the 4-card KPI grid. Real data from the dashboard stats. */
export function MetricStrip({ stats, role }: { stats: DashboardStats | null; role: 'seller' | 'buyer' }) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const metrics =
    role === 'seller'
      ? [
          { label: t('dashboardPage.kpi.dealsVolume'), value: formatCurrency(stats?.deals_volume ?? 0) },
          { label: t('dashboardPage.kpi.activeRequests'), value: String(stats?.active_requests ?? 0) },
          { label: t('dashboardPage.kpi.catalogItems'), value: String(stats?.catalog_items ?? 0) },
          { label: t('dashboardPage.kpi.clients'), value: String(stats?.clients_count ?? 0) },
        ]
      : [
          { label: t('dashboardPage.kpi.activeRequests'), value: String(stats?.active_requests ?? 0) },
          { label: t('dashboardPage.kpi.quotesReceived'), value: String(stats?.quotes_received ?? 0) },
          { label: t('dashboardPage.kpi.completed'), value: String(stats?.deals_completed ?? 0) },
        ];

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3 p-5">
        {metrics.map((m) => (
          <div key={m.label} className="min-w-0">
            <div className="text-lg font-bold tabular-nums leading-none">{m.value}</div>
            <div className="mt-1 truncate text-xs text-muted-foreground">{m.label}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
