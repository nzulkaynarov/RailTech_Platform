import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RotateCw } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError, type DocLinkAction, type DocLinkView, type Me } from '@/api/portal';
import { useRequestDocLinkCode, useVerifyDocLinkCode } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useNow } from '@/hooks/useNow';
import { formatMoney } from '@/lib/format';
import { codeDigits } from '@/pages/auth/loginCode';

/** `verified` — действие подтверждено кодом (текст уже написан): после оферты оно продолжается без нового диалога. */
export type DocLinkIntent = { action: DocLinkAction | 'open'; text?: string; verified?: boolean };

const TEXT_MAX = 2000;

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
  /** Код принят: сессия открыта; текст возвращается, чтобы действие продолжилось. */
  onSignedIn: (me: Me, text: string) => void;
  /** Вошедший подтвердил действие. */
  onConfirmed: (text: string) => void;
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
  const needsText = intent.action === 'reject' || intent.action === 'question';

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

  const submit = () => {
    setMessage(null);
    if (needsText && !text.trim()) {
      setMessage(t('common.reasonRequired'));
      return;
    }
    if (!needsCode) {
      onConfirmed(text.trim());
      return;
    }
    if (code.length !== 6) {
      setMessage(t('docLink.dialog.codeShort'));
      return;
    }
    verify.mutate(code, { onSuccess: (me) => onSignedIn(me, text.trim()) });
  };

  const title = needsCode
    ? t('docLink.dialog.title')
    : intent.action === 'accept'
      ? t('docLink.dialog.memberTitle', { context: doc.kind })
      : t(`docLink.actions.${intent.action}`, { context: doc.kind });
  const email = doc.recipient_hint;
  // ДК-4: код ушёл и в Telegram получателя — диалог говорит, куда именно, и не отсылает к папке «Спам»
  const viaTelegram = request.data?.channels?.includes('telegram') ?? false;
  const description = needsCode
    ? request.isPending
      ? t('docLink.dialog.sending')
      : t(viaTelegram ? 'docLink.dialog.sentTelegram' : 'docLink.dialog.sent', { email: request.data?.sent_to ?? email, minutes: 10 })
    : intent.action === 'accept'
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
      {needsText ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor={textId}>{t(intent.action === 'reject' ? 'docLink.dialog.remarks' : 'docLink.dialog.question')}</Label>
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
