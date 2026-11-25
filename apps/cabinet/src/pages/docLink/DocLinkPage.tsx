import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, LogOut } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError, logout as signOut, type DocLinkAvailability, type DocLinkView } from '@/api/portal';
import { keys, useActOnDocLink, useDocLink } from '@/api/queries';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DocumentNotReadyError, downloadDocLinkPdf } from '@/lib/download';
import { formatDate, formatMoney } from '@/lib/format';
import { toast } from '@/lib/toast';
import { LegalAcceptancePage } from '@/pages/legal/LegalAcceptancePage';
import { ME_QUERY_KEY } from '@/session/session';
import { useMe, useSetSession } from '@/session/useMe';
import { DocLinkDialog, type DocLinkIntent } from './DocLinkDialog';
import { DocLinkExtra } from './DocLinkExtra';
import { DocLinkLines } from './DocLinkLines';
import { DocLinkPartnerLines } from './DocLinkPartnerLines';
import { GuestShell } from './GuestShell';

type GoneKind = 'revoked' | 'expired' | 'superseded' | 'notFound';

const GONE_BY_CODE: Record<string, GoneKind> = {
  DOC_LINK_REVOKED: 'revoked',
  DOC_LINK_EXPIRED: 'expired',
  DOC_LINK_SUPERSEDED: 'superseded',
};

/** Ссылка ничего не показывает, кроме причины (ДК-1); неизвестный токен — всегда «не найдена» (404, без намёков). */
function goneKind(error: unknown): GoneKind | null {
  if (isPortalApiError(error, 410)) return GONE_BY_CODE[error.code] ?? 'notFound';
  if (isPortalApiError(error, 404)) return 'notFound';
  return null;
}

/**
 * `/d/<токен>` — документ по ссылке из письма (ДК-1, ДК-2, ADR-0030): гость видит один документ — состав, ключевые
 * факты и «Скачать PDF»; любое действие (принять, вернуть, вопрос, открыть Кабинет) — один диалог кода на адрес
 * получателя. Код — это вход: после него открыта сессия контакта, при первом входе показывается принятие оферты и
 * политики (ДВ-5), и начатое действие выполняется без повторного нажатия. Вошедший контакт той же компании кода не
 * видит; сессия другой компании — гостевой вид и предложение сменить вход.
 */
export function DocLinkPage() {
  const { token = '' } = useParams();
  const { t } = useTranslation();
  const doc = useDocLink(token);

  if (doc.isPending) {
    return (
      <GuestShell title={t('docLink.title')}>
        <div className="flex flex-1 items-center justify-center" role="status" aria-live="polite">
          <Loader2 className="size-8 motion-safe:animate-spin text-primary" aria-hidden="true" />
          <span className="sr-only">{t('app.loading')}</span>
        </div>
      </GuestShell>
    );
  }
  if (doc.isError) {
    const gone = goneKind(doc.error);
    return (
      <GuestShell title={gone ? t(`docLink.gone.${gone}.title`) : t('common.error')}>
        <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 rounded-lg border bg-card p-6 text-center">
          <h1 className="text-xl font-semibold">{gone ? t(`docLink.gone.${gone}.title`) : t('common.error')}</h1>
          <p className="text-sm text-muted-foreground">
            {gone ? t(`docLink.gone.${gone}.text`) : t(apiErrorKey(doc.error))}
          </p>
          {gone ? null : <Button onClick={() => void doc.refetch()}>{t('common.retry')}</Button>}
        </div>
      </GuestShell>
    );
  }
  return <DocLinkBody token={token} doc={doc.data} />;
}

type Phase = 'idle' | 'dialog' | 'legal';

