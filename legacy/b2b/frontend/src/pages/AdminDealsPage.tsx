import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { toast } from 'sonner'; import { Handshake, Trash2, ArrowRight } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { Label } from '@/components/ui/label'; import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'; import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table'; import { Toolbar, SortableHead, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { useDeals, useDealStages, useForceChangeDealStage, useDeleteDeal } from '@/hooks/useCRM';
import { useCompanies } from '@/hooks/useAccounts';
import { DealStage, DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import type { Deal } from '@/api/crmApi';

const CLOSED_STAGES: string[] = [DealStage.CLOSED_WON, DealStage.CLOSED_LOST];

export function AdminDealsPage() {
  const { t } = useTranslation();
  // Реестр показывает список ЦЕЛИКОМ и печатает по нему счётчики — пейджера у него нет.
  const { data: deals, isLoading, isError, refetch } = useDeals(undefined, { fetchAll: true });
  const { data: stages } = useDealStages();
  const { data: companies } = useCompanies();
  const deleteMut = useDeleteDeal();
  const forceMut = useForceChangeDealStage();

  const listParams = useListParams(['stage', 'company'] as const, { urlKey: 'admin-deals', defaultOrdering: '-created_at' });
  const [forceTarget, setForceTarget] = useState<Deal | null>(null);
  const [targetStage, setTargetStage] = useState<string>('');
  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);

  function openForce(d: Deal) {
    setTargetStage('');
    setForceTarget(d);
  }
  async function onDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('adminDeals.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('adminDeals.deleteFailed'));
    }
  }

  async function runForceStage(reason: string) {
    if (!forceTarget || !targetStage) return;
    await forceMut.mutateAsync({ id: forceTarget.id, stage: targetStage, reason });
    toast.success(t('adminDeals.stageChanged'));
    setForceTarget(null);
    setTargetStage('');
  }

  const stats = [
    { label: t('adminDeals.stats.total'), value: String(deals?.length ?? '—') },
    { label: t('adminDeals.stats.open'), value: String(deals?.filter((d) => !CLOSED_STAGES.includes(d.stage_code ?? '')).length ?? '—') },
    { label: t('adminDeals.stats.won'), value: String(deals?.filter((d) => d.stage_code === DealStage.CLOSED_WON).length ?? '—') },
    { label: t('adminDeals.stats.lost'), value: String(deals?.filter((d) => d.stage_code === DealStage.CLOSED_LOST).length ?? '—') },
  ];

  // Localize a stage by CODE; fall back to the DB name only if the code is unknown.
  const stageLabel = (code?: string | null, fallback?: string | null): string =>
    code && DEAL_STAGE_LABEL_KEY[code] ? t(DEAL_STAGE_LABEL_KEY[code]) : (fallback ?? '—');
  const targetStageName = stageLabel(targetStage, stages?.find((s) => s.code === targetStage)?.name);

  return (
    <PageShell
      title={t('adminDeals.title')}
      description={t('adminDeals.description')}
      icon={<Handshake className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('adminDeals.searchPlaceholder')}
        filters={[
          {
            key: 'stage',
            value: listParams.filters.stage,
            onChange: (v) => listParams.setFilter('stage', v),
            allLabel: t('adminDeals.allStages'),
            options: (stages ?? []).map((s) => ({ value: s.code, label: stageLabel(s.code, s.name) })),
          },
          {
            key: 'company',
            value: listParams.filters.company,
            onChange: (v) => listParams.setFilter('company', v),
            allLabel: t('adminDeals.allCompanies'),
            options: (companies ?? []).map((c) => ({ value: String(c.id), label: c.name })),
          },
        ]}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(deals ?? [], listParams, {
              searchFields: (d) => [d.title, d.company_name, String(d.id)],
              filterPredicates: {
                stage: (d, v) => d.stage_code === v,
                company: (d, v) => String(d.company ?? '') === v,
              },
              sortAccessors: {
                id: (d) => d.id,
                title: (d) => d.title ?? '',
                company: (d) => d.company_name ?? '',
                stage: (d) => d.stage_name ?? '',
                created_at: (d) => d.created_at ?? '',
              },
            });
            if (isError) return <ErrorState onRetry={() => refetch()} />;
            if (isLoading) return <LoadingRows rows={5} />;
            if (!pageItems.length) return <EmptyState icon={<Handshake className="h-5 w-5" />} message={t('adminDeals.empty')} />;
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="id" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminDeals.table.id')}</SortableHead>
                      <SortableHead sortKey="title" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminDeals.table.title')}</SortableHead>
                      <SortableHead sortKey="company" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminDeals.table.company')}</SortableHead>
                      <SortableHead sortKey="stage" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminDeals.table.stage')}</SortableHead>
                      <SortableHead>{t('adminDeals.table.value')}</SortableHead>
                      <SortableHead className="text-right">{t('adminDeals.table.actions')}</SortableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="font-mono text-xs">#{d.id}</TableCell>
                        <TableCell>{d.title ?? '—'}</TableCell>
                        <TableCell className="text-muted-foreground text-xs">{d.company_name ?? '—'}</TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {d.stage_code && DEAL_STAGE_LABEL_KEY[d.stage_code]
                              ? t(DEAL_STAGE_LABEL_KEY[d.stage_code])
                              : (d.stage_name ?? '—')}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{d.total_value ?? '—'}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="sm" onClick={() => openForce(d)} title={t('adminDeals.forceChangeStage')}>
                              <ArrowRight className="h-3.5 w-3.5" />
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(d)}>
                              <Trash2 className="h-3.5 w-3.5 text-destructive" />
                            </Button>
                          </div>
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

      <ConfirmActionDialog
        open={Boolean(forceTarget)}
        onOpenChange={(v) => !v && setForceTarget(null)}
        title={t('adminDeals.forceChangeStage')}
        description={
          forceTarget
            ? t('adminDeals.forceDescription', {
                id: forceTarget.id,
                title: forceTarget.title ?? '',
              })
            : ''
        }
        diff={
          forceTarget && targetStage
            ? [
                {
                  label: t('adminDeals.table.stage'),
                  before: stageLabel(forceTarget.stage_code, forceTarget.stage_name),
                  after: targetStageName,
                },
              ]
            : undefined
        }
        extraFields={
          <div className="space-y-2">
            <Label className="text-xs">{t('adminDeals.newStage')}</Label>
            <Select value={targetStage || undefined} onValueChange={setTargetStage}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                {(stages ?? []).map((s) => (
                  <SelectItem
                    key={s.code}
                    value={s.code}
                    disabled={s.code === forceTarget?.stage_code}
                    className="text-xs"
                  >
                    {stageLabel(s.code, s.name)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
        requireReason
        reasonLabel={t('adminDeals.reason')}
        confirmLabel={t('adminDeals.apply')}
        variant="warning"
        onConfirm={(p) =>
          targetStage ? runForceStage(p.reason) : Promise.reject(new Error(t('adminDeals.pickStage')))
        }
        translateError={(code) => {
          const map: Record<string, string> = {
            REASON_REQUIRED: t('adminDeals.reasonRequired'),
            FSM_TRANSITION_NOT_ALLOWED: t('adminDeals.transitionNotAllowed'),
            CLOSED_WON_REQUIRES_SIGNED_CONTRACT: t('adminDeals.closedWonRequiresContract'),
            DEAL_STAGE_NOT_FOUND: t('adminDeals.stageNotFound'),
          };
          return map[code] || null;
        }}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('adminDeals.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('adminDeals.confirmDeleteDesc', { id: deleteTarget?.id })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('adminDeals.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('adminDeals.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminDealsPage;
