import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Calculator, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { QuoteStatus, DealStage } from '@/lib/codes';
import { useIsSoloTeam, useHasCompanyPermission } from '@/hooks/useCapabilities';
import {
  useDeal, useChangeDealStage, useSendQuoteToClient,
  useClaimDeal, useReleaseDeal, useTakeAndPrepareQuote, useSubmitQuoteForReview,
} from '@/hooks/useCRM';
import { translateApiError, extractApiErrorCode } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { DealAttachmentsPanel } from '@/components/Sourcing/DealAttachmentsPanel';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { DealTimeline } from '@/components/CRM/DealTimeline';
import { DealDocumentsCard } from '@/components/CRM/DealDocumentsCard';
import { DealChainCard } from '@/components/CRM/DealChainCard';
import { DealMarginDeviationCard } from '@/components/CRM/DealMarginDeviationCard';
import { RequestHeader } from './RequestHeader';
import { RequestActionBar } from './RequestActionBar';
import { QuoteView } from './QuoteView';
import { needsQuoteWork } from '@/lib/waiting';

/**
 * Карточка сделки бэк-офиса. Reached via the `request-detail/<dealId>` hash route (Deals list,
 * Kanban, notifications, document links). State is React Query throughout (useDeal + useCRM).
 *
 * Покупательская сторона карточки (правка заявки, одобрение/отклонение КП, панель «что дальше»
 * после акцепта, проверка «КП vs заявка») удалена в M1-ERP-02 волна 3: клиент работает в Cabinet,
 * в ERP входят только сотрудники бэк-офиса.
 *
 * A SOLO deal (Wave E calculator draft) carries `deal.company === null` — a legitimate state.
 * Every counterparty field is null-guarded (see RequestHeader) and the documents block renders
 * regardless of a client, so the back office is never dead-ended on its own solo deal.
 *
 * Split into ./request-detail/* (god-component 500-line limit): RequestHeader, RequestActionBar,
 * QuoteView (priced КП).
 */
