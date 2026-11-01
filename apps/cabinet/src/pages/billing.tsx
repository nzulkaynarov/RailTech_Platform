import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, ClipboardCheck, FileSignature, PenLine, Receipt, Undo2, Upload, Wallet } from 'lucide-react';
import { toast } from '@/lib/toast';

import type { Act, Contract, Invoice, PaymentProof } from '@/api/portal';
import { useAcceptAct, useActs, useContracts, useInvoices, useReturnAct, useSignContract, useSubmitPaymentProof } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { BillingNavTabs } from '@/components/BillingNavTabs';
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { DealLink, SummaryNote } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ReasonDialog } from '@/components/ReasonDialog';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge, ToneBadge } from '@/components/StatusBadge';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useNow } from '@/hooks/useNow';
import { businessToday, formatDate, formatDateTime, formatMoney, sumByCurrency } from '@/lib/format';
import { invoiceOpen, invoiceView, parseAmount, PROOF_COMMENT_MAX } from '@/lib/invoice';
import { contractAwaitsClient } from '@/lib/status';
import { scanProblem, type UploadProblem } from '@/lib/upload';
import { CanAct } from '@/session/CanAct';

/**
 * Договоры, счета и акты (B2B `ContractsPage`, `InvoicesPage`, `ActsPage`, `RejectActDialog`) — проекция
 * клиента: подписать договор (простая подпись подтверждением, DECISIONS 2026-10-13), видеть остаток и
 * просрочку счёта, принять акт или вернуть его с причиной. Действия — только при `can_act`.
 */

/** Документ строки или пометка «файл готовится», если ERP ещё не выпустил PDF. */
function RowDocument({ documentId, number }: { documentId: number | null | undefined; number: string }) {
  const { t } = useTranslation();
  if (documentId === null || documentId === undefined) {
    return <span className="max-w-32 text-xs whitespace-normal text-muted-foreground">{t('documents.notIssued')}</span>;
  }
  return <DocumentButton documentId={documentId} fileName={`${number}.pdf`} label={number} variant="ghost" />;
}

// --- договоры ------------------------------------------------------------------------------------

