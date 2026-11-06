import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  CheckCircle2,
  ClipboardCheck,
  FileSignature,
  FileText,
  MessagesSquare,
  PackageOpen,
  Receipt,
  Truck,
  type LucideIcon,
} from 'lucide-react';

import { ErrorState } from '@/components/QueryStates';
import { ToneBadge } from '@/components/StatusBadge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useActionRequired } from '@/hooks/useActionRequired';
import { formatMoney, formatQuantity } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useCanAct } from '@/session/useMe';

/**
 * Виджет «Требует вашего решения» (M2-CAB-04, бенчмарк Odoo/ERPNext: клиент видит «что от меня ждут»).
 * Агрегирует (`useActionRequired`):
 *   - КП, которые ждут решения: `sent` и `viewed` (просмотренное КП — всё ещё без ответа), срок не истёк;
 *   - Договоры, ждущие подписи клиента;
 *   - Счета — только просроченные (`overdue` или срок оплаты прошёл при неоплате): остальные счёта — не решение;
 *   - Акты issued, требующие приёмки или возврата.
 * Пока списки грузятся — скелетон на месте виджета, а не пустота: виджет не вставляется над готовым списком (K10).
 * Ошибка загрузки любого из четырёх списков — видимое состояние с повтором: тихое «ничего не требуется» было бы ложью.
 * Наблюдателю (без права действовать) виджет не призывает к действию: «Ждут решения компании» и кто решает.
 */
export function ActionRequiredWidget({ holdSkeleton = false }: { holdSkeleton?: boolean }) {
  const { t } = useTranslation();
  const canAct = useCanAct();
  const actions = useActionRequired();

  // `holdSkeleton` — экран ещё грузит свой список: виджет и список появляются в одном кадре, скелетон списка под
  // виджетом не сдвигается, когда виджет дорисовался раньше (K10).
  if (!actions.available) return null; // у партнёра нет КП, договоров, счетов и актов — ждать от него решений нечего
  if (actions.isPending || holdSkeleton) return <ActionRequiredSkeleton />;
  if (actions.error) {
    return (
      <div className="mb-6" data-testid="action-required-error">
        <ErrorState error={actions.error} onRetry={actions.retry} />
      </div>
    );
  }

  const total = actions.total;
  if (total === 0) {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-lg border border-dashed bg-card/60 p-3.5 text-sm text-muted-foreground">
        <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />
        <span>{t('widgets.actionRequired.allClear')}</span>
      </div>
    );
  }

  const title = canAct ? t('widgets.actionRequired.title') : t('widgets.actionRequired.titleViewer');
  const hint = (key: string) => (canAct ? t(`widgets.actionRequired.${key}`) : t('widgets.actionRequired.viewerHint'));

  return (
    <section role="region" aria-label={title} className="mb-6 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-primary">{title}</h2>
        <ToneBadge tone={canAct ? 'warning' : 'neutral'}>{total}</ToneBadge>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {actions.partnerApplicationAwaiting ? (
          <ActionCard
            key="partner-application-draft"
            icon={FileSignature}
            tone="primary"
            badge={t('widgets.actionRequired.partnerContractBadge')}
            aside={<AlertCircle className="size-3.5 text-primary" aria-hidden="true" />}
            to="/company"
            label={t('widgets.actionRequired.partnerContractLabel')}
          >
            {hint('agreePartnerContract')}
          </ActionCard>
        ) : null}

        {actions.quotes.map((quote) => (
          <ActionCard
            key={`quote-${quote.id}`}
            icon={FileText}
            tone="warning"
            badge={t('widgets.actionRequired.quoteBadge')}
            aside={<Amount>{formatMoney(quote.total)}</Amount>}
            to={`/quotes/${quote.id}`}
            label={t('pages.quotes.numberVersion', { number: quote.number, version: quote.version })}
          >
            {hint('reviewQuote')}
          </ActionCard>
        ))}

        {actions.contracts.map((contract) => (
          <ActionCard
            key={`contract-${contract.id}`}
            icon={FileSignature}
            tone="primary"
            badge={t('widgets.actionRequired.contractBadge')}
            aside={<AlertCircle className="size-3.5 text-primary" aria-hidden="true" />}
            to="/contracts"
            label={contract.number}
          >
            {hint('signContract')}
          </ActionCard>
        ))}

        {actions.invoices.map((invoice) => {
          const view = actions.views.get(invoice.id);
          return (
            <ActionCard
              key={`inv-${invoice.id}`}
              icon={Receipt}
              tone="warning"
              badge={t('widgets.actionRequired.invoiceBadge')}
              aside={<Amount>{formatMoney(view?.remaining)}</Amount>}
              to="/invoices"
              label={invoice.number}
            >
              <span className="flex flex-wrap items-center gap-1.5">
                {hint('payInvoice')}
                <ToneBadge tone="danger">
                  {t('pages.invoices.overdueDays', { count: view?.overdueDays ?? 1 })}
                </ToneBadge>
              </span>
            </ActionCard>
          );
        })}

        {actions.acts.map((act) => (
          <ActionCard
            key={`act-${act.id}`}
            icon={ClipboardCheck}
            tone="primary"
            badge={t('widgets.actionRequired.actBadge')}
            aside={<AlertCircle className="size-3.5 text-primary" aria-hidden="true" />}
            to="/acts"
            label={act.number}
          >
            {hint('acceptAct')}
          </ActionCard>
        ))}

        {actions.deliveries.map((delivery) => (
          <ActionCard
            key={`delivery-${delivery.id}`}
            icon={Truck}
            tone="primary"
            badge={t('widgets.actionRequired.deliveryBadge')}
            aside={
              <span className="text-xs font-semibold tabular-nums text-foreground">
                {formatQuantity(delivery.quantity, delivery.unit)}
              </span>
            }
            to="/deliveries"
            label={delivery.title}
          >
            {hint('acceptDelivery')}
          </ActionCard>
        ))}

        {actions.rejectedProducts.map((product) => (
          <ActionCard
            key={`product-remark-${product.id}`}
            icon={PackageOpen}
            tone="warning"
            badge={t('widgets.actionRequired.productRemarkBadge')}
            aside={<ToneBadge tone="warning">{product.code || t('widgets.actionRequired.remarks')}</ToneBadge>}
            to="/my-products?tab=rejected"
            label={product.title}
          >
            {hint('fixProductRemarks')}
          </ActionCard>
        ))}

        {actions.unread > 0 ? (
          <ActionCard
            key="unread-chat"
            icon={MessagesSquare}
            tone="primary"
            badge={t('widgets.actionRequired.messagesBadge')}
            aside={<ToneBadge tone="primary">{actions.unread}</ToneBadge>}
            to="/messages"
            label={t('widgets.actionRequired.unreadMessages', { count: actions.unread })}
          >
            {hint('replyManager')}
          </ActionCard>
        ) : null}
      </div>
    </section>
  );
}