export function RequestDetailPage({ dealId, onBack }: { dealId: number; onBack: () => void }) {
  const { t } = useTranslation();
  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const [generateQuoteOpen, setGenerateQuoteOpen] = useState(false);

  const changeStage = useChangeDealStage();
  const sendQuote = useSendQuoteToClient();
  const claimMut = useClaimDeal();
  const releaseMut = useReleaseDeal();
  const takeMut = useTakeAndPrepareQuote();
  const submitReviewMut = useSubmitQuoteForReview();
  const isSoloTeam = useIsSoloTeam();
  // Кнопки действий — по правам из /me (D-03, FIX-58): те же коды, что проверяет сервер на эндпоинтах.
  // Нет права — кнопки нет (Наблюдатель видит карточку, но не действия, которые закончатся 403).
  const canManageDeal = useHasCompanyPermission('deal.manage');
  const canEditPricing = useHasCompanyPermission('quote.edit_pricing');
  const canBuildQuoteLifecycle = useHasCompanyPermission('quote.build');
  const canSendQuote = useHasCompanyPermission('quote.send');

  if (isLoading && !deal) return <LoadingSkeleton />;
  // A failed fetch (404 / no-access / network) must read as an error with a way out — not a bare
  // "no data" that looks like an empty deal.
  if (isError && !deal) return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium">{t('common.loadError')}</p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => refetch()}>{t('common.retry')}</Button>
        <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft className="mr-1.5 h-4 w-4" />{t('requestDetailActions.backToRequests')}</Button>
      </div>
    </div>
  );
  if (!deal) return <div className="p-8 text-center text-muted-foreground">{t('pages.common.noData')}</div>;

  const quote = deal.active_quote ?? deal.quotes?.[deal.quotes.length - 1] ?? null;

  const isDraft = deal.stage_code === DealStage.DRAFT;
  const isSourcing = deal.stage_code === DealStage.SOURCING;
  const isCalculating = deal.stage_code === DealStage.CALCULATING;
  const isWon = deal.stage_code === DealStage.CLOSED_WON || deal.stage_code === DealStage.CONTRACT_SIGNED;
  // W2 «одна кнопка» (one-click-quotation): claim + стадия + предзаполненный КП одним действием.
  //
  // Условие «КП ещё нет» выражается через `needsQuoteWork`, а НЕ через `!active_quote`: позиции
  // заявки клиента физически лежат в DRAFT-КП, поэтому `active_quote` есть у каждой
  // отправленной заявки — и кнопка волны W2 не показывалась НИКОГДА (проход глазами 03-08, тот
  // же корень, что у плитки «Заявки без КП»).
  const quoteNotStarted = needsQuoteWork(deal);
  const canTakeAndPrepare = quoteNotStarted && canEditPricing;
  // Q5 (устранение рассинхрона гейтов): «Сформировать КП» — резервный ручной путь, НЕ показываем
  // рядом с одной кнопкой W2 (иначе две кнопки создания на одной стадии сбивают с толку).
  const canBuildQuote = (isSourcing || isCalculating) && quoteNotStarted && !canTakeAndPrepare && canEditPricing;
  // «КП уже собирают» — тоже по состоянию: пустой черновик-хранилище позиций за КП не считается.
  const hasQuote = !!deal.active_quote && !quoteNotStarted;
  // Q4: send a DRAFT КП into internal review straight from the request card (no builder detour).
  // The server re-runs every gate; a sole-approver КП auto-approves → «Отправить» surfaces next.
  const canSubmitForReview = deal.active_quote?.status_code === QuoteStatus.DRAFT && canBuildQuoteLifecycle;
  // The client rejected the КП → offer a primary "new version" action (perform_create auto-increments).
  const canBuildNewVersion = deal.active_quote?.status_code === QuoteStatus.REJECTED && canEditPricing;
  // Wave B2 (auto-claim): a solo team has no queue to hand out, so hide «Взять в работу» entirely.
  const canClaim = deal.assigned_to == null && !isSoloTeam && canManageDeal;
  // Право на возврат считает СЕРВЕР (владелец записи ИЛИ team.manage) — фронт его не выводит.
  const canRelease = !!deal.viewer_can_release && canManageDeal;
  const openQuoteBuilder = () => { window.location.hash = `deal-quote/${deal.id}`; };

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Sending a below-floor КП needs a written justification, and that confirm-with-reason flow lives
  // only in the canonical builder (DealQuotePage, S7a). Rather than dead-end the user on a
  // BELOW_FLOOR_JUSTIFICATION_REQUIRED toast here, route them to the builder to finish the send.
  const handleSendQuote = async () => {
    if (!quote) return;
    try {
      await sendQuote.mutateAsync({ id: quote.id });
    } catch (e) {
      if (extractApiErrorCode(e) === 'BELOW_FLOOR_JUSTIFICATION_REQUIRED') {
        toast.error(t('requestDetailActions.belowFloorSendInBuilder'));
        openQuoteBuilder();
        return;
      }
      toast.error(translateApiError(e));
    }
  };

  return (
    <div className="flex gap-4 w-full min-w-0">
      <div className="flex flex-col gap-3 flex-[7] min-w-0">

        <RequestHeader deal={deal} onBack={onBack} />

        <RequestActionBar
          quote={quote}
          isDraft={isDraft && canManageDeal}
          isSourcing={isSourcing && canManageDeal}
          isCalculating={isCalculating && canManageDeal}
          canSendQuote={canSendQuote}
          isWon={isWon}
          hasQuote={hasQuote}
          canBuildQuote={canBuildQuote}
          canBuildNewVersion={canBuildNewVersion}
          canClaim={canClaim}
          canRelease={canRelease}
          canTakeAndPrepare={canTakeAndPrepare}
          canSubmitForReview={canSubmitForReview}
          changeStagePending={changeStage.isPending}
          claimPending={claimMut.isPending}
          releasePending={releaseMut.isPending}
          takePending={takeMut.isPending}
          submitReviewPending={submitReviewMut.isPending}
          onSubmitForReview={async () => {
            if (!quote) return;
            try {
              await submitReviewMut.mutateAsync(quote.id);
              toast.success(t('quote.approvalChain.submitted'));
            } catch (e) {
              toast.error(translateApiError(e));
            }
          }}
          onTakeAndPrepare={async () => {
            try {
              await takeMut.mutateAsync(deal.id);
              toast.success(t('requestDetailActions.takePrepared'));
              openQuoteBuilder();
            } catch (e) {
              toast.error(translateApiError(e));
            }
          }}
          sendQuotePending={sendQuote.isPending}
          onClaim={() => claimMut.mutate(deal.id, {
            onSuccess: () => toast.success(t('dealsKanban.claimed')),
            onError: (err) => toast.error(translateApiError(err)),
          })}
          onRelease={() => releaseMut.mutate(deal.id, {
            onSuccess: () => toast.success(t('dealsKanban.released')),
            onError: (err) => toast.error(translateApiError(err)),
          })}
          onStartSourcing={() => run(() => changeStage.mutateAsync({ id: deal.id, stage: DealStage.SOURCING }))}
          onStartCalculation={() => run(() => changeStage.mutateAsync({ id: deal.id, stage: DealStage.CALCULATING }))}
          onOpenGenerate={() => setGenerateQuoteOpen(true)}
          onOpenQuoteBuilder={openQuoteBuilder}
          onSendQuote={handleSendQuote}
          onOpenContract={() => { window.location.hash = 'contracts'; }}
        />

        {/* Комментарий клиента к заявке (подан в Cabinet или передан из CRM) — только чтение. */}
        {(deal.notes ?? '').trim() && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('requestDetailActions.clientNote')}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-line text-sm text-muted-foreground">{deal.notes}</p>
            </CardContent>
          </Card>
        )}

        {quote ? (
          <QuoteView deal={deal} quote={quote} />
        ) : (
          <Card>
            <CardContent className="py-12 flex flex-col items-center justify-center text-muted-foreground">
              <Calculator className="h-10 w-10 mb-2 opacity-20" />
              <p>{t('requestDetailActions.noQuote')}</p>
            </CardContent>
          </Card>
        )}

        {/* M1-ERP-08 — отклонение маржи: КП против факта закупки (только с правом видеть маржу;
            появляется после отправки КП). Цена клиенту не пересчитывается. */}
        <DealMarginDeviationCard dealId={deal.id} />

        {/* F1 — цепочка «после договора»: договор / счета / платежи / акты / отгрузка со
            счётчиками-ссылками и подсказкой следующего шага (smart-buttons карточки заказа
            Odoo). Сам решает, показываться ли: пока договора нет, блок молчит. Шаг приходит с сервера. */}
        <DealChainCard dealId={deal.id} />

        {/* F2 II-4 — documents attached to this deal + «Создать документ» (pre-bound to the deal).
            Received counterparty documents surface here read-only with a «Получен» badge. Renders
            regardless of a client company, so a solo deal still has its documents surface. */}
        <DealDocumentsCard dealId={deal.id} />

        {/* CRM Phase A — deal history feed (renders nothing while empty) */}
        <DealTimeline dealId={deal.id} />
      </div>

      {/* Вложения сделки (Excel-спецификации, чертежи). Чат сделки ушёл в M1-ERP-02 1b — переписка с клиентом в CRM. */}
      <div className="w-80 shrink-0 sticky top-0 self-start hidden lg:flex flex-col">
        <Card>
          <CardContent>
            <DealAttachmentsPanel dealId={deal.id} />
          </CardContent>
        </Card>
      </div>

      {/* Create the КП, then jump straight into the focused builder. */}
      <GenerateQuoteDialog
        dealId={deal.id}
        open={generateQuoteOpen}
        onOpenChange={setGenerateQuoteOpen}
        onGenerated={openQuoteBuilder}
      />
    </div>
  );
}

export default RequestDetailPage;
