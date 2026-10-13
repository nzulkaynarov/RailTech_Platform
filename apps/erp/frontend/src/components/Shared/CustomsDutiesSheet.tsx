import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink, Loader2, TriangleAlert } from 'lucide-react';

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { CountrySelect } from '@/components/Shared/CountrySelect';
import { useCountries, useCustomsDuties } from '@/hooks/useMasterData';
import type { CustomsPayment } from '@/api/masterDataApi';

/** Цифровые коды платежей ГТК — стабильный ключ строки; подписи наши, источник отдаёт узбекские. */
const PAYMENT_LABEL_KEY: Record<string, string> = {
  '10': 'customsDuties.payments.fee',
  '20': 'customsDuties.payments.duty',
  '27': 'customsDuties.payments.excise',
  '29': 'customsDuties.payments.vat',
};

export interface CustomsDutiesSheetProps {
  hsCode: string;
  /** Наименование позиции из нашего справочника — заголовок панели. */
  hsName?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Таможенные платежи по коду ТН ВЭД — ВИТРИНА интегрированного тарифа ГТК.
 *
 * Зачем в карточке: подготавливая КП с растаможкой, менеджер уходил на сайт ГТК, руками вбивал
 * код и возвращался переносить цифры. Панель показывает то же самое там, где код уже выбран.
 *
 * Три правила, которые здесь важнее вёрстки:
 *   1. Ставку НЕ подставляем в расчёт КП. Пошлина зависит от происхождения, преференций и
 *      сертификата происхождения — это решение менеджера, а не автоподстановка (иначе мы
 *      начинаем консультировать по таможне и отвечать за цифру).
 *   2. Пустая ставка рисуется «—», а не «0%»: источник оставляет ячейку пустой и когда платежа
 *      нет, и когда ставка не задана. Додумывать за таможню нельзя.
 *   3. Источник лёг — панель не оставляет пользователя в тупике: показывает ссылку на
 *      калькулятор ГТК, чтобы путь всё равно можно было пройти вручную.
 */
export function CustomsDutiesSheet({ hsCode, hsName, open, onOpenChange }: CustomsDutiesSheetProps) {
  const { t } = useTranslation();
  const { data: countries } = useCountries();
  // Страну не угадываем: происхождение знает менеджер, а неверная страна даёт неверную ставку.
  const [originId, setOriginId] = useState('');
  const originCode = countries?.find((country) => String(country.id) === originId)?.code ?? '';
  const { data, isFetching, isError } = useCustomsDuties(open ? hsCode : '', originCode);

  const paymentLabel = (payment: CustomsPayment) => {
    const key = PAYMENT_LABEL_KEY[payment.code];
    return key ? t(key) : payment.source_label;
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{t('customsDuties.title')}</SheetTitle>
          <SheetDescription>
            <span className="font-mono">{hsCode}</span>
            {hsName ? ` — ${hsName}` : ''}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-6">
          <div className="space-y-2">
            <Label htmlFor="duties-origin">{t('customsDuties.originLabel')}</Label>
            <CountrySelect
              id="duties-origin"
              value={originId}
              onChange={setOriginId}
              placeholder={t('customsDuties.originPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">{t('customsDuties.originHint')}</p>
          </div>

          {!originCode && (
            <p className="text-sm text-muted-foreground">{t('customsDuties.chooseOriginFirst')}</p>
          )}

          {originCode && isFetching && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('customsDuties.loading')}
            </div>
          )}

          {originCode && isError && (
            <div className="space-y-2 rounded-md border border-warning/40 bg-warning/10 p-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <TriangleAlert className="h-4 w-4 text-warning" aria-hidden="true" />
                {t('customsDuties.unavailableTitle')}
              </div>
              <p className="text-xs text-muted-foreground">{t('customsDuties.unavailableHint')}</p>
              <a
                className="inline-flex items-center gap-1 text-xs text-primary underline"
                href="https://tarif.customs.uz"
                target="_blank"
                rel="noreferrer noopener"
              >
                {t('customsDuties.openSource')}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </div>
          )}

          {data && !isFetching && (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('customsDuties.columns.payment')}</TableHead>
                      <TableHead>{t('customsDuties.columns.rate')}</TableHead>
                      <TableHead>{t('customsDuties.columns.legalBasis')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.payments.map((payment, index) => (
                      <TableRow key={`${payment.code}-${index}`}>
                        <TableCell className="text-sm">{paymentLabel(payment)}</TableCell>
                        {/* Пусто у источника = «ставки в тарифе нет», а НЕ «0%». */}
                        <TableCell className="text-sm font-medium">{payment.rate || '—'}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {payment.legal_basis || '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {data.permits.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-medium">{t('customsDuties.permitsTitle')}</h3>
                  <ul className="space-y-2">
                    {data.permits.map((permit, index) => (
                      <li key={index} className="rounded-md border p-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{permit.document}</span>
                          <Badge variant="secondary">{permit.document_kind}</Badge>
                        </div>
                        <p className="mt-1 text-muted-foreground">{permit.organization}</p>
                        <p className="text-muted-foreground">{permit.legal_basis}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Подпись обязательна в каждом показе: это данные ГТК на дату, а не наша ставка. */}
              <div className="space-y-1 border-t pt-3">
                <p className="text-xs text-muted-foreground">
                  {t('customsDuties.disclaimer', {
                    date: new Date(data.fetched_at).toLocaleDateString(),
                  })}
                </p>
                <a
                  className="inline-flex items-center gap-1 text-xs text-primary underline"
                  href="https://tarif.customs.uz"
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {t('customsDuties.openSource')}
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
