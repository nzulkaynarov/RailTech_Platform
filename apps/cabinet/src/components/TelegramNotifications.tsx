import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BellRing, Check, MessageSquareText, Send } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError } from '@/api/portal';
import type { TelegramLink } from '@/api/portal';
import { useCreateTelegramLink, useSendTelegramTest, useTelegramStatus, useUnlinkTelegram } from '@/api/queries';
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { TelegramLinkButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useNow } from '@/hooks/useNow';
import { formatTime } from '@/lib/format';
import { toast } from '@/lib/toast';
import { useAppMode } from '@/session/mode';

/** Срок ссылки проверяется раз в секунду: «ссылка истекла» появляется вовремя, без перезагрузки. */
const EXPIRY_TICK_MS = 1000;

/**
 * Профиль → «Уведомления» (ADR-0023 п. 3, NOTIFY-1): контакт сам привязывает Telegram.
 *
 * «Подключить» выпускает одноразовую ссылку на бот (15 минут): на вебе — QR и кнопка, в Mini App — только кнопка.
 * Пока ссылка жива и экран открыт, статус опрашивается — привязку делает бот CRM, проекция приходит в ERP за секунды.
 * Привязан: строка «Telegram привязан · Отвязать» и «Отправить проверочное сообщение» (бот CRM пишет контакту; не чаще
 * раза в минуту — на 429 кнопка ждёт `Retry-After`). «Отвязать» — подтверждение по месту с «Что произойдёт»; статус
 * меняется, когда CRM отвяжет Telegram (тоже опрос).
 * `autoStart` — пришли с плашки «Подключить»: ссылка выпускается сразу.
 */
