import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';

import { StatusBadge } from '@/components/StatusBadge';
import { formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Schemas } from '@/api/portal';

export type DealCardStatus =
  | { statusEntity: 'request'; statusCode: Schemas['RequestStatus'] }
  | { statusEntity: 'quote'; statusCode: Schemas['QuoteStatus'] }
  | { statusEntity: 'contract'; statusCode: Schemas['ContractStatus'] }
  | { statusEntity: 'invoice'; statusCode: Schemas['InvoiceStatus'] }
  | { statusEntity: 'act'; statusCode: Schemas['ActStatus'] }
  | { statusEntity: 'delivery'; statusCode: Schemas['DeliveryStatus'] }
  | { statusEntity?: undefined; statusCode?: undefined };

export type DealCardProps = {
  id: number | string;
  code: string;
  title: string;
  summary?: string | null;
  href?: string;
  onClick?: () => void;
  /** Текущий этап от 1 до 5 */
  step?: number;
  /** Дата или срок */
  dateLabel?: string;
  /** Сумма в деньгах (если есть) */
  money?: Schemas['Money'] | null;
  hasDocuments?: boolean;
  documentCount?: number;
  className?: string;
} & DealCardStatus;

const MILESTONES = [
  'Запрос',
  'КП',
  'Договор',
  'Счёт и Оплата',
  'Исполнение и Акт',
];

export function DealCard(props: DealCardProps) {
  const {
    code,
    title,
    summary,
    href,
    onClick,
    step = 1,
    dateLabel,
    money,
    hasDocuments,
    documentCount,
    className,
  } = props;
  const { t } = useTranslation();
  const clampedStep = Math.max(1, Math.min(5, step));

  const content = (
    <article
      className={cn(
        'portal-card group relative flex min-w-0 flex-col gap-3 p-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
      onClick={onClick}
    >
      {/* Слой 1: Пилл срока + моноширинный код */}
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-mono font-medium text-navy">{code}</span>
        {dateLabel ? (
          <span className="rounded-full bg-alabaster px-2.5 py-0.5 text-xs text-muted-foreground border border-hairline">
            {dateLabel}
          </span>
        ) : null}
      </div>

      {/* Слой 2: Заголовок и резюме */}
      <div className="min-w-0">
        <h3 className="line-clamp-1 text-sm font-semibold text-charcoal transition-colors group-hover:text-navy">
          {title}
        </h3>
        {summary ? (
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{summary}</p>
        ) : null}
      </div>

      {/* Слой 3: Сегментированный прогресс-бар (5 сегментов) */}
      <div className="flex flex-col gap-1.5 pt-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground font-medium">
            {t('deal.milestones', { defaultValue: 'Этапы сделки' })}
          </span>
          <span className="font-mono font-semibold tabular-nums text-navy">
            {clampedStep}/5 · {MILESTONES[clampedStep - 1]}
          </span>
        </div>
        <div className="grid grid-cols-5 gap-1.5" role="progressbar" aria-valuenow={clampedStep} aria-valuemin={1} aria-valuemax={5}>
          {[1, 2, 3, 4, 5].map((index) => {
            const isCompleted = index < clampedStep;
            const isCurrent = index === clampedStep;
            return (
              <span
                key={index}
                className={cn(
                  'h-1.5 rounded-full transition-colors',
                  isCompleted ? 'bg-sage' : isCurrent ? 'bg-navy' : 'bg-hairline',
                )}
                title={`${index}. ${MILESTONES[index - 1]}`}
              />
            );
          })}
        </div>
      </div>

      {/* Слой 4: Футер — статус, сумма и документы */}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 text-xs">
        <div className="flex items-center gap-1.5">
          {props.statusEntity === 'request' && <StatusBadge entity="request" code={props.statusCode} />}
          {props.statusEntity === 'quote' && <StatusBadge entity="quote" code={props.statusCode} />}
          {props.statusEntity === 'contract' && <StatusBadge entity="contract" code={props.statusCode} />}
          {props.statusEntity === 'invoice' && <StatusBadge entity="invoice" code={props.statusCode} />}
          {props.statusEntity === 'act' && <StatusBadge entity="act" code={props.statusCode} />}
          {props.statusEntity === 'delivery' && <StatusBadge entity="delivery" code={props.statusCode} />}

          {money ? (
            <span className="font-mono font-semibold tabular-nums text-navy">
              {formatMoney(money)}
            </span>
          ) : null}
        </div>

        {hasDocuments || (documentCount && documentCount > 0) ? (
          <span className="flex items-center gap-1 text-muted-foreground" title={t('common.documents', { defaultValue: 'Документы' })}>
            <FileText className="size-3.5" aria-hidden="true" />
            <span className="font-mono text-xs">{documentCount ?? 1}</span>
          </span>
        ) : null}
      </div>
    </article>
  );

  if (href) {
    return (
      <Link to={href} className="block outline-none">
        {content}
      </Link>
    );
  }

  return content;
}
