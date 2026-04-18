import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Handshake, Trash2, ArrowRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { useDeals, useDealStages, useForceChangeDealStage, useDeleteDeal } from '@/hooks/useCRM';
import { useCompanies } from '@/hooks/useAccounts';
import type { Deal } from '@/api/crmApi';

function ForceStageSheet({
  deal, open, onOpenChange,
}: {
  deal: Deal | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const { data: stages } = useDealStages();
  const forceMut = useForceChangeDealStage();
  const [stage, setStage] = useState<string>('');
  const [reason, setReason] = useState<string>('');

  const submit = async () => {
    if (!deal || !stage) return;
    try {
      await forceMut.mutateAsync({ id: deal.id, stage, reason });
      toast.success(t('adminDeals.stageChanged'));
      onOpenChange(false);
      setStage('');
      setReason('');
    } catch {
      toast.error(t('adminDeals.stageChangeFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t('adminDeals.forceChangeStage')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="text-sm">
            <span className="text-muted-foreground">{t('adminDeals.currentStage')}: </span>
            <Badge variant="outline">{deal?.stage_name ?? '—'}</Badge>
          </div>
          <div className="space-y-2">
            <Label>{t('adminDeals.newStage')}</Label>
            <Select value={stage || undefined} onValueChange={setStage}>
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(stages ?? []).map((s) => (
                  <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('adminDeals.reason')}</Label>
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('adminDeals.reasonPlaceholder')}
            />
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={forceMut.isPending || !stage} className="w-full">
            {t('adminDeals.apply')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminDealsPage() {
  const { t } = useTranslation();
  const { data: deals, isLoading } = useDeals();
  const { data: stages } = useDealStages();
  const { data: companies } = useCompanies();
  const deleteMut = useDeleteDeal();

  const listParams = useListParams(['stage', 'company'] as const, { defaultOrdering: '-created_at' });
  const [forceTarget, setForceTarget] = useState<Deal | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);

  const onForce = (d: Deal) => {
    setForceTarget(d);
    setSheetOpen(true);
  };
  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('adminDeals.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('adminDeals.deleteFailed'));
    }
  };

  const stats = [
    { label: t('adminDeals.stats.total'), value: String(deals?.length ?? '—') },
    { label: t('adminDeals.stats.open'), value: String(deals?.filter((d) => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? '')).length ?? '—') },
    { label: t('adminDeals.stats.won'), value: String(deals?.filter((d) => d.stage_code === 'CLOSED_WON').length ?? '—') },
    { label: t('adminDeals.stats.lost'), value: String(deals?.filter((d) => d.stage_code === 'CLOSED_LOST').length ?? '—') },
  ];

  return (
    <PageShell
      title={t('adminDeals.title')}
      description={t('adminDeals.description')}
      icon={<Handshake className="h-5 w-5" />}
      stats={stats}
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
            options: (stages ?? []).map((s) => ({ value: s.code, label: s.name })),
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
                  <SortableHead sortKey="" current="" onChange={() => {}}>{t('adminDeals.table.value')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}} className="text-right">{t('adminDeals.table.actions')}</SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-mono text-xs">#{d.id}</TableCell>
                    <TableCell>{d.title ?? '—'}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{d.company_name ?? '—'}</TableCell>
                    <TableCell><Badge variant="outline">{d.stage_name ?? '—'}</Badge></TableCell>
                    <TableCell className="font-mono text-xs">{d.total_value ?? '—'}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onForce(d)} title={t('adminDeals.forceChangeStage')}>
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

      <ForceStageSheet deal={forceTarget} open={sheetOpen} onOpenChange={setSheetOpen} />

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