export function ContractsPage() {
  const { t } = useTranslation();
  const contracts = useContracts();
  const sign = useSignContract();
  const [target, setTarget] = useState<Contract | null>(null);
  const awaiting = (contracts.data ?? []).filter((item) => contractAwaitsClient(item.status)).length;

  const close = () => {
    setTarget(null);
    sign.reset();
  };

  return (
    <>
      <PageHeader title={t('pages.contracts.title')} icon={FileSignature} />
      <BillingNavTabs />
      {contracts.isPending ? (
        <ListSkeleton />
      ) : contracts.isError ? (
        <ErrorState error={contracts.error} onRetry={() => void contracts.refetch()} />
      ) : contracts.data.length === 0 ? (
        <EmptyState icon={FileSignature} title={t('pages.contracts.emptyTitle')} text={t('pages.contracts.emptyText')} />
      ) : (
        <>
          {awaiting > 0 ? <SummaryNote icon={PenLine}>{t('pages.contracts.awaiting', { count: awaiting })}</SummaryNote> : null}
          <ResponsiveList<Contract>
            label={t('pages.contracts.title')}
            rows={contracts.data}
            getRowId={(row) => row.id}
            title={{ header: t('pages.contracts.columns.contract'), cell: (row) => <span className="font-medium whitespace-nowrap">{row.number}</span> }}
            columns={[
              { id: 'status', header: t('pages.contracts.columns.status'), cell: (row) => <StatusBadge entity="contract" code={row.status} /> },
              {
                id: 'client',
                header: t('pages.contracts.columns.client'),
                cell: (row) => (row.signed_by_client_at ? formatDateTime(row.signed_by_client_at) : t('pages.contracts.notSigned')),
              },
              {
                id: 'company',
                header: t('pages.contracts.columns.company'),
                cell: (row) => (row.signed_by_company_at ? formatDateTime(row.signed_by_company_at) : t('pages.contracts.notSigned')),
              },
              { id: 'deal', header: t('pages.contracts.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
            ]}
            actions={{
              header: t('common.actions'),
              cell: (row) => (
                <>
                  <RowDocument documentId={row.document_id} number={row.number} />
                  <ManagerButton compact dealId={row.deal?.id} label={t('manager.aboutContract', { number: row.number })} />
                  {contractAwaitsClient(row.status) ? (
                    <CanAct>
                      <Button size="sm" onClick={() => setTarget(row)} aria-label={t('pages.contracts.signNamed', { number: row.number })}>
                        <PenLine aria-hidden="true" />
                        {t('pages.contracts.sign')}
                      </Button>
                    </CanAct>
                  ) : null}
                </>
              ),
            }}
          />
        </>
      )}
      <ActionDialog
        open={target !== null}
        onOpenChange={(open) => !open && close()}
        title={t('pages.contracts.signTitle', { number: target?.number ?? '' })}
        description={t('pages.contracts.signText')}
        confirmLabel={t('pages.contracts.signConfirm')}
        pending={sign.isPending}
        error={sign.error}
        onSubmit={() =>
          target &&
          sign.mutate(target.id, {
            onSuccess: (signed) => {
              toast.success(
                signed.status === 'signed'
                  ? t('pages.contracts.signedBoth', { number: signed.number })
                  : t('pages.contracts.signedClient', { number: signed.number }),
              );
              close();
            },
          })
        }
      />
    </>
  );
}

// --- счета ------------------------------------------------------------------------------------

export function InvoicesPage() {
  const { t } = useTranslation();
  const invoices = useInvoices();
  const now = useNow();
  const views = new Map((invoices.data ?? []).map((invoice) => [invoice.id, invoiceView(invoice, now)]));
  const open = (invoices.data ?? []).filter((invoice) => invoice.status !== 'paid' && invoice.status !== 'cancelled');
  const toPay = sumByCurrency(open.map((invoice) => views.get(invoice.id)?.remaining).filter((money) => money !== null && money !== undefined));
  const overdue = open.filter((invoice) => views.get(invoice.id)?.overdueDays).length;
  const [paying, setPaying] = useState<Invoice | null>(null);

  return (
    <>
      <PageHeader title={t('pages.invoices.title')} icon={Receipt} />
      <BillingNavTabs />
      {invoices.isPending ? (
        <ListSkeleton />
      ) : invoices.isError ? (
        <ErrorState error={invoices.error} onRetry={() => void invoices.refetch()} />
      ) : invoices.data.length === 0 ? (
        <EmptyState icon={Receipt} title={t('pages.invoices.emptyTitle')} text={t('pages.invoices.emptyText')} />
      ) : (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            <Card className="py-4">
              <CardContent className="flex items-start gap-3 px-4">
                <Wallet className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="text-sm text-muted-foreground">{t('pages.invoices.toPay')}</p>
                  {toPay.length ? (
                    toPay.map((money) => (
                      <p key={money.currency} className="text-lg font-semibold tabular-nums wrap-break-word">
                        {formatMoney(money)}
                      </p>
                    ))
                  ) : (
                    <p className="text-lg font-semibold">{t('pages.invoices.nothingToPay')}</p>
                  )}
                </div>
              </CardContent>
            </Card>
            <Card className="py-4">
              <CardContent className="flex items-start gap-3 px-4">
                {overdue ? (
                  <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
                ) : (
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
                )}
                <div>
                  <p className="text-sm text-muted-foreground">{t('pages.invoices.overdueTitle')}</p>
                  <p className="text-lg font-semibold">
                    {overdue ? t('pages.invoices.overdueCount', { count: overdue }) : t('pages.invoices.noOverdue')}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
          <ResponsiveList<Invoice>
            label={t('pages.invoices.title')}
            rows={invoices.data}
            getRowId={(row) => row.id}
            title={{
              header: t('pages.invoices.columns.invoice'),
              cell: (row) => (
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="font-medium whitespace-nowrap">{row.number}</span>
                  <ProofList invoice={row} />
                </span>
              ),
              className: 'min-w-0',
            }}
            columns={[
              {
                id: 'status',
                header: t('pages.invoices.columns.status'),
                cell: (row) => <StatusBadge entity="invoice" code={views.get(row.id)?.displayStatus ?? row.status} />,
              },
              { id: 'total', header: t('pages.invoices.columns.total'), cell: (row) => formatMoney(row.total), className: 'text-right tabular-nums whitespace-nowrap' },
              { id: 'paid', header: t('pages.invoices.columns.paid'), cell: (row) => formatMoney(row.paid), className: 'text-right tabular-nums whitespace-nowrap' },
              {
                id: 'remaining',
                header: t('pages.invoices.columns.remaining'),
                cell: (row) => <span className="font-medium">{formatMoney(views.get(row.id)?.remaining)}</span>,
                className: 'text-right tabular-nums whitespace-nowrap',
              },
              {
                id: 'due',
                header: t('pages.invoices.columns.due'),
                cell: (row) => {
                  const days = views.get(row.id)?.overdueDays;
                  return (
                    <span className="inline-flex flex-wrap items-center justify-end gap-1">
                      {formatDate(row.due_date)}
                      {days ? <ToneBadge tone="danger">{t('pages.invoices.overdueDays', { count: days })}</ToneBadge> : null}
                    </span>
                  );
                },
              },
              { id: 'deal', header: t('pages.invoices.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
            ]}
            actions={{
              header: t('common.actions'),
              cell: (row) => (
                <>
                  <RowDocument documentId={row.document_id} number={row.number} />
                  <ManagerButton compact dealId={row.deal?.id} label={t('manager.aboutInvoice', { number: row.number })} />
                  {invoiceOpen(row) ? (
                    <CanAct>
                      <Button size="sm" onClick={() => setPaying(row)} aria-label={t('pages.invoices.payNamed', { number: row.number })}>
                        <Upload aria-hidden="true" />
                        {t('pages.invoices.payButton')}
                      </Button>
                    </CanAct>
                  ) : null}
                </>
              ),
            }}
          />
        </>
      )}
      <PaymentProofDialog invoice={paying} remaining={paying ? views.get(paying.id)?.remaining : null} onClose={() => setPaying(null)} />
    </>
  );
}

/** Платёжки счёта со статусом проверки (`Invoice.proofs`): что клиент отправил и что с ней сделал менеджер. */
function ProofList({ invoice }: { invoice: Invoice }) {
  const { t } = useTranslation();
  if (!invoice.proofs.length) return null;
  return (
    <ul className="flex flex-col gap-1.5 text-xs font-normal" aria-label={t('pages.invoices.proofsLabel', { number: invoice.number })}>
      {invoice.proofs.map((proof) => (
        <li key={proof.id} className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge entity="proof" code={proof.status} />
            <span className="break-all text-muted-foreground">
              {t('pages.invoices.proofLine', { name: proof.file_name, date: formatDateTime(proof.submitted_at) })}
            </span>
          </span>
          <ProofClaim proof={proof} />
          {proof.status === 'rejected' && proof.reject_reason ? (
            <span className="text-muted-foreground">{t('pages.invoices.proofRejected', { reason: proof.reject_reason })}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ProofClaim({ proof }: { proof: PaymentProof }) {
  const { t } = useTranslation();
  if (proof.amount) {
    const amount = formatMoney(proof.amount);
    const text = proof.paid_on
      ? t('pages.invoices.proofClaimedDate', { amount, date: formatDate(proof.paid_on) })
      : t('pages.invoices.proofClaimed', { amount });
    return <span className="text-muted-foreground">{text}</span>;
  }
  if (proof.paid_on) return <span className="text-muted-foreground">{t('pages.invoices.proofPaidOn', { date: formatDate(proof.paid_on) })}</span>;
  return null;
}

type ProofProblem = 'fileMissing' | UploadProblem | 'amount' | 'future';

/**
 * «Я оплатил» (SPEC-v3 §3.1 шаг 8, §8): файл платёжного поручения обязателен, дата, сумма и комментарий — по желанию.
 * Файл — `POST /uploads`, затем `POST /invoices/{id}/proofs`. Платёжка не деньги: статус счёта меняет менеджер, когда
 * сверит поступление с выпиской (так и написано в «Что произойдёт»).
 */
function PaymentProofDialog({
  invoice,
  remaining,
  onClose,
}: {
  invoice: Invoice | null;
  remaining: Invoice['total'] | null | undefined;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const now = useNow();
  const submit = useSubmitPaymentProof();
  const [file, setFile] = useState<File | null>(null);
  const [paidOn, setPaidOn] = useState('');
  const [amount, setAmount] = useState('');
  const [comment, setComment] = useState('');
  const [problem, setProblem] = useState<ProofProblem | null>(null);
  const today = businessToday(now);

  const close = () => {
    setFile(null);
    setPaidOn('');
    setAmount('');
    setComment('');
    setProblem(null);
    submit.reset();
    onClose();
  };

  const choose = (picked: File | undefined) => {
    submit.reset();
    if (!picked) {
      setFile(null);
      return;
    }
    const found = scanProblem(picked);
    setProblem(found);
    setFile(found ? null : picked);
  };

  const send = () => {
    if (!invoice) return;
    if (!file) return setProblem(problem === 'tooLarge' || problem === 'badType' ? problem : 'fileMissing');
    const parsed = parseAmount(amount);
    if (parsed === 'invalid') return setProblem('amount');
    if (paidOn && paidOn > today) return setProblem('future');
    setProblem(null);
    submit.mutate(
      { id: invoice.id, file, paid_on: paidOn || null, amount: parsed, comment: comment.trim() || null },
      {
        onSuccess: () => {
          toast.success(t('pages.invoices.proofDialog.sent', { number: invoice.number }));
          close();
        },
      },
    );
  };

  const optional = <span className="font-normal text-muted-foreground">({t('pages.invoices.proofDialog.optional')})</span>;
  return (
    <ActionDialog
      open={invoice !== null}
      onOpenChange={(open) => !open && close()}
      title={t('pages.invoices.proofDialog.title', { number: invoice?.number ?? '' })}
      description={t('pages.invoices.proofDialog.text', { remaining: formatMoney(remaining) })}
      confirmLabel={t('pages.invoices.proofDialog.confirm')}
      pending={submit.isPending}
      error={submit.error}
      message={problem ? t(`pages.invoices.proofDialog.problem.${problem}`) : null}
      onSubmit={send}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-file`}>{t('pages.invoices.proofDialog.file')}</Label>
          <Input
            id={`${id}-file`}
            type="file"
            accept=".pdf,image/*"
            required
            aria-describedby={`${id}-file-hint`}
            aria-invalid={problem === 'fileMissing' || problem === 'tooLarge' || problem === 'badType' ? true : undefined}
            onChange={(event) => choose(event.target.files?.[0])}
          />
          <p id={`${id}-file-hint`} className="text-xs text-muted-foreground">
            {t('pages.invoices.proofDialog.fileHint')}
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-date`}>
              {t('pages.invoices.proofDialog.paidOn')} {optional}
            </Label>
            <Input
              id={`${id}-date`}
              type="date"
              max={today}
              value={paidOn}
              aria-invalid={problem === 'future' ? true : undefined}
              onChange={(event) => setPaidOn(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-amount`}>
              {t('pages.invoices.proofDialog.amount', { currency: invoice?.total.currency ?? '' })} {optional}
            </Label>
            <Input
              id={`${id}-amount`}
              inputMode="decimal"
              autoComplete="off"
              value={amount}
              aria-describedby={`${id}-amount-hint`}
              aria-invalid={problem === 'amount' ? true : undefined}
              onChange={(event) => setAmount(event.target.value)}
            />
            <p id={`${id}-amount-hint`} className="text-xs text-muted-foreground">
              {t('pages.invoices.proofDialog.amountHint')}
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-comment`}>
            {t('pages.invoices.proofDialog.comment')} {optional}
          </Label>
          <Textarea
            id={`${id}-comment`}
            rows={3}
            maxLength={PROOF_COMMENT_MAX}
            value={comment}
            placeholder={t('pages.invoices.proofDialog.commentPlaceholder')}
            onChange={(event) => setComment(event.target.value)}
          />
        </div>
        <ConsequenceCallout text={t('pages.invoices.proofDialog.consequence')} />
      </div>
    </ActionDialog>
  );
}

// --- акты ---------------------------------------------------------------------------------------

export function ActsPage() {
  const { t } = useTranslation();
  const acts = useActs();
  const giveBack = useReturnAct();
  const [target, setTarget] = useState<{ act: Act; action: 'accept' | 'return' } | null>(null);
  const awaiting = (acts.data ?? []).filter((act) => act.status === 'issued').length;

  const close = () => {
    setTarget(null);
    giveBack.reset();
  };

  return (
    <>
      <PageHeader title={t('pages.acts.title')} icon={ClipboardCheck} />
      <BillingNavTabs />
      {acts.isPending ? (
        <ListSkeleton />
      ) : acts.isError ? (
        <ErrorState error={acts.error} onRetry={() => void acts.refetch()} />
      ) : acts.data.length === 0 ? (
        <EmptyState icon={ClipboardCheck} title={t('pages.acts.emptyTitle')} text={t('pages.acts.emptyText')} />
      ) : (
        <>
          {awaiting > 0 ? <SummaryNote icon={ClipboardCheck}>{t('pages.acts.awaiting', { count: awaiting })}</SummaryNote> : null}
          <ResponsiveList<Act>
            label={t('pages.acts.title')}
            rows={acts.data}
            getRowId={(row) => row.id}
            title={{
              header: t('pages.acts.columns.act'),
              cell: (row) => (
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium whitespace-nowrap">{row.number}</span>
                  {row.status === 'returned' && row.returned_reason ? (
                    <span className="font-normal text-muted-foreground">
                      {t('pages.acts.returnedReason', { reason: row.returned_reason })}
                    </span>
                  ) : null}
                </span>
              ),
            }}
            columns={[
              { id: 'status', header: t('pages.acts.columns.status'), cell: (row) => <StatusBadge entity="act" code={row.status} /> },
              { id: 'issued', header: t('pages.acts.columns.issued'), cell: (row) => formatDate(row.issued_at) },
              { id: 'deal', header: t('pages.acts.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
            ]}
            actions={{
              header: t('common.actions'),
              cell: (row) => (
                <>
                  <RowDocument documentId={row.document_id} number={row.number} />
                  {row.scan_document_id !== null && row.scan_document_id !== undefined ? (
                    <DocumentButton
                      documentId={row.scan_document_id}
                      fileName={`${row.number}-scan.pdf`}
                      label={t('pages.acts.scanNamed', { number: row.number })}
                      variant="ghost"
                      text={t('pages.acts.scan')}
                    />
                  ) : null}
                  <ManagerButton compact dealId={row.deal?.id} label={t('manager.aboutAct', { number: row.number })} />
                  {row.status === 'issued' ? (
                    <CanAct>
                      <Button size="sm" onClick={() => setTarget({ act: row, action: 'accept' })} aria-label={t('pages.acts.acceptNamed', { number: row.number })}>
                        <CheckCircle2 aria-hidden="true" />
                        {t('pages.acts.accept')}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setTarget({ act: row, action: 'return' })}
                        aria-label={t('pages.acts.returnNamed', { number: row.number })}
                      >
                        <Undo2 aria-hidden="true" />
                        {t('pages.acts.return')}
                      </Button>
                    </CanAct>
                  ) : null}
                </>
              ),
            }}
          />
        </>
      )}
      <AcceptActDialog act={target?.action === 'accept' ? target.act : null} onClose={close} />
      <ReasonDialog
        target={target?.act.id ?? null}
        open={target?.action === 'return'}
        onOpenChange={(open) => !open && close()}
        title={t('pages.acts.returnTitle', { number: target?.act.number ?? '' })}
        description={t('pages.acts.returnText')}
        label={t('pages.acts.returnReason')}
        placeholder={t('pages.acts.returnPlaceholder')}
        confirmLabel={t('pages.acts.returnConfirm')}
        pending={giveBack.isPending}
        error={giveBack.error}
        onConfirm={(reason) =>
          target &&
          giveBack.mutate(
            { id: target.act.id, reason },
            {
              onSuccess: (act) => {
                toast.success(t('pages.acts.returnedToast', { number: act.number }));
                close();
              },
            },
          )
        }
      />
    </>
  );
}

/**
 * Приёмка акта. Скан подписанного экземпляра необязателен: с ним — `POST /uploads`, затем
 * `POST /acts/{id}/accept {upload_id}` (ERP кладёт скан в `scan_document_id`), без него — приёмка без тела.
 */
function AcceptActDialog({ act, onClose }: { act: Act | null; onClose: () => void }) {
  const { t } = useTranslation();
  const id = useId();
  const accept = useAcceptAct();
  const [scan, setScan] = useState<File | null>(null);
  const [problem, setProblem] = useState<UploadProblem | null>(null);

  const close = () => {
    setScan(null);
    setProblem(null);
    accept.reset();
    onClose();
  };

  const choose = (file: File | undefined) => {
    accept.reset();
    if (!file) {
      setScan(null);
      setProblem(null);
      return;
    }
    const found = scanProblem(file);
    setProblem(found);
    setScan(found ? null : file);
  };

  return (
    <ActionDialog
      open={act !== null}
      onOpenChange={(open) => !open && close()}
      title={t('pages.acts.acceptTitle', { number: act?.number ?? '' })}
      description={t('pages.acts.acceptText')}
      confirmLabel={t('pages.acts.acceptConfirm')}
      pending={accept.isPending}
      error={accept.error}
      message={problem ? t(`pages.acts.scanProblem.${problem}`) : null}
      onSubmit={() =>
        act &&
        !problem &&
        accept.mutate(
          { id: act.id, scan },
          {
            onSuccess: (accepted) => {
              toast.success(t('pages.acts.acceptedToast', { number: accepted.number }));
              close();
            },
          },
        )
      }
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>{t('pages.acts.scanLabel')}</Label>
        <Input
          id={id}
          type="file"
          accept=".pdf,image/*"
          aria-describedby={`${id}-hint`}
          aria-invalid={problem ? true : undefined}
          onChange={(event) => choose(event.target.files?.[0])}
        />
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {t('pages.acts.scanHint')}
        </p>
      </div>
    </ActionDialog>
  );
}