function DocLinkBody({ token, doc }: { token: string; doc: DocLinkView }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setSession = useSetSession();
  // Сменить вход: прежняя сессия закрыта, документ запрашивается заново — уже гостем (кэш документа `useLogout` не стирает)
  const logout = useMutation({
    mutationFn: signOut,
    onSettled: () => {
      queryClient.setQueryData(ME_QUERY_KEY, null);
      void queryClient.invalidateQueries({ queryKey: keys.docLink(token) });
    },
  });
  const me = useMe({ enabled: doc.session === 'member' }).data;
  const act = useActOnDocLink(token);
  const [intent, setIntent] = useState<DocLinkIntent | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [downloading, setDownloading] = useState<'idle' | 'loading' | 'pending'>('idle');
  const member = doc.session === 'member';
  const decideOpen = doc.state === 'open';
  const kind = doc.kind;
  // ДК-5: запрос цены и заказ поставщику — партнёрская проекция (его позиции и цены), действия — ответить и подтвердить
  const partner = kind === 'price_request' || kind === 'supplier_order';

  const finishOpen = () => navigate('/');
  const run = (next: DocLinkIntent, text: string) => {
    if (next.action === 'open') {
      finishOpen();
      return;
    }
    act.mutate(
      { action: next.action, ...(text ? { text } : {}), ...(next.extra ? { extra: next.extra } : {}) },
      {
        onSuccess: () => {
          toast.success(t(`docLink.done.${next.action}`, { context: kind }));
          setPhase('idle');
          setIntent(null);
        },
        onError: (error) => {
          if (isPortalApiError(error, 403) && error.code === 'LEGAL_ACCEPTANCE_REQUIRED') {
            void queryClient.invalidateQueries({ queryKey: ['me'] });
            setPhase('legal');
          }
        },
      },
    );
  };

  const start = (next: DocLinkIntent) => {
    act.reset();
    setIntent(next);
    if (member && next.action === 'open' && !me?.legal_pending) {
      finishOpen();
      return;
    }
    setPhase(member && me?.legal_pending ? 'legal' : 'dialog');
  };

  // После принятия оферты (ДВ-5): подтверждённое кодом действие продолжается само; вошедшему, который ещё не подтверждал
  // действие или не писал текст, диалог открывается снова.
  const accepted = phase === 'legal' && me?.legal_pending === false;
  const reopenDialog = accepted && intent !== null && intent.action !== 'open' && !intent.verified;
  const view: Phase = phase === 'legal' ? (!accepted ? 'legal' : reopenDialog ? 'dialog' : 'idle') : phase;
  const resumed = useRef(false);
  useEffect(() => {
    if (phase !== 'legal') resumed.current = false;
    else if (accepted && intent && !reopenDialog && !resumed.current) {
      resumed.current = true;
      run(intent, intent.text ?? '');
    }
  }, [phase, accepted]); // eslint-disable-line react-hooks/exhaustive-deps -- run и intent читаются в момент принятия

  if (view === 'legal') return <LegalAcceptancePage />;

  const download = async () => {
    setDownloading('loading');
    try {
      await downloadDocLinkPdf(token, `${doc.number}.pdf`, { onPending: () => setDownloading('pending') });
    } catch (error) {
      if (error instanceof DocumentNotReadyError) toast.info(t('docLink.stillPreparing'));
      else toast.error(t(apiErrorKey(error)));
    } finally {
      setDownloading('idle');
    }
  };

  const reasonText = (availability: DocLinkAvailability) =>
    availability.reason && !availability.allowed && availability.reason !== 'no_actions'
      ? t(`docLink.reason.${availability.reason}`, { context: partner ? 'partner' : undefined })
      : null;
  const blocked = decideOpen ? reasonText(doc.decide) : null;
  const noContact = doc.decide.reason === 'no_contact';
  const other = doc.session === 'other_company';
  const name = me?.contact.name ?? '';
  // Действия вида документа (ДК-3): КП — три, договор — «подписать», акт — «принять» и «вернуть», счёт — ни одного
  const offered: readonly string[] = doc.actions ?? ['accept', 'reject', 'question'];
  const buttons = (
    [
      { action: 'accept', variant: 'default' },
      { action: 'answer', variant: 'default' },
      { action: 'confirm', variant: 'default' },
      { action: 'reject', variant: 'outline' },
      { action: 'question', variant: 'outline' },
    ] as const
  ).filter(({ action }) => offered.includes(action));
  const title = t('docLink.docTitle', { number: doc.number, context: kind });
  const money = (value: DocLinkView['total']) =>
    kind === 'quote' || kind === 'invoice' ? t('docLink.withVat', { amount: formatMoney(value) }) : formatMoney(value);

  return (
    <GuestShell title={title} note={t('docLink.header', { email: doc.recipient_hint })}>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          {partner ? <DocLinkPartnerLines doc={doc} /> : doc.lines.length > 0 ? <DocLinkLines doc={doc} /> : <DocLinkExtra doc={doc} />}
          <div>
            <Button
              type="button"
              variant="outline"
              disabled={downloading !== 'idle'}
              onClick={() => void download()}
              aria-label={t('docLink.downloadNamed', { number: doc.number, context: kind })}
            >
              {downloading === 'idle' ? <Download aria-hidden="true" /> : <Loader2 className="motion-safe:animate-spin" aria-hidden="true" />}
              {downloading === 'pending' ? t('docLink.preparing') : t('docLink.download')}
            </Button>
          </div>
        </div>

        <section aria-labelledby="doc-card-title" className="order-first flex flex-col gap-4 rounded-lg border bg-card p-4 sm:p-5 lg:order-none">
          <h1 id="doc-card-title" className="text-lg font-semibold">
            {title}
          </h1>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t('docLink.facts.from')}</dt>
            <dd className="break-words">{doc.from_name}</dd>
            <dt className="text-muted-foreground">{t('docLink.facts.to')}</dt>
            <dd className="break-words">{doc.to_name}</dd>
            {kind === 'price_request' ? null : (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.total')}</dt>
                <dd className="font-medium tabular-nums">{money(doc.total)}</dd>
              </>
            )}
            {kind === 'supplier_order' ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.expectedDate')}</dt>
                <dd>{doc.expected_date ? formatDate(doc.expected_date) : '—'}</dd>
                {doc.confirmed_at ? (
                  <>
                    <dt className="text-muted-foreground">{t('docLink.facts.confirmedAt')}</dt>
                    <dd>{formatDate(doc.confirmed_at)}</dd>
                  </>
                ) : null}
              </>
            ) : null}
            {kind === 'price_request' && doc.answered_at ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.answeredAt')}</dt>
                <dd>{formatDate(doc.answered_at)}</dd>
              </>
            ) : null}
            {kind === 'quote' ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.validUntil')}</dt>
                <dd>{formatDate(doc.valid_until)}</dd>
              </>
            ) : null}
            {kind === 'invoice' ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.dueDate')}</dt>
                <dd>{formatDate(doc.due_date)}</dd>
                {doc.balance_due ? (
                  <>
                    <dt className="text-muted-foreground">{t('docLink.facts.balance')}</dt>
                    <dd className="font-medium tabular-nums">{formatMoney(doc.balance_due)}</dd>
                  </>
                ) : null}
              </>
            ) : null}
            {kind === 'contract' && doc.signed_at ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.signedAt')}</dt>
                <dd>{formatDate(doc.signed_at)}</dd>
              </>
            ) : null}
            {kind === 'act' && doc.issued_at ? (
              <>
                <dt className="text-muted-foreground">{t('docLink.facts.issuedAt')}</dt>
                <dd>{formatDate(doc.issued_at)}</dd>
              </>
            ) : null}
          </dl>

          {other ? (
            <Alert>
              <AlertDescription className="flex flex-col gap-2">
                <span className="font-medium">{t('docLink.otherCompany.title')}</span>
                <span>{t('docLink.otherCompany.text')}</span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  disabled={logout.isPending}
                  onClick={() => logout.mutate()}
                >
                  <LogOut aria-hidden="true" />
                  {t('docLink.otherCompany.signOut')}
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          {!decideOpen ? (
            <p className="rounded-md bg-muted px-3 py-2 text-sm" role="status">
              {t(`docLink.state.${doc.state}`, { context: kind })}
            </p>
          ) : noContact ? (
            // В-1: адрес получателя не контакт компании — гость одного документа: ни действий, ни входа
            <p className="text-sm text-muted-foreground" role="status">
              {t('docLink.guestNote')}
            </p>
          ) : buttons.length === 0 ? null : (
            <div className="flex flex-col gap-2">
              {buttons.map(({ action, variant }) => (
                <Button
                  key={action}
                  type="button"
                  variant={variant}
                  disabled={!doc.decide.allowed || act.isPending}
                  aria-describedby={blocked ? 'doc-blocked' : undefined}
                  onClick={() => start({ action })}
                >
                  {t(`docLink.actions.${action}`, { context: kind })}
                </Button>
              ))}
              {blocked ? (
                <p id="doc-blocked" className="text-sm text-muted-foreground">
                  {blocked}
                </p>
              ) : null}
            </div>
          )}

          {act.isError && view === 'idle' ? (
            <Alert variant="destructive">
              <AlertDescription>{t(apiErrorKey(act.error))}</AlertDescription>
            </Alert>
          ) : null}
          {act.isPending && view === 'idle' ? (
            <p className="text-sm text-muted-foreground" role="status">
              {t('docLink.dialog.working')}
            </p>
          ) : null}

          {noContact ? null : (
            <>
              <Button type="button" variant="ghost" disabled={other} onClick={() => start({ action: 'open' })}>
                {t('docLink.actions.open')}
              </Button>
              <p className="text-sm text-muted-foreground">
                {member ? t('docLink.memberNote', { name }) : t('docLink.codeNote', { email: doc.recipient_hint })}
              </p>
            </>
          )}
          <p className="text-sm text-muted-foreground">{t('docLink.linkUntil', { date: formatDate(doc.link_expires_at) })}</p>
        </section>
      </div>

      {view === 'dialog' && intent ? (
        <DocLinkDialog
          token={token}
          doc={doc}
          intent={intent}
          signedIn={member}
          pending={act.isPending}
          actionError={act.error}
          onClose={() => {
            setPhase('idle');
            setIntent(null);
          }}
          onSignedIn={(signedInMe, text, extra) => {
            setSession(signedInMe);
            queryClient.setQueryData<DocLinkView>(keys.docLink(token), { ...doc, session: 'member' });
            const next = { ...intent, text, extra, verified: true };
            setIntent(next);
            if (signedInMe.legal_pending) setPhase('legal');
            else run(next, text);
          }}
          onConfirmed={(text, extra) => run({ ...intent, text, extra }, text)}
        />
      ) : null}
    </GuestShell>
  );
}
