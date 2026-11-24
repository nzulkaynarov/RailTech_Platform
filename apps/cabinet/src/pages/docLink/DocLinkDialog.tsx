import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RotateCw } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError, type DocLinkAction, type DocLinkActExtra, type DocLinkView, type Me } from '@/api/portal';
import { useRequestDocLinkCode, useVerifyDocLinkCode } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DateField } from '@/components/DateField';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useNow } from '@/hooks/useNow';
import { formatMoney } from '@/lib/format';
import { codeDigits } from '@/pages/auth/loginCode';

/** `verified` — действие подтверждено кодом (текст уже написан): после оферты оно продолжается без нового диалога. */
export type DocLinkIntent = { action: DocLinkAction | 'open'; text?: string; extra?: DocLinkActExtra; verified?: boolean };

const TEXT_MAX = 2000;
const PRICE_RE = /^\d+(\.\d{1,2})?$/;
const CURRENCY_RE = /^[A-Z]{3}$/;

/** `0:45` — сколько ждать до повторной отправки. */
function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * Диалог действия по ссылке документа (ДК-2): гость вводит код, который ушёл на адрес получателя, — код открывает
 * сессию контакта, и действие продолжается без повторного нажатия. Адрес в диалоге не вводится и не меняется. Вошедший
 * контакт кода не видит: «Принять» просит подтверждения (необратимо), остальные действия — только текст.
 * Код запрашивается один раз при открытии диалога, повтор — через `resend_after` секунд, которые назвал сервер.
 */
