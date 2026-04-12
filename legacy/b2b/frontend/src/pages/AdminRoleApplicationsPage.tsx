import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ClipboardCheck, Check, X } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { useRoleApplications, useApproveRoleApplication, useRejectRoleApplication } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { RoleApplication } from '@/api/accountsApi';

const statusVariant = (status: string) => {
  switch (status) {
    case 'APPROVED': return 'default';
    case 'PENDING': return 'secondary';
    case 'DOCUMENTS_REQUIRED': case 'PAYMENT_REQUIRED': return 'outline';
    case 'REJECTED': return 'destructive';
    default: return 'outline';
  }
};

export function AdminRoleApplicationsPage() {
  const { t } = useTranslation();
  const { data: apps, isLoading } = useRoleApplications();
  const approveMutation = useApproveRoleApplication();
  const rejectMutation = useRejectRoleApplication();

  const handleApprove = async (id: number) => {
    try {
      await approveMutation.mutateAsync(id);
      toast.success(t('admin.roleApps.approved'));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('common.error');
      toast.error(msg);
    }
  };

  const handleReject = async (id: number) => {
    try {
      await rejectMutation.mutateAsync({ id });
      toast.success(t('admin.roleApps.rejected'));
    } catch {
      toast.error(t('common.error'));
    }
  };

  const pending = apps?.filter(a => ['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'].includes(a.status)) ?? [];

  const stats = [
    { label: t('admin.roleApps.stats.total'), value: String(apps?.length ?? '—') },
    { label: t('admin.roleApps.stats.pending'), value: String(pending.length) },
    { label: t('admin.roleApps.stats.approved'), value: String(apps?.filter(a => a.status === 'APPROVED').length ?? '—') },
    { label: t('admin.roleApps.stats.rejected'), value: String(apps?.filter(a => a.status === 'REJECTED').length ?? '—') },
  ];

  return (
    <PageShell
      title={t('admin.roleApps.title')}
      description={t('admin.roleApps.description')}
      icon={<ClipboardCheck className="h-5 w-5" />}
      stats={stats}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !apps?.length ? (
            <EmptyState icon={<ClipboardCheck className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('admin.roleApps.table.company')}</TableHead>
                  <TableHead>{t('admin.roleApps.table.requestedType')}</TableHead>
                  <TableHead>{t('admin.roleApps.table.status')}</TableHead>
                  <TableHead>{t('admin.roleApps.table.submittedBy')}</TableHead>
                  <TableHead>{t('admin.roleApps.table.date')}</TableHead>
                  <TableHead className="text-center">{t('admin.roleApps.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {apps.map((app: RoleApplication) => (
                  <TableRow key={app.id}>
                    <TableCell>
                      <div>
                        <span className="font-medium">{app.company_name}</span>
                        <span className="block text-xs text-muted-foreground">{app.company_inn}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{app.requested_type_name}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(app.status)}>{app.status_display}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {app.submitted_by_email || '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {app.created_at ? new Date(app.created_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell className="text-center">
                      {['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'].includes(app.status) && (
                        <div className="flex justify-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleApprove(app.id)}
                            disabled={approveMutation.isPending}
                            title={t('admin.roleApps.approve')}
                          >
                            <Check className="h-3.5 w-3.5 text-success" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleReject(app.id)}
                            disabled={rejectMutation.isPending}
                            title={t('admin.roleApps.reject')}
                          >
                            <X className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </div>
                      )}
                      {app.status === 'APPROVED' && (
                        <Badge variant="default" className="gap-1">
                          <Check className="h-3 w-3" /> {t('admin.roleApps.approvedLabel')}
                        </Badge>
                      )}
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

export default AdminRoleApplicationsPage;