/** Сумма в карточке: обычный шрифт с табличными цифрами (не моноширинный). */
function Amount({ children }: { children: ReactNode }) {
  return <span className="font-semibold whitespace-nowrap text-foreground tabular-nums">{children}</span>;
}

function ActionCard({
  icon: Icon,
  tone,
  badge,
  aside,
  to,
  label,
  children,
}: {
  icon: LucideIcon;
  tone: 'warning' | 'primary';
  badge: string;
  aside: ReactNode;
  to: string;
  label: string;
  children: ReactNode;
}) {
  const color = tone === 'warning' ? 'text-warning' : 'text-primary';
  return (
    <Card className="portal-card group relative border-border hover:border-ring/40">
      <CardContent className="flex flex-col gap-1.5 p-3.5">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className={cn('flex items-center gap-1 font-medium', color)}>
            <Icon className={cn('size-3.5', color)} aria-hidden="true" />
            {badge}
          </span>
          {aside}
        </div>
        <p className="text-sm font-medium text-foreground">
          <Link
            to={to}
            className="rounded-sm outline-none after:absolute after:inset-0 hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            {label}
          </Link>
        </p>
        <span className="text-xs text-muted-foreground">{children}</span>
      </CardContent>
    </Card>
  );
}

/**
 * Место виджета, пока списки грузятся: заголовок и строка карточек той же высоты (на телефоне — одна, на десктопе — до
 * четырёх). Экран «Запросы» показывает свой список одновременно с виджетом, поэтому готовый список не сдвигается.
 */
function ActionRequiredSkeleton() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-busy="true" className="mb-6 flex flex-col gap-3" data-testid="action-required-loading">
      <span className="sr-only">{t('common.loading')}</span>
      <Skeleton className="h-5 w-48" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton
            key={index}
            className={cn('h-[5.75rem] rounded-2xl', index > 0 && 'hidden sm:block', index > 1 && 'sm:hidden lg:block')}
          />
        ))}
      </div>
    </div>
  );
}