export function DocLinkDialog({
  token,
  doc,
  intent,
  signedIn,
  pending,
  actionError,
  onClose,
  onSignedIn,
  onConfirmed,
}: {
  token: string;
  doc: DocLinkView;
  intent: DocLinkIntent;
  /** Есть сессия того же контакта или коллеги компании — код не нужен. */
  signedIn: boolean;
  /** Действие выполняется (после кода или подтверждения). */
  pending: boolean;
  actionError: unknown;
  onClose: () => void;
  /** Код принят: сессия открыта; текст и данные действия возвращаются, чтобы оно продолжилось. */
  onSignedIn: (me: Me, text: string, extra: DocLinkActExtra) => void;
  /** Вошедший подтвердил действие. */
  onConfirmed: (text: string, extra: DocLinkActExtra) => void;
}) {
  const { t } = useTranslation();
  const codeId = useId();
  const textId = useId();
  const [text, setText] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [resendAfter, setResendAfter] = useState(45);
  const now = useNow(1000);
  const request = useRequestDocLinkCode(token);
  const verify = useVerifyDocLinkCode(token);
  const requested = useRef(false);
  // Решается при открытии: код открывает сессию, а диалог не должен на лету превратиться в «подтверждение вошедшего»
  const [needsCode] = useState(() => !signedIn);
  const needsText = intent.action === 'reject' || intent.action === 'question' || intent.action === 'answer';
  // ДК-5: ответ партнёра на запрос цены — цена и срок по строкам; подтверждение заказа без даты в заказе — дата партнёра
  const [prices, setPrices] = useState<Record<number, string>>({});
  const [leads, setLeads] = useState<Record<number, string>>({});
  const [currency, setCurrency] = useState('UZS');
  const [expected, setExpected] = useState('');
  const needsDate = intent.action === 'confirm' && !doc.expected_date;

  const sendCode = request.mutate;
  useEffect(() => {
    if (!needsCode || requested.current) return;
    requested.current = true;
    sendCode(undefined, {
      onSuccess: (sent) => {
        setSentAt(Date.now());
        setResendAfter(sent.resend_after);
      },
      onError: (error) => {
        // «Слишком рано» — код уже отправлен (вторая вкладка, повторное открытие): ждём названный сервером срок
        if (isPortalApiError(error, 429) && error.code === 'CODE_RESEND_TOO_SOON') {
          setSentAt(Date.now());
          setResendAfter(error.retryAfter ?? 45);
        }
      },
    });
  }, [needsCode, sendCode]);

  const wait = sentAt === null ? 0 : Math.max(0, Math.ceil((sentAt + resendAfter * 1000 - now) / 1000));
  const resend = () => {
    setCode('');
    verify.reset();
    request.mutate(undefined, {
      onSuccess: (sent) => {
        setSentAt(Date.now());
        setResendAfter(sent.resend_after);
      },
    });
  };

  /** Данные действия или текст ошибки: цены — только заполненные, валюта обязательна с ценами. */
  const collect = (): { extra: DocLinkActExtra } | { problem: string } => {
    if (intent.action === 'confirm') {
      if (needsDate && !expected) return { problem: t('docLink.dialog.dateRequired') };
      return { extra: needsDate ? { expected_date: expected } : {} };
    }
    if (intent.action !== 'answer') return { extra: {} };
    const rows = (doc.partner_lines ?? [])
      .map((line) => {
        const price = (prices[line.id] ?? '').trim().replace(',', '.');
        const lead = (leads[line.id] ?? '').trim();
        return { id: line.id, price, lead };
      })
      .filter((row) => row.price !== '');
    if (rows.some((row) => !PRICE_RE.test(row.price) || Number(row.price) <= 0)) {
      return { problem: t('pages.partnerOrders.dialogs.priceInvalid') };
    }
    if (rows.some((row) => row.lead !== '' && (!/^\d{1,4}$/.test(row.lead) || Number(row.lead) > 3650))) {
      return { problem: t('docLink.dialog.leadInvalid') };
    }
    const code3 = currency.trim().toUpperCase();
    if (rows.length > 0 && !CURRENCY_RE.test(code3)) return { problem: t('pages.partnerOrders.dialogs.currencyInvalid') };
    return {
      extra:
        rows.length > 0
          ? {
              currency: code3,
              prices: rows.map((row) => ({ id: row.id, unit_price: row.price, ...(row.lead !== '' ? { lead_days: Number(row.lead) } : {}) })),
            }
          : {},
    };
  };

  const submit = () => {
    setMessage(null);
    if (needsText && !text.trim()) {
      setMessage(t(intent.action === 'answer' ? 'docLink.dialog.noteRequired' : 'common.reasonRequired'));
      return;
    }
    const collected = collect();
    if ('problem' in collected) {
      setMessage(collected.problem);
      return;
    }
    if (!needsCode) {
      onConfirmed(text.trim(), collected.extra);
      return;
    }
    if (code.length !== 6) {
      setMessage(t('docLink.dialog.codeShort'));
      return;
    }
    verify.mutate(code, { onSuccess: (me) => onSignedIn(me, text.trim(), collected.extra) });
  };

  const title = needsCode
    ? t('docLink.dialog.title')
    : intent.action === 'accept' || intent.action === 'confirm'
      ? t('docLink.dialog.memberTitle', { context: doc.kind })
      : t(`docLink.actions.${intent.action}`, { context: doc.kind });
  const email = doc.recipient_hint;
  // ДК-4: код ушёл и в Telegram получателя — диалог говорит, куда именно, и не отсылает к папке «Спам»
  const viaTelegram = request.data?.channels?.includes('telegram') ?? false;
  const description = needsCode
    ? request.isPending
      ? t('docLink.dialog.sending')
      : t(viaTelegram ? 'docLink.dialog.sentTelegram' : 'docLink.dialog.sent', { email: request.data?.sent_to ?? email, minutes: 10 })
    : intent.action === 'accept' || intent.action === 'confirm'
      ? t('docLink.dialog.memberText', { total: formatMoney(doc.total), context: doc.kind })
      : t('docLink.docTitle', { number: doc.number, context: doc.kind });

  return (
    <ActionDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      description={description}
      confirmLabel={t(`docLink.actions.${intent.action}`, { context: doc.kind })}
      pending={pending || verify.isPending}
      error={verify.error ?? actionError}
      message={message}
      onSubmit={submit}
    >
      {intent.action === 'answer' ? (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium">{t('pages.partnerOrders.dialogs.pricesLegend')}</legend>
          <p className="text-xs text-muted-foreground">{t('pages.partnerOrders.dialogs.pricesHint')}</p>
          {(doc.partner_lines ?? []).map((line) => (
            <div key={line.id} className="flex flex-col gap-1 border-b pb-2 last:border-b-0">
              <span className="text-sm break-words">{line.name}</span>
              <div className="flex items-center gap-2">
                <Label htmlFor={`${textId}-price-${line.id}`} className="sr-only">
                  {t('docLink.dialog.priceFor', { name: line.name })}
                </Label>
                <Input
                  id={`${textId}-price-${line.id}`}
                  inputMode="decimal"
                  placeholder={t('docLink.dialog.pricePlaceholder')}
                  className="w-32 tabular-nums"
                  value={prices[line.id] ?? ''}
                  onChange={(event) => setPrices((prev) => ({ ...prev, [line.id]: event.target.value }))}
                />
                <Label htmlFor={`${textId}-lead-${line.id}`} className="sr-only">
                  {t('docLink.dialog.leadFor', { name: line.name })}
                </Label>
                <Input
                  id={`${textId}-lead-${line.id}`}
                  inputMode="numeric"
                  placeholder={t('docLink.dialog.leadPlaceholder')}
                  className="w-28 tabular-nums"
                  value={leads[line.id] ?? ''}
                  onChange={(event) => setLeads((prev) => ({ ...prev, [line.id]: event.target.value }))}
                />
              </div>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Label htmlFor={`${textId}-currency`} className="flex-1 text-sm font-normal">
              {t('pages.partnerOrders.dialogs.currencyLabel')}
            </Label>
            <Input
              id={`${textId}-currency`}
              maxLength={3}
              className="w-28 uppercase"
              value={currency}
              onChange={(event) => setCurrency(event.target.value)}
            />
          </div>
        </fieldset>
      ) : null}
      {needsDate ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${textId}-date`}>{t('pages.partnerOrders.dialogs.expectedDateLabel')}</Label>
          <DateField id={`${textId}-date`} value={expected} onChange={(value) => setExpected(value ?? '')} />
        </div>
      ) : null}
      {needsText ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor={textId}>
            {intent.action === 'answer'
              ? `${t('pages.partnerOrders.dialogs.responseNoteLabel')} *`
              : t(intent.action === 'reject' ? 'docLink.dialog.remarks' : 'docLink.dialog.question')}
          </Label>
          <Textarea id={textId} rows={4} maxLength={TEXT_MAX} value={text} onChange={(event) => setText(event.target.value)} />
        </div>
      ) : null}
      {needsCode ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor={codeId}>{t(viaTelegram ? 'docLink.dialog.labelTelegram' : 'docLink.dialog.label')}</Label>
            <Input
              id={codeId}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              placeholder="000000"
              className="text-center text-lg tracking-[0.4em] tabular-nums"
              value={code}
              onChange={(event) => setCode(codeDigits(event.target.value))}
              aria-invalid={verify.isError || undefined}
            />
          </div>
          <p className="text-sm text-muted-foreground">{t(viaTelegram ? 'docLink.dialog.notInMail' : 'docLink.dialog.spam')}</p>
          <Button type="button" variant="outline" size="sm" className="self-start" disabled={wait > 0 || request.isPending} onClick={resend}>
            <RotateCw aria-hidden="true" />
            {wait > 0 ? t('docLink.dialog.resendIn', { time: clock(wait) }) : t('docLink.dialog.resend')}
          </Button>
          {request.isError && !(isPortalApiError(request.error, 429) && request.error.code === 'CODE_RESEND_TOO_SOON') ? (
            <Alert variant="destructive">
              <AlertDescription>{t(apiErrorKey(request.error))}</AlertDescription>
            </Alert>
          ) : null}
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{t('docLink.dialog.legal')}</p>
        </div>
      ) : null}
    </ActionDialog>
  );
}
