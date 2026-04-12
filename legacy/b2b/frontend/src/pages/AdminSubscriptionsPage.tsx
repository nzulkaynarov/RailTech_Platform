import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CreditCard, Play, Pause } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
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

export function AdminSubscriptionsPage() {
  const { t } = useTranslation();
  const { data: subscriptions, isLoading } = useSubscriptions();
  const activateMutation = useActivateSubscription();
  const suspendMutation = useSuspendSubscription();

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
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !subscriptions?.length ? (
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
                {subscriptions.map((sub: Subscription) => (
                  <TableRow key={sub.id}>
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
                      <div className="flex justify-center gap-1">
                        {sub.status !== 'ACTIVE' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleActivate(sub.id)}
                            disabled={activateMutation.isPending}
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
                          >
                            <Pause className="h-3.5 w-3.5 text-warning" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default AdminSubscriptionsPage;
