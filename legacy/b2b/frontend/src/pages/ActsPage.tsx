import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { extractBlobErrorCode, fetchDocumentBlob, saveBlob } from '@/lib/documents';
import { ScrollText, PenLine, Download, Ban } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import { useActs, useSignAct, useRejectAct } from '@/hooks/useBilling';
import { RejectActDialog } from '@/components/Billing/RejectActDialog';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useCurrencyStore } from '@/store/currencyStore';
import { openableRowProps } from '@/lib/rowClick';
import { DealLink } from '@/components/Shared/DealLink';
import type { Act, ActStatus } from '@/api/billingApi';

const STATUS_VARIANT: Record<ActStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'outline',
  SIGNED: 'default',
  CANCELLED: 'destructive',
};
const STATUS_CODES: ActStatus[] = ['DRAFT', 'ISSUED', 'SIGNED', 'CANCELLED'];

/**
 * Одна подпись: кто и когда. Пусто — честное «—», а не пропуск строки: заказчик должен
 * видеть, что акт ещё никем не принят.
 *
 * Формулировка «согласовал в системе», а не «подписал»: клик без E-IMZO юридической подписью
 * не является, и интерфейс не должен утверждать обратное (канон отрезка «после контракта»).
 */
function SignatureLine({ name, at }: { name?: string | null; at?: string | null }) {
  if (!at) return <p className="text-muted-foreground">—</p>;
  return (
    <p className="text-muted-foreground">
      <span className="text-foreground">{name || '—'}</span>
      <br />
      <span className="text-xs">{new Date(at).toLocaleString()}</span>
    </p>
  );
}

/**
 * «Чей сейчас ход» — состояние документа в терминах действия.
 *
 * Статус-код («Выставлен») говорит, ЧТО с документом, но не говорит, КОГО он ждёт. Эталоны
 * закрывающих документов показывают именно второе: Диадок «Ожидается подпись контрагента»,
 * DocuSign «Needs to Sign». Данные для этого сервер уже отдаёт — обе подписи и адресные
 * подсказки `viewer_can_sign` / `viewer_can_reject`.
 */
function ActTurnLine({ act }: { act: Act }) {
  const { t } = useTranslation();
  if (act.status === 'CANCELLED') return null;

  // Обе стороны согласовали — документ закрыт, ход ничей.
  if (act.issuer_signed_at && act.acceptor_signed_at) {
    return (
      <p className="rounded-md border border-success/30 bg-success/5 p-3 text-sm text-foreground">
        {t('actsPage.turn.settled')}
      </p>
    );
  }
  // Ждёт ЗРИТЕЛЯ — сервер сказал это адресно.
  if (act.viewer_can_sign) {
    return (
      <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm font-medium text-foreground">
        {t('actsPage.turn.yours')}
      </p>
    );
  }
  // Выставлен, но ждёт другую сторону.
  if (act.status === 'ISSUED') {
    return (
      <p className="rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
        {t('actsPage.turn.counterparty')}
      </p>
    );
  }
  return null;
}


