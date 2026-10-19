import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, ClipboardCheck, FileSignature, PenLine, Receipt, Undo2, Wallet } from 'lucide-react';
import { toast } from 'sonner';

import type { Act, Contract, Invoice } from '@/api/portal';
import { useAcceptAct, useActs, useContracts, useInvoices, useReturnAct, useSignContract } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
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
import { useNow } from '@/hooks/useNow';
import { formatDate, formatDateTime, formatMoney, sumByCurrency } from '@/lib/format';
import { invoiceView } from '@/lib/invoice';
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
    return <span className="text-xs text-muted-foreground">{t('documents.notIssued')}</span>;
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
      <PageHeader title={t('pages.contracts.title')} />
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

  return (
    <>
      <PageHeader title={t('pages.invoices.title')} />
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
                      <p key={money.currency} className="text-lg font-semibold wrap-break-word">
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
            title={{ header: t('pages.invoices.columns.invoice'), cell: (row) => <span className="font-medium whitespace-nowrap">{row.number}</span> }}
            columns={[
              {
                id: 'status',
                header: t('pages.invoices.columns.status'),
                cell: (row) => <StatusBadge entity="invoice" code={views.get(row.id)?.displayStatus ?? row.status} />,
              },
              { id: 'total', header: t('pages.invoices.columns.total'), cell: (row) => formatMoney(row.total), className: 'text-right' },
              { id: 'paid', header: t('pages.invoices.columns.paid'), cell: (row) => formatMoney(row.paid), className: 'text-right' },
              {
                id: 'remaining',
                header: t('pages.invoices.columns.remaining'),
                cell: (row) => <span className="font-medium">{formatMoney(views.get(row.id)?.remaining)}</span>,
                className: 'text-right',
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
                </>
              ),
            }}
          />
        </>
      )}
    </>
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
      <PageHeader title={t('pages.acts.title')} />
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
