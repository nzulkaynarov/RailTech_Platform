import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CreditCard, Play, Pause, Eye, Search } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useSubscriptions, useActivateSubscription, useSuspendSubscription } from '@/hooks/useAccounts';
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

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

function DetailSheet({
  sub,
  open,
  onOpenChange,
}: {
  sub: Subscription | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  if (!sub) return null;

  const rows: { label: string; value: string }[] = [
    { label: t('admin.subscriptions.detail.monthlyRate'), value: `${sub.monthly_rate} ${sub.currency_code || ''}` },
    { label: t('admin.subscriptions.detail.validFrom'), value: sub.valid_from || '—' },
    { label: t('admin.subscriptions.detail.validUntil'), value: sub.valid_until || '—' },
    { label: t('admin.subscriptions.detail.lastPayment'), value: sub.last_payment_date || '—' },
    { label: t('admin.subscriptions.detail.nextPayment'), value: sub.next_payment_date || '—' },
    { label: t('admin.subscriptions.detail.created'), value: sub.created_at ? new Date(sub.created_at).toLocaleDateString() : '—' },
    { label: t('admin.subscriptions.detail.updated'), value: sub.updated_at ? new Date(sub.updated_at).toLocaleDateString() : '—' },
  ];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t('admin.subscriptions.detail.title')}</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Company info */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('admin.subscriptions.detail.companyInfo')}</h3>
            <div className="rounded-lg border p-3 space-y-1">
              <p className="text-sm font-medium">{sub.company_name}</p>
              <p className="text-xs text-muted-foreground">
                {t('admin.subscriptions.detail.inn')}: {sub.company_inn}
              </p>
            </div>
          </section>

          <Separator />

          {/* Plan & Status */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('admin.subscriptions.detail.planAndStatus')}</h3>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.subscriptions.table.plan')}</span>
              <Badge variant={planVariant(sub.plan)}>{sub.plan_display}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.subscriptions.table.status')}</span>
              <Badge variant={statusVariant(sub.status)}>{sub.status_display}</Badge>
            </div>
          </section>

          <Separator />

          {/* Billing */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('admin.subscriptions.detail.billing')}</h3>
            {rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{r.label}</span>
                <span className="text-sm tabular-nums">{r.value}</span>
              </div>
            ))}
          </section>

          <Separator />

          {/* Notes */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('admin.subscriptions.detail.notes')}</h3>
            {sub.notes ? (
              <div className="rounded-lg border bg-muted/50 p-3">
                <p className="text-sm">{sub.notes}</p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t('admin.subscriptions.detail.noNotes')}</p>
            )}
          </section>
        </div>
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

  const [search, setSearch] = useState('');
  const [planFilter, setPlanFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [detailTarget, setDetailTarget] = useState<Subscription | null>(null);

  const filtered = useMemo(() => {
    if (!subscriptions) return [];
    return subscriptions.filter((s) => {
      const matchesSearch = !search ||
        s.company_name.toLowerCase().includes(search.toLowerCase()) ||
        s.company_inn.includes(search);
      const matchesPlan = planFilter === 'all' || s.plan === planFilter;
      const matchesStatus = statusFilter === 'all' || s.status === statusFilter;
      return matchesSearch && matchesPlan && matchesStatus;
    });
  }, [subscriptions, search, planFilter, statusFilter]);

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
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t('admin.subscriptions.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={planFilter} onValueChange={setPlanFilter}>
          <SelectTrigger className="w-full sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('admin.subscriptions.allPlans')}</SelectItem>
            {PLAN_OPTIONS.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('admin.subscriptions.allStatuses')}</SelectItem>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !filtered.length ? (
            <EmptyState icon={<CreditCard className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('admin.subscriptions.table.company')}</TableHead>
                  <TableHead>{t('admin.subscriptions.table.plan')}</TableHead>
                  <TableHead>{t('admin.subscriptions.table.status')}</TableHead>
                  <TableHead>{t('admin.subscriptions.table.rate')}</TableHead>
                  <TableHead>{t('admin.subscriptions.table.validUntil')}</TableHead>
                  <TableHead className="text-center">{t('admin.subscriptions.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((sub: Subscription) => (
                  <TableRow
                    key={sub.id}
                    className="cursor-pointer"
                    onClick={() => setDetailTarget(sub)}
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
                          onClick={() => setDetailTarget(sub)}
                          title={t('admin.subscriptions.detail.title')}
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DetailSheet
        sub={detailTarget}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default AdminSubscriptionsPage;
