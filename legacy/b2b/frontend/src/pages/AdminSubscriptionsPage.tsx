import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CreditCard, Play, Pause, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHeader, TableRow,
} from '@/components/ui/table';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter,
} from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  useSubscriptions, useActivateSubscription, useSuspendSubscription,
  useCreateSubscription, useUpdateSubscription, useDeleteSubscription,
  useCompanies,
} from '@/hooks/useAccounts';
import { useCurrencies } from '@/hooks/useMasterData';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { Subscription } from '@/api/accountsApi';

const statusVariant = (status: string) => {
  switch (status) {
    case 'ACTIVE': return 'default';
    case 'TRIAL': return 'secondary';
    case 'SUSPENDED': case 'PAST_DUE': case 'CANCELLED': return 'destructive';
    default: return 'outline';
  }
};

const planVariant = (plan: string) => {
  switch (plan) {
    case 'PREMIUM': return 'default';
    case 'STANDARD': return 'secondary';
    default: return 'outline';
  }
};

const PLAN_OPTIONS = ['BASIC', 'STANDARD', 'PREMIUM'] as const;
const STATUS_OPTIONS = ['ACTIVE', 'TRIAL', 'SUSPENDED', 'PAST_DUE', 'CANCELLED'] as const;

/* ─── Form Sheet (create & edit) ───────────────────────────────────── */

type Draft = Partial<Subscription>;