export function ActsPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const { data: acts, isLoading, isError, refetch } = useActs(undefined);
  const signAct = useSignAct();
  const rejectAct = useRejectAct();
  const [rejectOpen, setRejectOpen] = useState(false);
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = useMemo(() => (acts ?? []).find((a) => a.id === selectedId) ?? null, [acts, selectedId]);

  const stats = useMemo(() => {
    const list = acts ?? [];
    return [
      { label: t('actsPage.stats.total'), value: String(list.length) },
      { label: t('actsPage.stats.issued'), value: String(list.filter((a) => a.status === 'ISSUED').length) },
      { label: t('actsPage.stats.signed'), value: String(list.filter((a) => a.status === 'SIGNED').length) },
    ];
  }, [acts, t]);

  const onSign = async (id: number, file?: File) => {
    try {
      await signAct.mutateAsync({ id, signedFile: file });
      toast.success(t('actsPage.signed'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onReject = async (id: number, reason: string) => {
    await rejectAct.mutateAsync({ id, reason });
    toast.success(t('actsPage.rejected'));
  };

  const onDownloadSigned = async (act: Act) => {
    try {
      const blob = await fetchDocumentBlob(`crm/acts/${act.id}/download-signed/`);
      const ext = blob.type.includes('pdf') ? 'pdf' : (blob.type.split('/')[1] || 'bin');
      saveBlob(blob, `RailTech_Act_${act.id}_signed.${ext}`);
    } catch (err) {
      // Surface the real backend code (403/404/expiry) instead of a generic message. Blob-response
      // error bodies aren't plain JSON — parse the code out first, fall back to the generic string.
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    }
  };

  return (
    <PageShell
      title={t('actsPage.title')}
      description={t('actsPage.description')}
      icon={<ScrollText className="h-5 w-5" />}
      stats={stats}
    >
      <ManualModeBanner kind="esign" />
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('actsPage.table.number')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('actsPage.allStatuses'),
            options: STATUS_CODES.map((s) => ({ value: s, label: t(`actsPage.status.${s}`) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(acts ?? [], listParams, {
              searchFields: (a) => [a.number, String(a.deal)],
              filterPredicates: { status: (a, v) => a.status === v },
              sortAccessors: {
                number: (a) => a.number,
                total: (a) => Number(a.total_amount),
                issued: (a) => a.issued_at ?? '',
                created_at: (a) => a.created_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              // Acts are generated from an invoice — never created directly — so the empty state
              // explains where they come from instead of implying a missing «create» button.
              return <EmptyState icon={<ScrollText className="h-5 w-5" />} message={t('actsPage.emptyState')} />;
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="number" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.number')}
                      </SortableHead>
                      <TableHead>{t('actsPage.table.deal')}</TableHead>
                      <SortableHead sortKey="total" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.total')}
                      </SortableHead>
                      <TableHead>{t('actsPage.table.status')}</TableHead>
                      <SortableHead sortKey="issued" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.issued')}
                      </SortableHead>
                      <TableHead className="text-right">{t('actsPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((a) => (
                      <TableRow key={a.id} {...openableRowProps(() => setSelectedId(a.id), `${t('common.open')} ${a.number}`)}>
                        <TableCell className="font-medium">{a.number}</TableCell>
                        <TableCell><DealLink dealId={a.deal} /></TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(a.total_amount))}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[a.status]}>
                            {t(`actsPage.status.${a.status}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {a.issued_at ? new Date(a.issued_at).toLocaleDateString() : '—'}
                        </TableCell>
                        <TableCell className="text-right" data-row-action>
                          <DocumentActions
                            request={() => ({ path: `crm/acts/${a.id}/download-pdf/` })}
                            filenameBase={`RailTech_Act_${a.id}`}
                            variant="ghost"
                            iconOnly
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
              </>
            );
          })()}
        </CardContent>
      </Card>

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelectedId(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.number}</SheetTitle>
              <SheetDescription>
                <Badge variant={STATUS_VARIANT[selected.status]}>{t(`actsPage.status.${selected.status}`)}</Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              {/* Чей сейчас ход — строка в терминах ДЕЙСТВИЯ, а не только код документа.
                  Эталон: Диадок «Ожидается подпись контрагента», DocuSign «Needs to Sign».
                  Считается из полей, которые сервер и так отдаёт. */}
              <ActTurnLine act={selected} />

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('actsPage.table.deal')}</Label><DealLink dealId={selected.deal} /></div>
                <div><Label>{t('actsPage.table.total')}</Label><p className="tabular-nums">{formatCurrency(Number(selected.total_amount))}</p></div>
                <div><Label>{t('actsPage.table.issued')}</Label><p className="text-muted-foreground">{selected.issued_at ? new Date(selected.issued_at).toLocaleDateString() : '—'}</p></div>
                {/* Акт ДВУСТОРОННИЙ (волна G2): выпускает исполнитель, принимает заказчик, и
                    сервер отдаёт обе подписи с именами. Карточка показывала одно поле «Подписан»
                    по legacy `signed_at` — кто выпустил и кто принял, было не узнать, хотя данные
                    приходили в том же ответе. */}
                <div>
                  <Label>{t('actsPage.issuedBy')}</Label>
                  <SignatureLine name={selected.issuer_signer_name} at={selected.issuer_signed_at} />
                </div>
                <div>
                  <Label>{t('actsPage.acceptedBy')}</Label>
                  <SignatureLine name={selected.acceptor_signer_name} at={selected.acceptor_signed_at} />
                </div>
              </div>

              {/* Причина возврата — рядом со статусом, а не под кнопками: это объяснение
                  текущего состояния документа, а не действие. */}
              {selected.rejection_reason ? (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {t('actsPage.rejectedWithReason', { reason: selected.rejection_reason })}
                </p>
              ) : null}
              <div className="flex flex-col gap-2">
                {/* Кнопка не ждёт готового файла: сервер сам ставит рендер и отвечает 202 (ARCH-03),
                    а `DocumentActions` опрашивает его по Retry-After. Пока условие требовало уже
                    существующий PDF, документ было НЕ ПОЛУЧИТЬ именно тогда, когда он ещё не
                    отрисован, — и без единого объяснения (аудит UI, U3). */}
                <DocumentActions
                  request={() => ({ path: `crm/acts/${selected.id}/download-pdf/` })}
                  filenameBase={`RailTech_Act_${selected.id}`}
                  size="default"
                />
                {selected.signed_file_url && (
                  <Button variant="outline" onClick={() => onDownloadSigned(selected)}>
                    <Download className="mr-2 h-4 w-4" />
                    {t('actsPage.downloadSigned')}
                  </Button>
                )}
                {/* Акт двусторонний (G2): принимает ЗАКАЗЧИК, и признак приходит с сервера —
                    выпустившей стороне «принять собственный акт» не предлагается. */}
                {selected.viewer_can_sign && (
                  <Button
                    onClick={() => onSign(selected.id)}
                    disabled={isViewer || signAct.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('actsPage.accept')}
                  </Button>
                )}
                {selected.viewer_can_reject && (
                  <Button
                    variant="outline"
                    onClick={() => setRejectOpen(true)}
                    disabled={isViewer || rejectAct.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Ban className="mr-2 h-4 w-4" />
                    {t('actsPage.reject')}
                  </Button>
                )}
                {selected.viewer_can_sign && (
                  <label
                    className={`flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm ${isViewer ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-accent'}`}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="h-4 w-4" />
                    <span>{t('actsPage.uploadSigned')}</span>
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.jpg,.jpeg,.png"
                      disabled={isViewer}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) onSign(selected.id, f);
                      }}
                    />
                  </label>
                )}
              </div>
            </div>
            <SheetFooter />
          </SheetContent>
        </Sheet>
      )}
      <RejectActDialog
        actNumber={selected?.number ?? null}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={async (reason) => { if (selected) await onReject(selected.id, reason); }}
      />
    </PageShell>
  );
}

export default ActsPage;