export function TelegramNotifications({ autoStart = false }: { autoStart?: boolean }) {
  const { t } = useTranslation();
  const mode = useAppMode();
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const now = useNow(link ? EXPIRY_TICK_MS : 0);
  const expired = link !== null && new Date(link.expires_at).getTime() <= now;
  const waitingLink = link !== null && !expired;
  const status = useTelegramStatus({ poll: waitingLink || unlinking });
  const create = useCreateTelegramLink();
  const unlink = useUnlinkTelegram();
  const linked = status.data?.linked ?? false;

  const issue = () =>
    create.mutate(undefined, {
      onSuccess: (issued) => setLink(issued),
      onError: (error) => toast.error(t(apiErrorKey(error))),
    });

  // Привязка или отключение пришли проекцией — ссылка больше не нужна, опрос останавливается.
  const prevLinked = useRef(linked);
  useEffect(() => {
    if (linked && !prevLinked.current && link) {
      setLink(null);
      toast.success(t('profile.notifications.done'));
    }
    if (!linked && prevLinked.current && unlinking) {
      setUnlinking(false);
      toast.success(t('profile.notifications.disconnected'));
    }
    prevLinked.current = linked;
  }, [linked, link, unlinking, t]);

  const started = useRef(false);
  const canIssue = status.data?.available === true && !status.data.linked;
  useEffect(() => {
    if (!autoStart || started.current || !canIssue) return;
    started.current = true;
    issue();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- выпуск один раз по приходу с плашки
  }, [autoStart, canIssue]);

  const onUnlink = () =>
    unlink.mutate(undefined, {
      onSuccess: (next) => {
        setConfirming(false);
        if (next.linked) setUnlinking(true);
        else toast.success(t('profile.notifications.disconnected'));
      },
      onError: (error) => toast.error(t(apiErrorKey(error))),
    });

  return (
    <Card id="notifications" className="scroll-mt-20 md:col-span-2">
      <CardHeader>
        <CardTitle>
          <h2 className="text-base">{t('profile.notifications.title')}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : status.isError ? (
          <p className="text-sm text-destructive" role="alert">
            {t(apiErrorKey(status.error))}
          </p>
        ) : (
          <>
            <StatusLine linked={linked} />
            {linked ? (
              unlinking ? (
                <p className="text-sm text-muted-foreground" aria-live="polite">
                  {t('profile.notifications.disconnecting')}
                </p>
              ) : confirming ? (
                <section
                  aria-labelledby="telegram-unlink-title"
                  className="flex flex-col gap-3 rounded-xl border border-border p-3.5"
                >
                  <h3 id="telegram-unlink-title" className="text-sm font-semibold">
                    {t('profile.notifications.confirmTitle')}
                  </h3>
                  <ConsequenceCallout text={t('profile.notifications.consequence')} />
                  <div className="flex flex-wrap gap-2">
                    <Button variant="destructive" onClick={onUnlink} disabled={unlink.isPending}>
                      {t('profile.notifications.confirm')}
                    </Button>
                    <Button variant="outline" onClick={() => setConfirming(false)} disabled={unlink.isPending}>
                      {t('common.cancel')}
                    </Button>
                  </div>
                </section>
              ) : (
                <LinkedActions onUnbind={() => setConfirming(true)} onNotLinked={() => void status.refetch()} />
              )
            ) : !status.data?.available ? (
              <p className="text-sm text-muted-foreground">{t('profile.notifications.unavailable')}</p>
            ) : waitingLink && link ? (
              <LinkPanel link={link} showQr={mode === 'web'} />
            ) : (
              <div className="flex flex-col gap-2">
                {expired ? <p className="text-sm text-muted-foreground">{t('profile.notifications.expired')}</p> : null}
                <Button className="self-start" onClick={issue} disabled={create.isPending}>
                  <Send aria-hidden="true" />
                  {create.isPending
                    ? t('profile.notifications.preparing')
                    : expired
                      ? t('profile.notifications.newLink')
                      : t('profile.notifications.connect')}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function StatusLine({ linked }: { linked: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-3">
      <div
        className={
          linked
            ? 'flex size-8 shrink-0 items-center justify-center rounded-full bg-success text-success-foreground'
            : 'flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-primary'
        }
      >
        {linked ? <Check className="size-4" aria-hidden="true" /> : <BellRing className="size-4" aria-hidden="true" />}
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="text-sm font-semibold">
          {linked ? t('profile.notifications.linked') : t('profile.notifications.notLinked')}
        </p>
        <p className="text-sm text-muted-foreground">
          {linked ? t('profile.notifications.linkedText') : t('profile.notifications.notLinkedText')}
        </p>
      </div>
    </div>
  );
}

/** Выпущенная ссылка: QR (только веб — в Mini App телефон уже в руке), кнопка «Открыть Telegram», срок и ожидание. */
function LinkPanel({ link, showQr }: { link: TelegramLink; showQr: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
      {showQr ? (
        // QR — изображение для камеры: тёмные модули на светлом поле с «тихой зоной» по стандарту (marginSize),
        // в тёмной теме тоже, поэтому цвета — по умолчанию библиотеки, а не токены темы.
        <div className="self-center overflow-hidden rounded-xl border border-border sm:self-auto">
          <QRCodeSVG
            value={link.url}
            size={184}
            marginSize={2}
            role="img"
            aria-label={t('profile.notifications.qrLabel')}
            title={t('profile.notifications.qrLabel')}
          />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-col gap-3">
        <p className="text-sm">{showQr ? t('profile.notifications.scanQr') : t('profile.notifications.pressStart')}</p>
        <TelegramLinkButton href={link.url} className="self-start">
          <Send aria-hidden="true" />
          {t('profile.notifications.openTelegram')}
        </TelegramLinkButton>
        <p className="text-xs text-muted-foreground">
          {t('profile.notifications.validUntil', { time: formatTime(link.expires_at) })}
        </p>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {t('profile.notifications.waiting')}
        </p>
      </div>
    </div>
  );
}

/** Раз в секунду, пока идёт отсчёт «можно повторить через N с». */
const RETRY_TICK_MS = 1000;

/** Привязанный Telegram: «Telegram привязан · Отвязать» и проверочное сообщение с отсчётом после 429. */
function LinkedActions({ onUnbind, onNotLinked }: { onUnbind: () => void; onNotLinked: () => void }) {
  const { t } = useTranslation();
  const send = useSendTelegramTest();
  const [retryUntil, setRetryUntil] = useState<number | null>(null);
  const now = useNow(retryUntil !== null ? RETRY_TICK_MS : 0);
  const waitSeconds = retryUntil !== null ? Math.ceil((retryUntil - now) / 1000) : 0;
  const waiting = waitSeconds > 0;
  // Отсчёт кончился — секундный таймер больше не нужен (сброс по таймауту, а не эффектом).
  const resetTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(resetTimer.current), []);

  const onSend = () =>
    send.mutate(undefined, {
      onSuccess: () => toast.success(t('profile.notifications.testSent')),
      onError: (error) => {
        if (isPortalApiError(error, 429)) {
          const waitMs = (error.retryAfter ?? 60) * 1000;
          setRetryUntil(Date.now() + waitMs);
          window.clearTimeout(resetTimer.current);
          resetTimer.current = window.setTimeout(() => setRetryUntil(null), waitMs);
          return;
        }
        if (isPortalApiError(error, 409)) onNotLinked();
        toast.error(t(apiErrorKey(error)));
      },
    });

  return (
    <div className="flex flex-col gap-3">
      <p className="flex flex-wrap items-center gap-x-1.5 text-sm">
        <span>{t('profile.notifications.boundLine')}</span>
        <span aria-hidden="true">·</span>
        <Button variant="link" className="h-auto p-0" onClick={onUnbind}>
          {t('profile.notifications.unbind')}
        </Button>
      </p>
      <div className="flex flex-col gap-1.5">
        <Button variant="outline" className="self-start" onClick={onSend} disabled={send.isPending || waiting}>
          <MessageSquareText aria-hidden="true" />
          {send.isPending ? t('profile.notifications.sendingTest') : t('profile.notifications.sendTest')}
        </Button>
        {waiting ? (
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {t('profile.notifications.testRetry', { seconds: waitSeconds })}
          </p>
        ) : null}
      </div>
    </div>
  );
}