function FormSheet({
  sub, open, onOpenChange,
}: {
  sub: Subscription | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const { data: companies } = useCompanies();
  const { data: currencies } = useCurrencies();
  const createMut = useCreateSubscription();
  const updateMut = useUpdateSubscription();

  const [draft, setDraft] = useState<Draft>(() => sub ?? {
    plan: 'BASIC', status: 'TRIAL', monthly_rate: '0',
  });

  useEffect(() => {
    setDraft(sub ?? { plan: 'BASIC', status: 'TRIAL', monthly_rate: '0' });
  }, [sub]);

  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(sub?.id);
  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.company || !draft.plan || !draft.monthly_rate) {
      toast.error(t('admin.subscriptions.requiredFields'));
      return;
    }
    const payload: Partial<Subscription> = {
      company: Number(draft.company),
      plan: draft.plan,
      status: draft.status,
      monthly_rate: String(draft.monthly_rate),
      currency: draft.currency ? Number(draft.currency) : null,
      valid_from: draft.valid_from || null,
      valid_until: draft.valid_until || null,
      notes: draft.notes ?? '',
    };
    try {
      if (isEdit && sub) {
        await updateMut.mutateAsync({ id: sub.id, data: payload });
        toast.success(t('admin.subscriptions.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('admin.subscriptions.created'));
      }
      onOpenChange(false);
    } catch {
      toast.error(t('admin.subscriptions.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('admin.subscriptions.edit') : t('admin.subscriptions.new')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('admin.subscriptions.fields.company')}</Label>
            <Select
              value={draft.company ? String(draft.company) : undefined}
              onValueChange={(v) => update({ company: Number(v) })}
              disabled={isEdit}
            >
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(companies ?? []).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.table.plan')}</Label>
              <Select value={draft.plan ?? undefined} onValueChange={(v) => update({ plan: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PLAN_OPTIONS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.table.status')}</Label>
              <Select value={draft.status ?? undefined} onValueChange={(v) => update({ status: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.fields.monthlyRate')}</Label>
              <Input
                type="number"
                step="0.01"
                value={draft.monthly_rate ?? ''}
                onChange={(e) => update({ monthly_rate: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.fields.currency')}</Label>
              <Select
                value={draft.currency ? String(draft.currency) : undefined}
                onValueChange={(v) => update({ currency: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(currencies ?? []).map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.fields.validFrom')}</Label>
              <Input type="date" value={draft.valid_from ?? ''} onChange={(e) => update({ valid_from: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.fields.validUntil')}</Label>
              <Input type="date" value={draft.valid_until ?? ''} onChange={(e) => update({ valid_until: e.target.value })} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('admin.subscriptions.fields.notes')}</Label>
            <Textarea rows={3} value={draft.notes ?? ''} onChange={(e) => update({ notes: e.target.value })} />
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('admin.subscriptions.save') : t('admin.subscriptions.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function AdminSubscriptionsPage() {
  const { t } = useTranslation();
  const { data: subscriptions, isLoading } = useSubscriptions();
  const activateMutation = useActivateSubscription();
  const suspendMutation = useSuspendSubscription();
  const deleteMut = useDeleteSubscription();

  const listParams = useListParams(['plan', 'status'] as const, { defaultOrdering: '-created_at' });
  const [editTarget, setEditTarget] = useState<Subscription | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Subscription | null>(null);

  const handleActivate = async (id: number) => {
    try {
      await activateMutation.mutateAsync(id);
      toast.success(t('admin.subscriptions.activated'));
    } catch {
      toast.error(t('common.error'));
    }
  };

  const handleSuspend = async (id: number) => {
    try {
      await suspendMutation.mutateAsync(id);
      toast.success(t('admin.subscriptions.suspended'));
    } catch {
      toast.error(t('common.error'));
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('admin.subscriptions.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('admin.subscriptions.deleteFailed'));
    }
  };

  const openNew = () => { setEditTarget(null); setSheetOpen(true); };
  const openEdit = (s: Subscription) => { setEditTarget(s); setSheetOpen(true); };

  const stats = [
    { label: t('admin.subscriptions.stats.total'), value: String(subscriptions?.length ?? '—') },
    { label: t('admin.subscriptions.stats.active'), value: String(subscriptions?.filter(s => s.status === 'ACTIVE').length ?? '—') },
    { label: t('admin.subscriptions.stats.trial'), value: String(subscriptions?.filter(s => s.status === 'TRIAL').length ?? '—') },
    { label: t('admin.subscriptions.stats.suspended'), value: String(subscriptions?.filter(s => s.status === 'SUSPENDED').length ?? '—') },
  ];

  return (
    <PageShell
      title={t('admin.subscriptions.title')}
      description={t('admin.subscriptions.description')}
      icon={<CreditCard className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('admin.subscriptions.searchPlaceholder')}
        filters={[
          {
            key: 'plan',
            value: listParams.filters.plan,
            onChange: (v) => listParams.setFilter('plan', v),
            allLabel: t('admin.subscriptions.allPlans'),
            options: PLAN_OPTIONS.map((p) => ({ value: p, label: p })),
          },
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('admin.subscriptions.allStatuses'),
            options: STATUS_OPTIONS.map((s) => ({ value: s, label: s })),
          },
        ]}
        newLabel={t('admin.subscriptions.new')}
        onNew={openNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(subscriptions ?? [], listParams, {
              searchFields: (s) => [s.company_name, s.company_inn, s.plan, s.status],
              filterPredicates: {
                plan: (s, v) => s.plan === v,
                status: (s, v) => s.status === v,
              },
              sortAccessors: {
                company: (s) => s.company_name ?? '',
                plan: (s) => s.plan ?? '',
                status: (s) => s.status ?? '',
                rate: (s) => Number(s.monthly_rate) || 0,
                valid_until: (s) => s.valid_until ?? '',
                created_at: (s) => s.created_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (!pageItems.length) return <EmptyState icon={<CreditCard className="h-5 w-5" />} message={t('pages.common.noData')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="company" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('admin.subscriptions.table.company')}</SortableHead>
                  <SortableHead sortKey="plan" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('admin.subscriptions.table.plan')}</SortableHead>
                  <SortableHead sortKey="status" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('admin.subscriptions.table.status')}</SortableHead>
                  <SortableHead sortKey="rate" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('admin.subscriptions.table.rate')}</SortableHead>
                  <SortableHead sortKey="valid_until" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('admin.subscriptions.table.validUntil')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}} className="text-center">{t('admin.subscriptions.table.actions')}</SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((sub: Subscription) => (
                  <TableRow
                    key={sub.id}
                    className="cursor-pointer"
                    onClick={() => openEdit(sub)}
                  >
                    <TableCell>
                      <div>
                        <span className="font-medium">{sub.company_name}</span>
                        <span className="block text-xs text-muted-foreground">{sub.company_inn}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={planVariant(sub.plan)}>{sub.plan_display}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(sub.status)}>{sub.status_display}</Badge>
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {sub.monthly_rate} {sub.currency_code || ''}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {sub.valid_until || '—'}
                    </TableCell>
                    <TableCell className="text-center">
                      <div className="flex justify-center gap-1" onClick={(e) => e.stopPropagation()}>
                        {sub.status !== 'ACTIVE' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleActivate(sub.id)}
                            disabled={activateMutation.isPending}
                            title={t('admin.subscriptions.activated')}
                          >
                            <Play className="h-3.5 w-3.5 text-success" />
                          </Button>
                        )}
                        {sub.status === 'ACTIVE' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSuspend(sub.id)}
                            disabled={suspendMutation.isPending}
                            title={t('admin.subscriptions.suspended')}
                          >
                            <Pause className="h-3.5 w-3.5 text-warning" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEdit(sub)}
                          title={t('admin.subscriptions.edit')}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDeleteTarget(sub)}
                          title={t('admin.subscriptions.delete')}
                        >
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

      <FormSheet
        sub={editTarget}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('admin.subscriptions.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('admin.subscriptions.confirmDeleteDesc', { name: deleteTarget?.company_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('admin.subscriptions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleteMut.isPending}>
              {t('admin.subscriptions.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminSubscriptionsPage;
