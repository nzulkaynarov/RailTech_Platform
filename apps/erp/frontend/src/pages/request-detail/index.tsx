import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Calculator, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { QuoteStatus, DealStage } from '@/lib/codes';
import { useUserStore } from '@/store/userStore';
import { useIsSoloSeller } from '@/hooks/useCapabilities';
import {
  useDeal, useChangeDealStage, useApproveQuote, useRejectQuote, useSendQuoteToClient,
  useUpdateRequestMeta, useClaimDeal, useReleaseDeal, useTakeAndPrepareQuote, useSubmitQuoteForReview,
} from '@/hooks/useCRM';
import { translateApiError, extractApiErrorCode } from '@/lib/apiError';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { DealAttachmentsPanel } from '@/components/Sourcing/DealAttachmentsPanel';
import { RejectQuoteDialog } from '@/components/CRM/RejectQuoteDialog';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { RequestItemsEditor } from '@/components/CRM/RequestItemsEditor';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { BuyerAcceptedPanel } from '@/components/CRM/BuyerAcceptedPanel';
import { DealTimeline } from '@/components/CRM/DealTimeline';
import { DealDocumentsCard } from '@/components/CRM/DealDocumentsCard';
import { DealChainCard } from '@/components/CRM/DealChainCard';
import { RequestHeader } from './RequestHeader';
import { RequestActionBar } from './RequestActionBar';
import { QuoteView } from './QuoteView';
import { BuyerRequestEditor } from './BuyerRequestEditor';
import { needsQuoteWork } from '@/lib/waiting';

/**
 * Canonical buyer-facing deal/КП detail surface. Reached via the `request-detail/<dealId>` hash
 * route (My Requests / Sourcing / cart / import). State is React Query throughout (useDeal +
 * useCRM). Seller-side stage actions remain for sellers who land here from the sourcing list; the
 * buyer only ever sees approve/reject.
 *
 * A SOLO deal (Wave E calculator draft) carries `deal.company === null` — a legitimate state.
 * Every counterparty field is null-guarded (see RequestHeader) and the documents block renders
 * regardless of a buyer, so the seller is never dead-ended on their own solo deal.
 *
 * Split into ./request-detail/* (god-component 500-line limit): RequestHeader, RequestActionBar,
 * QuoteView (priced КП + coverage), BuyerRequestEditor (request lines + pre-flight).
 */
