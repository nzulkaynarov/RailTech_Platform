import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CreditCard, Play, Pause, Pencil, Trash2, Wallet } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { AdminDataTable } from '@/components/Admin/AdminDataTable';
import { useAdminTableQueryState } from '@/components/Admin/useAdminTableQueryState';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import { useBulkSubscriptionStatus } from '@/hooks/useAdmin';
import { useDraftState } from '@/hooks/useDraftState';
import { Tabs as TabsRoot, TabsList as TabsListRoot, TabsTrigger as TabsTriggerRoot, TabsContent as TabsContentRoot } from '@/components/ui/tabs';
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
import { PageShell, ErrorState } from './shared/PageShell';
import { translateApiError } from '@/lib/apiError';
import { SubscriptionPayDialog } from '@/components/Admin/SubscriptionPayDialog';
import { subscriptionPlanLabelKey, subscriptionStatusLabelKey } from '@/lib/codes';
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

/**
 * Localized labels for the subscription plan/status CODEs. The backend `plan_display` /
 * `status_display` fields are `get_FOO_display()` output — Russian-only at the source —
 * so they are kept only as a fallback for a code this map does not know.
 */
function useSubscriptionLabels() {
  const { t } = useTranslation();
  return {
    planLabel: (code?: string | null, fallback?: string | null): string => {
      const key = subscriptionPlanLabelKey(code);
      return key ? t(key) : fallback || code || '';
    },
    statusLabel: (code?: string | null, fallback?: string | null): string => {
      const key = subscriptionStatusLabelKey(code);
      return key ? t(key) : fallback || code || '';
    },
  };
}

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
  const { planLabel, statusLabel } = useSubscriptionLabels();
  const { data: companies } = useCompanies();
  const { data: currencies } = useCurrencies();
  const createMut = useCreateSubscription();
  const updateMut = useUpdateSubscription();

  // Черновик собирается из редактируемой подписки прямо в рендере.
  const [draft, setDraft] = useDraftState<typeof sub, Draft>(
    sub,
    (source) => source ?? { plan: 'BASIC', status: 'TRIAL', monthly_rate: '0' },
  );

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
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('admin.subscriptions.edit') : t('admin.subscriptions.new')}</SheetTitle>
        </SheetHeader>

        <TabsRoot defaultValue="details" className="mt-4 px-4">
          <TabsListRoot className="grid w-full grid-cols-2">
            <TabsTriggerRoot value="details" className="text-xs">
              {t('admin.subscriptions.tabs.details')}
            </TabsTriggerRoot>
            <TabsTriggerRoot value="timeline" disabled={!isEdit} className="text-xs">
              {t('platformAdmin.activity.title')}
            </TabsTriggerRoot>
          </TabsListRoot>
          <TabsContentRoot value="timeline" className="mt-4">
            {isEdit && sub ? (
              <AdminActivityTimeline entityType="subscription" entityId={sub.id} />
            ) : null}
          </TabsContentRoot>
          <TabsContentRoot value="details" className="mt-4 space-y-4">
          {isEdit && sub ? (
            <DetailKPIGrid
              columns={4}
              items={[
                {
                  label: t('admin.subscriptions.table.plan'),
                  value: planLabel(sub.plan, sub.plan_display),
                },
                {
                  label: t('admin.subscriptions.table.status'),
                  value: statusLabel(sub.status, sub.status_display),
                  tone:
                    sub.status === 'ACTIVE'
                      ? 'success'
                      : sub.status === 'SUSPENDED' || sub.status === 'PAST_DUE'
                        ? 'destructive'
                        : sub.status === 'TRIAL'
                          ? 'info'
                          : 'default',
                },
                {
                  label: t('admin.subscriptions.fields.monthlyRate'),
                  value: sub.monthly_rate
                    ? `${sub.monthly_rate} ${sub.currency_code || ''}`
                    : '—',
                },
                {
                  label: t('admin.subscriptions.fields.validUntil'),
                  value: sub.valid_until || '—',
                  hint: sub.valid_from
                    ? t('admin.subscriptions.validFromHint', {
                        date: sub.valid_from,
                      })
                    : undefined,
                },
              ]}
            />
          ) : null}
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
                  {PLAN_OPTIONS.map((planCode) => (
                    <SelectItem key={planCode} value={planCode}>{planLabel(planCode)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('admin.subscriptions.table.status')}</Label>
              <Select value={draft.status ?? undefined} onValueChange={(v) => update({ status: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((statusCode) => (
                    <SelectItem key={statusCode} value={statusCode}>{statusLabel(statusCode)}</SelectItem>
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
          </TabsContentRoot>
        </TabsRoot>

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

const STORAGE_KEY = 'adminSubscriptions';

export function AdminSubscriptionsPage() {
  const { t } = useTranslation();
  const { planLabel, statusLabel } = useSubscriptionLabels();
  const activateMutation = useActivateSubscription();
  const suspendMutation = useSuspendSubscription();
  const deleteMut = useDeleteSubscription();
  const bulkStatus = useBulkSubscriptionStatus();

  const tableState = useAdminTableQueryState(STORAGE_KEY);
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (tableState.search) p.search = tableState.search;
    const tab = tableState.tab || 'all';
    if (tab.startsWith('status:')) p.status = tab.slice(7);
    else if (tab.startsWith('plan:')) p.plan = tab.slice(5);
    return Object.keys(p).length ? p : undefined;
  }, [tableState.search, tableState.tab]);

  const { data: allSubs = [] } = useSubscriptions();
  const { data: subscriptions = [], isLoading, isError, refetch } = useSubscriptions(queryParams);

  const [editTarget, setEditTarget] = useState<Subscription | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Subscription | null>(null);
  const [payTargetId, setPayTargetId] = useState<number | null>(null);
  const [confirmBulkSuspend, setConfirmBulkSuspend] = useState<Subscription[] | null>(null);
  const [suspendTarget, setSuspendTarget] = useState<Subscription | null>(null);

  const filtered = subscriptions;

  const counts = useMemo(() => ({
    all: allSubs.length,
    active: allSubs.filter((s) => s.status === 'ACTIVE').length,
    trial: allSubs.filter((s) => s.status === 'TRIAL').length,
    suspended: allSubs.filter((s) => s.status === 'SUSPENDED').length,
    pastDue: allSubs.filter((s) => s.status === 'PAST_DUE').length,
  }), [allSubs]);

  async function handleActivate(id: number) {
    try {
      await activateMutation.mutateAsync(id);
      toast.success(t('admin.subscriptions.activated'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  async function runSuspend() {
    if (!suspendTarget) return;
    try {
      await suspendMutation.mutateAsync(suspendTarget.id);
      toast.success(t('admin.subscriptions.suspended'));
      setSuspendTarget(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('admin.subscriptions.deleted'));
      setDeleteTarget(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  async function runBulkSuspend(rows: Subscription[], reason: string) {
    const res = await bulkStatus.mutateAsync({
      ids: rows.map((r) => r.id),
      status: 'SUSPENDED',
      reason,
    });
    toast.success(t('admin.subscriptions.bulkResult', { affected: res.affected }));
    setConfirmBulkSuspend(null);
  }

  async function runBulkActivate(rows: Subscription[]) {
    const res = await bulkStatus.mutateAsync({
      ids: rows.map((r) => r.id),
      status: 'ACTIVE',
    });
    toast.success(t('admin.subscriptions.bulkResult', { affected: res.affected }));
  }

  const openNew = () => { setEditTarget(null); setSheetOpen(true); };
  const openEdit = (s: Subscription) => { setEditTarget(s); setSheetOpen(true); };

  const stats = [
    { label: t('admin.subscriptions.stats.total'), value: String(counts.all) },
    { label: t('admin.subscriptions.stats.active'), value: String(counts.active) },
    { label: t('admin.subscriptions.stats.trial'), value: String(counts.trial) },
    { label: t('admin.subscriptions.stats.suspended'), value: String(counts.suspended) },
  ];

  return (
    <PageShell
      title={t('admin.subscriptions.title')}
      description={t('admin.subscriptions.description')}
      icon={<CreditCard className="h-5 w-5" />}
      stats={stats}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
      <AdminDataTable<Subscription>
        storageKey={STORAGE_KEY}
        rows={filtered}
        getRowId={(s) => s.id}
        isLoading={isLoading}
        onRowClick={openEdit}
        searchPlaceholder={t('admin.subscriptions.searchPlaceholder')}
        exportUrl={`${window.location.origin}/api/v1/accounts/subscriptions/export/`}
        primaryAction={
          <Button size="sm" className="h-8 text-xs" onClick={openNew}>
            {t('admin.subscriptions.new')}
          </Button>
        }
        tabs={[
          { id: 'all', label: t('common.all'), count: counts.all },
          { id: 'status:ACTIVE', label: t('admin.subscriptions.stats.active'), count: counts.active },
          { id: 'status:TRIAL', label: t('admin.subscriptions.stats.trial'), count: counts.trial },
          { id: 'status:PAST_DUE', label: statusLabel('PAST_DUE'), count: counts.pastDue },
          { id: 'status:SUSPENDED', label: t('admin.subscriptions.stats.suspended'), count: counts.suspended },
          { id: 'plan:BASIC', label: planLabel('BASIC') },
          { id: 'plan:STANDARD', label: planLabel('STANDARD') },
          { id: 'plan:PREMIUM', label: planLabel('PREMIUM') },
        ]}
        columns={[
          {
            id: 'company',
            header: t('admin.subscriptions.table.company'),
            cell: (s) => (
              <div>
                <div className="font-medium">{s.company_name}</div>
                <div className="text-xs text-muted-foreground">{s.company_inn}</div>
              </div>
            ),
            alwaysVisible: true,
          },
          {
            id: 'plan',
            header: t('admin.subscriptions.table.plan'),
            cell: (s) => <Badge variant={planVariant(s.plan)}>{planLabel(s.plan, s.plan_display)}</Badge>,
          },
          {
            id: 'status',
            header: t('admin.subscriptions.table.status'),
            cell: (s) => <Badge variant={statusVariant(s.status)}>{statusLabel(s.status, s.status_display)}</Badge>,
          },
          {
            id: 'rate',
            header: t('admin.subscriptions.table.rate'),
            cell: (s) => (
              <span className="tabular-nums">
                {s.monthly_rate} {s.currency_code || ''}
              </span>
            ),
          },
          {
            id: 'validUntil',
            header: t('admin.subscriptions.table.validUntil'),
            cell: (s) => <span className="text-muted-foreground">{s.valid_until || '—'}</span>,
          },
        ]}
        rowActions={[
          {
            id: 'activate',
            label: t('admin.subscriptions.activated'),
            icon: <Play className="h-3.5 w-3.5 text-success" />,
            onRun: (s) => {
              if (s.status === 'ACTIVE') return;
              handleActivate(s.id);
            },
          },
          {
            id: 'suspend',
            label: t('admin.subscriptions.suspended'),
            icon: <Pause className="h-3.5 w-3.5 text-warning" />,
            onRun: (s) => {
              if (s.status !== 'ACTIVE') return;
              setSuspendTarget(s);
            },
          },
          {
            id: 'pay',
            label: t('subscriptionPay.title'),
            icon: <Wallet className="h-3.5 w-3.5 text-primary" />,
            onRun: (s) => {
              if (s.status === 'CANCELLED') return;
              setPayTargetId(s.id);
            },
          },
          {
            id: 'edit',
            label: t('admin.subscriptions.edit'),
            icon: <Pencil className="h-3.5 w-3.5" />,
            onRun: openEdit,
          },
          {
            id: 'delete',
            label: t('admin.subscriptions.delete'),
            icon: <Trash2 className="h-3.5 w-3.5" />,
            variant: 'destructive',
            onRun: (s) => setDeleteTarget(s),
          },
        ]}
        bulkActions={[
          {
            id: 'bulk-activate',
            label: t('admin.subscriptions.bulkActivate'),
            onRun: (rows) => runBulkActivate(rows),
          },
          {
            id: 'bulk-suspend',
            label: t('admin.subscriptions.bulkSuspend'),
            variant: 'destructive',
            onRun: (rows) => setConfirmBulkSuspend(rows),
          },
        ]}
        emptyIcon={<CreditCard className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('pages.common.noData')}
      />
      )}

      <FormSheet
        sub={editTarget}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />

      <SubscriptionPayDialog
        subscriptionId={payTargetId}
        open={payTargetId !== null}
        onOpenChange={(o) => !o && setPayTargetId(null)}
      />

      <ConfirmActionDialog
        open={Boolean(confirmBulkSuspend)}
        onOpenChange={(v) => !v && setConfirmBulkSuspend(null)}
        title={t('admin.subscriptions.bulkSuspend')}
        description={
          confirmBulkSuspend
            ? t('admin.subscriptions.bulkSuspendDesc', { count: confirmBulkSuspend.length })
            : ''
        }
        requireReason
        reasonTemplates={[
          t('admin.subscriptions.suspendTemplates.nonPayment'),
          t('admin.subscriptions.suspendTemplates.fraud'),
          t('admin.subscriptions.suspendTemplates.other'),
        ]}
        confirmLabel={t('admin.subscriptions.suspended')}
        variant="destructive"
        onConfirm={(p) =>
          confirmBulkSuspend ? runBulkSuspend(confirmBulkSuspend, p.reason) : Promise.resolve()
        }
        translateError={(code) => translateApiError(code)}
      />

      <ConfirmActionDialog
        open={Boolean(suspendTarget)}
        onOpenChange={(v) => !v && setSuspendTarget(null)}
        title={t('admin.subscriptions.suspendDialog.title')}
        description={
          suspendTarget
            ? t('admin.subscriptions.suspendDialog.description', { name: suspendTarget.company_name })
            : ''
        }
        requireReason
        reasonTemplates={[
          t('admin.subscriptions.suspendTemplates.nonPayment'),
          t('admin.subscriptions.suspendTemplates.fraud'),
          t('admin.subscriptions.suspendTemplates.other'),
        ]}
        confirmLabel={t('admin.subscriptions.suspended')}
        variant="destructive"
        onConfirm={() => runSuspend()}
        translateError={(code) => translateApiError(code)}
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
