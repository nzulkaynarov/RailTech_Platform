import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { cn } from '@/lib/utils';

export type ConsequenceAction =
  | 'accept_quote'
  | 'reject_quote'
  | 'sign_contract'
  | 'pay_invoice'
  | 'accept_act'
  | 'return_act'
  | 'accept_delivery'
  | 'submit_request'
  | 'default';

export interface ConsequenceCalloutProps {
  action?: ConsequenceAction;
  customText?: string;
  className?: string;
}

export function ConsequenceCallout({ action = 'default', customText, className }: ConsequenceCalloutProps) {
  const { t } = useTranslation();

  const getActionText = (): string => {
    if (customText) return customText;
    switch (action) {
      case 'accept_quote':
        return t('consequences.acceptQuote', {
          defaultValue:
            'После согласования КП автоматически сформируется договор, бронь номенклатуры зафиксируется, а счёт будет выставлен в раздел «Счета».',
        });
      case 'reject_quote':
        return t('consequences.rejectQuote', {
          defaultValue:
            'КП будет отклонено с указанной причиной. Менеджер получит уведомление и подготовит перерасчёт или скорректированную спецификацию.',
        });
      case 'sign_contract':
        return t('consequences.signContract', {
          defaultValue:
            'Договор будет подписан с вашей стороны электронной подписью подтверждением. Заказ поступит в комплектацию и исполнение.',
        });
      case 'pay_invoice':
        return t('consequences.payInvoice', {
          defaultValue:
            'После фиксации оплаты бухгалтерией статус счёта обновится на «Оплачен», и начнется отгрузка позиций по графику.',
        });
      case 'accept_act':
        return t('consequences.acceptAct', {
          defaultValue:
            'Акт приёма-передачи будет подписан, обязательства по этапу сделки считаются выполненными в полном объеме.',
        });
      case 'return_act':
        return t('consequences.returnAct', {
          defaultValue:
            'Акт будет возвращён на доработку. Претензия с вашими замечаниями поступит ответственному исполнителю.',
        });
      case 'accept_delivery':
        return t('consequences.acceptDelivery', {
          defaultValue:
            'Вы подтверждаете получение товара без замечаний. Будет инициирован финальный закрывающий акт.',
        });
      case 'submit_request':
        return t('consequences.submitRequest', {
          defaultValue:
            'Запрос поступит в обработку инженеру-расчётчику. Расчёт КП будет готов в течение 2–4 рабочих часов.',
        });
      default:
        return t('consequences.default', {
          defaultValue:
            'Действие будет зафиксировано в едином реестре сделки с отправкой уведомления персональному менеджеру.',
        });
    }
  };

  return (
    <div
      role="note"
      className={cn(
        'flex items-start gap-3 rounded-xl border border-hairline bg-ice-navy/80 p-3.5 text-xs text-navy',
        className,
      )}
    >
      <div className="flex size-5 shrink-0 items-center justify-center rounded-full bg-navy text-primary-foreground">
        <Info className="size-3 text-primary-foreground" aria-hidden="true" />
      </div>
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="font-semibold text-navy tracking-tight">
          {t('consequences.title', { defaultValue: 'Что произойдёт' })}
        </span>
        <p className="text-charcoal leading-relaxed">{getActionText()}</p>
      </div>
    </div>
  );
}