export function RequestDetailPage({ dealId, onBack }: { dealId: number; onBack: () => void }) {
  const { t } = useTranslation();
  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approveConfirmOpen, setApproveConfirmOpen] = useState(false);
  const [generateQuoteOpen, setGenerateQuoteOpen] = useState(false);

  const changeStage = useChangeDealStage();
  const approveQuote = useApproveQuote();
  const rejectQuote = useRejectQuote();
  const sendQuote = useSendQuoteToClient();
  const updateMeta = useUpdateRequestMeta();
  const claimMut = useClaimDeal();
  const releaseMut = useReleaseDeal();
  const takeMut = useTakeAndPrepareQuote();
  const submitReviewMut = useSubmitQuoteForReview();
  const isSoloSeller = useIsSoloSeller();

  // Gate seller-side actions (start sourcing / calculation / send quote) to sellers. A buyer would
  // only hit backend guards — and the buttons are meaningless on their screen.
  //
  // Сторону считает СЕРВЕР и присылает на КАЖДОЙ сделке (`viewer_is_seller`/`viewer_is_buyer`).
  // Раньше она выводилась из `activeStatus` — а это ПЕРВЫЙ тип компании: у компании с типами
  // CLIENT+SUPPLIER продавец открывал свою же заявку и видел ПОКУПАТЕЛЬСКИЙ экран без единой
  // кнопки подготовки КП (проход глазами 03-08). Бенчмарк: GitHub отдаёт `viewerCan*` на
  // объекте, Salesforce — `UserRecordAccess`; клиент роль ЧИТАЕТ, а не вычисляет.
  //
  // `activeStatus` остаётся ЗАПАСНЫМ путём для старых ответов без этих полей.
  const activeStatus = useUserStore((s) => s.activeStatus);

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

  const isSellerSide = deal.viewer_is_seller ?? activeStatus === 'SELLER';
  const isBuyerSide = deal.viewer_is_buyer ?? activeStatus === 'BUYER';

  const quote = deal.active_quote ?? deal.quotes?.[deal.quotes.length - 1] ?? null;

  const isDraft = deal.stage_code === DealStage.DRAFT;
  const isSourcing = deal.stage_code === DealStage.SOURCING;
  const isCalculating = deal.stage_code === DealStage.CALCULATING;
  const isQuoteSent = deal.stage_code === DealStage.QUOTE_SENT;
  const isWon = deal.stage_code === DealStage.CLOSED_WON || deal.stage_code === DealStage.CONTRACT_SIGNED;
  // W2 «одна кнопка» (one-click-quotation): claim + стадия + предзаполненный КП одним действием.
  //
  // Условие «КП ещё нет» выражается через `needsQuoteWork`, а НЕ через `!active_quote`: позиции
  // заявки покупателя физически лежат в DRAFT-КП, поэтому `active_quote` есть у каждой
  // отправленной заявки — и кнопка волны W2 не показывалась НИКОГДА (проход глазами 03-08, тот
  // же корень, что у плитки «Заявки без КП»).
  const quoteNotStarted = needsQuoteWork(deal);
  const canTakeAndPrepare = isSellerSide && quoteNotStarted;
  // Q5 (устранение рассинхрона гейтов): «Сформировать КП» — резервный ручной путь, НЕ показываем
  // рядом с одной кнопкой W2 (иначе две кнопки создания на одной стадии сбивают с толку).
  const canBuildQuote = isSellerSide && (isSourcing || isCalculating) && quoteNotStarted && !canTakeAndPrepare;
  // «КП уже собирают» — тоже по состоянию: пустой черновик-хранилище позиций за КП не считается.
  const hasQuote = isSellerSide && !!deal.active_quote && !quoteNotStarted;
  // Q4: send a DRAFT КП into internal review straight from the request card (no builder detour).
  // The server re-runs every gate; a sole-approver КП auto-approves → «Отправить» surfaces next.
  const canSubmitForReview = isSellerSide && deal.active_quote?.status_code === QuoteStatus.DRAFT;
  // Buyer rejected the КП → offer a primary "new version" action (perform_create auto-increments).
  const canBuildNewVersion = isSellerSide && deal.active_quote?.status_code === QuoteStatus.REJECTED;
  // Wave B2 (auto-claim): a solo seller has no queue to route, so hide «Взять в работу» entirely.
  const canClaim = isSellerSide && deal.assigned_to == null && !isSoloSeller;
  // Право на возврат считает СЕРВЕР (владелец записи ИЛИ team.manage) — фронт его не выводит.
  const canRelease = !!deal.viewer_can_release;
  const openQuoteBuilder = () => { window.location.hash = `deal-quote/${deal.id}`; };
  // Buyer may build/edit their own request (name + qty) until the seller engages. The backend is
  // the source of truth (can_edit_request); the UI only reflects it.
  const canEditRequest = !!deal.can_edit_request;
  // A request has NO price. Prices belong to the seller's КП and are shown to the buyer ONLY after
  // the КП is actually sent back (SENT / APPROVED / REJECTED). The seller side always sees pricing.
  const quoteSentToBuyer = [QuoteStatus.SENT, QuoteStatus.APPROVED, QuoteStatus.REJECTED].includes(
    (quote?.status_code ?? '') as never,
  );
  const showPricedQuote = !!quote && (isSellerSide || quoteSentToBuyer);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Sending a below-floor КП needs a written justification, and that confirm-with-reason flow lives
  // only in the canonical builder (DealQuotePage, S7a). Rather than dead-end the seller on a
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

        <RequestHeader
          deal={deal}
          isBuyerSide={isBuyerSide}
          canEditRequest={canEditRequest}
          isSavingTitle={updateMeta.isPending}
          onSaveTitle={(title, onError) => updateMeta.mutate({ dealId: deal.id, title }, {
            onError: (err) => { onError(err); toast.error(translateApiError(err)); },
          })}
          onBack={onBack}
        />

        {/* Post-accept "what's next" (Wave A2). Once the buyer approves the КП the FSM materializes
            a Contract awaiting their signature — surface it here (with the real contract number +
            a deep-link) instead of dead-ending on the dashboard. */}
        {isBuyerSide && isWon && <BuyerAcceptedPanel dealId={deal.id} />}

        <RequestActionBar
          quote={quote}
          isSellerSide={isSellerSide}
          isBuyerSide={isBuyerSide}
          isDraft={isDraft}
          isSourcing={isSourcing}
          isCalculating={isCalculating}
          isQuoteSent={isQuoteSent}
          isWon={isWon}
          hasQuote={hasQuote}
          canBuildQuote={canBuildQuote}
          canBuildNewVersion={canBuildNewVersion}
          canClaim={canClaim}
          canRelease={canRelease}
          canTakeAndPrepare={canTakeAndPrepare}
          canSubmitForReview={canSubmitForReview}
          canEditRequest={canEditRequest}
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
          approvePending={approveQuote.isPending}
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
          onApprove={() => setApproveConfirmOpen(true)}
          onReject={() => setRejectOpen(true)}
          onOpenContract={() => { window.location.hash = 'contracts'; }}
        />

        {/* Note to the seller — the buyer's free-text request description. Editable while drafting,
            read-only (and visible to the seller) afterwards. */}
        {(canEditRequest || (deal.notes ?? '').trim()) && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('requestDetailActions.noteToSeller')}</CardTitle>
            </CardHeader>
            <CardContent>
              {canEditRequest ? (
                <Textarea
                  defaultValue={deal.notes ?? ''}
                  onBlur={(e) => { if (e.target.value !== (deal.notes ?? '')) updateMeta.mutate({ dealId: deal.id, notes: e.target.value }); }}
                  placeholder={t('requestDetailActions.noteToSellerPlaceholder')}
                  rows={2}
                />
              ) : (
                <p className="whitespace-pre-line text-sm text-muted-foreground">{deal.notes}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* What the buyer sees about their request:
            1. canEditRequest      → editable items (name + qty, no price) + pre-flight
            2. КП sent back / seller → the priced quote table
            3. seller pricing, not sent yet → request items READ-ONLY, no price
            4. nothing yet         → empty state */}
        {canEditRequest ? (
          <BuyerRequestEditor deal={deal} quote={quote} />
        ) : showPricedQuote && quote ? (
          <QuoteView deal={deal} quote={quote} isSellerSide={isSellerSide} isBuyerSide={isBuyerSide} />
        ) : quote && (quote.items?.length ?? 0) > 0 ? (
          // Seller is working the КП but hasn't sent it — buyer sees their requested items
          // read-only, WITHOUT any price.
          <RequestItemsEditor dealId={deal.id} items={quote.items ?? []} canEdit={false} />
        ) : (
          <Card>
            <CardContent className="py-12 flex flex-col items-center justify-center text-muted-foreground">
              <Calculator className="h-10 w-10 mb-2 opacity-20" />
              <p>{t('requestDetailActions.noQuote')}</p>
            </CardContent>
          </Card>
        )}

        {/* F1 — цепочка «после договора»: договор / счета / платежи / акты / отгрузка со
            счётчиками-ссылками и подсказкой следующего шага (smart-buttons карточки заказа
            Odoo). Сам решает, показываться ли: пока договора нет, блок молчит. Стороны и шаг
            приходят с сервера, поэтому dual-компания видит верные кнопки в любом контексте. */}
        <DealChainCard dealId={deal.id} />

        {/* F2 II-4 — documents attached to this deal + «Создать документ» (pre-bound to the deal).
            Received counterparty documents surface here read-only with a «Получен» badge. Renders
            regardless of a buyer company, so a solo deal still has its documents surface. */}
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

      <RejectQuoteDialog
        quoteId={quote?.id ?? null}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={async (reason) => { if (quote) await run(() => rejectQuote.mutateAsync({ id: quote.id, reason })); }}
      />

      {/* Approving commits the deal to a contract — confirm before the irreversible accept (parity
          with the reject dialog). */}
      <ConfirmActionDialog
        open={approveConfirmOpen}
        onOpenChange={setApproveConfirmOpen}
        title={t('confirmActions.approveQuote.title')}
        description={t('confirmActions.approveQuote.description')}
        variant="primary"
        confirmLabel={t('requestDetailActions.approveQuote')}
        onConfirm={async () => { if (quote) await approveQuote.mutateAsync(quote.id); }}
        translateError={(code) => translateApiError(code)}
      />

      {/* Seller: create the КП, then jump straight into the focused builder. */}
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
