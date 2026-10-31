import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, CheckCircle2, FileText, X } from 'lucide-react';

import { StatusBadge } from '@/components/StatusBadge';
import { DocumentButton } from '@/components/DocumentButton';
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { Button } from '@/components/ui/button';
import { formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Schemas } from '@/api/portal';

export interface MilestoneItem {
  id: number;
  label: string;
  completed: boolean;
  current?: boolean;
}

export interface SidePeekDoc {
  id: number;
  number: string;
  title: string;
  fileName?: string;
  sizeBytes?: number;
}

export type SidePeekStatus =
  | { statusEntity: 'request'; statusCode: Schemas['RequestStatus'] }
  | { statusEntity: 'quote'; statusCode: Schemas['QuoteStatus'] }
  | { statusEntity: 'contract'; statusCode: Schemas['ContractStatus'] }
  | { statusEntity: 'invoice'; statusCode: Schemas['InvoiceStatus'] }
  | { statusEntity: 'act'; statusCode: Schemas['ActStatus'] }
  | { statusEntity: 'delivery'; statusCode: Schemas['DeliveryStatus'] }
  | { statusEntity?: undefined; statusCode?: undefined };

export type NotionSidePeekProps = {
  open: boolean;
  onClose: () => void;
  code: string;
  title: string;
  managerName?: string;
  money?: Schemas['Money'] | null;
  dateLabel?: string;
  currentStep?: number;
  documents?: SidePeekDoc[];
  onConfirm?: () => void;
  onReject?: () => void;
  confirmLabel?: string;
  rejectLabel?: string;
  canAct?: boolean;
} & SidePeekStatus;

const DEFAULT_MILESTONES = [
  '1. Запрос потребности',
  '2. Коммерческое предложение',
  '3. Договор поставки',
  '4. Счёт и фиксация оплаты',
  '5. Исполнение и Акт приёмки',
];

export function NotionSidePeek(props: NotionSidePeekProps) {
  const {
    open,
    onClose,
    code,
    title,
    managerName,
    money,
    dateLabel,
    currentStep = 1,
    documents = [],
    onConfirm,
    onReject,
    confirmLabel,
    rejectLabel,
    canAct = true,
  } = props;
  const { t } = useTranslation();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (open && event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-charcoal/30 backdrop-blur-xs transition-opacity duration-200 animate-in fade-in-0"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over panel */}
      <aside
        role="dialog"
        aria-label={title}
        aria-modal="true"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-full sm:max-w-[480px] flex-col border-l border-hairline bg-canvas shadow-2xl transition-all duration-250 ease-out animate-in slide-in-from-right-full"
      >
        {/* Шапка боковой панели */}
        <div className="flex items-center justify-between border-b border-hairline p-4">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-ice-navy px-2.5 py-0.5 font-mono text-xs font-semibold text-navy">
              {code}
            </span>
            <span className="text-xs text-muted-foreground">
              {t('peek.windowTitle', { defaultValue: 'Единое окно сделки' })}
            </span>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 rounded-lg text-muted-foreground hover:bg-ice-navy hover:text-navy"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Закрыть' })}
          >
            <X className="size-4" />
          </Button>
        </div>

        {/* Скроллируемое тело панели */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
          {/* Заголовок */}
          <div>
            <h2 className="text-base font-bold text-navy">{title}</h2>
          </div>

          {/* Блок свойств на подложке #F8F9FA */}
          <div className="rounded-xl border border-hairline bg-alabaster p-3.5">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
              <div>
                <dt className="text-muted-foreground">{t('peek.status', { defaultValue: 'Статус' })}</dt>
                <dd className="mt-1 font-medium">
                  {props.statusEntity === 'request' && <StatusBadge entity="request" code={props.statusCode} />}
                  {props.statusEntity === 'quote' && <StatusBadge entity="quote" code={props.statusCode} />}
                  {props.statusEntity === 'contract' && <StatusBadge entity="contract" code={props.statusCode} />}
                  {props.statusEntity === 'invoice' && <StatusBadge entity="invoice" code={props.statusCode} />}
                  {props.statusEntity === 'act' && <StatusBadge entity="act" code={props.statusCode} />}
                  {props.statusEntity === 'delivery' && <StatusBadge entity="delivery" code={props.statusCode} />}
                  {!props.statusEntity && '—'}
                </dd>
              </div>

              <div>
                <dt className="text-muted-foreground">{t('peek.manager', { defaultValue: 'Ответственный' })}</dt>
                <dd className="mt-1 font-medium text-charcoal truncate">
                  {managerName || t('manager.title', { defaultValue: 'Менеджер RailTech' })}
                </dd>
              </div>

              {money ? (
                <div>
                  <dt className="text-muted-foreground">{t('peek.amount', { defaultValue: 'Сумма' })}</dt>
                  <dd className="mt-1 font-mono font-semibold tabular-nums text-navy">
                    {formatMoney(money)}
                  </dd>
                </div>
              ) : null}

              {dateLabel ? (
                <div>
                  <dt className="text-muted-foreground">{t('peek.dueDate', { defaultValue: 'Срок этапа' })}</dt>
                  <dd className="mt-1 font-medium text-charcoal">{dateLabel}</dd>
                </div>
              ) : null}
            </dl>
          </div>

          {/* Интерактивный чек-лист 5 этапов */}
          <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-navy uppercase tracking-wider">
              {t('deal.milestones', { defaultValue: 'Этапы сделки' })}
            </span>
            <ul className="flex flex-col divide-y divide-hairline rounded-xl border border-hairline bg-canvas">
              {DEFAULT_MILESTONES.map((label, idx) => {
                const stepIndex = idx + 1;
                const isPassed = stepIndex < currentStep;
                const isCurrent = stepIndex === currentStep;

                return (
                  <li
                    key={label}
                    className={cn(
                      'flex items-center justify-between p-3 text-xs transition-colors',
                      isCurrent && 'bg-ice-navy/30',
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      {isPassed ? (
                        <div className="flex size-5 items-center justify-center rounded-full bg-sage-bg text-sage">
                          <Check className="size-3 text-sage stroke-[3]" />
                        </div>
                      ) : isCurrent ? (
                        <div className="flex size-5 items-center justify-center rounded-full bg-sand-bg text-sand font-bold">
                          {stepIndex}
                        </div>
                      ) : (
                        <div className="flex size-5 items-center justify-center rounded-full bg-alabaster text-muted-foreground font-mono">
                          {stepIndex}
                        </div>
                      )}
                      <span className={cn('font-medium', isCurrent ? 'text-navy font-semibold' : isPassed ? 'text-charcoal' : 'text-muted-foreground')}>
                        {label}
                      </span>
                    </div>
                    {isCurrent && (
                      <span className="rounded-full bg-ice-navy px-2 py-0.5 text-xs font-semibold text-navy">
                        {t('deal.inProgress', { defaultValue: 'В работе' })}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Обязательный блок «Что произойдёт» */}
          <ConsequenceCallout
            action={props.statusEntity === 'quote' ? 'accept_quote' : props.statusEntity === 'contract' ? 'sign_contract' : 'default'}
          />

          {/* Вложения сделки */}
          {documents.length > 0 && (
            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold text-navy uppercase tracking-wider">
                {t('peek.attachments', { defaultValue: 'Вложения сделки' })}
              </span>
              <ul className="flex flex-col gap-2">
                {documents.map((doc) => (
                  <li
                    key={doc.id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-hairline bg-alabaster/40 p-3 text-xs"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-coral-bg text-coral">
                        <FileText className="size-4 text-coral" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-charcoal">{doc.title}</p>
                        <p className="font-mono text-xs text-muted-foreground">{doc.number}.pdf</p>
                      </div>
                    </div>
                    <DocumentButton
                      documentId={doc.id}
                      fileName={doc.fileName || `${doc.number}.pdf`}
                      label={doc.title}
                      variant="outline"
                    />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Футер быстрых решений */}
        {canAct && (onConfirm || onReject) && (
          <div className="flex items-center justify-end gap-2 border-t border-hairline bg-alabaster/40 p-4">
            {onReject && (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl border-silver text-xs hover:bg-coral-bg hover:text-coral hover:border-coral-border"
                onClick={onReject}
              >
                {rejectLabel || t('common.reject', { defaultValue: 'Отклонить' })}
              </Button>
            )}
            {onConfirm && (
              <Button
                size="sm"
                className="rounded-xl bg-navy text-primary-foreground hover:bg-navy-hover text-xs font-semibold shadow-xs"
                onClick={onConfirm}
              >
                <CheckCircle2 className="size-4" />
                {confirmLabel || t('common.confirmInOneClick', { defaultValue: 'Согласовать в 1 клик' })}
              </Button>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
