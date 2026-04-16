import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ClipboardCheck, Check, X, Eye, FileText, Download,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
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

const isPending = (status: string) =>
  ['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'].includes(status);

/* ─── Reject Dialog ────────────────────────────────────────────────── */

function RejectDialog({
  app,
  open,
  onOpenChange,
}: {
  app: RoleApplication | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const rejectMutation = useRejectRoleApplication();

  const handleConfirm = async () => {
    if (!app) return;
    try {
      await rejectMutation.mutateAsync({ id: app.id, reason: reason.trim() || undefined });
      toast.success(t('admin.roleApps.rejected'));
      onOpenChange(false);
      setReason('');
    } catch {
      toast.error(t('common.error'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('admin.roleApps.rejectDialog.title')}</DialogTitle>
          <DialogDescription>
            {t('admin.roleApps.rejectDialog.description', { company: app?.company_name })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>{t('admin.roleApps.rejectDialog.reason')}</Label>
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('admin.roleApps.rejectDialog.reasonPlaceholder')}
            rows={4}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('admin.roleApps.rejectDialog.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={rejectMutation.isPending}
          >
            {t('admin.roleApps.rejectDialog.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ─── Document Link ────────────────────────────────────────────────── */

function DocLink({ url, label }: { url: string | null; label: string }) {
  const { t } = useTranslation();
  if (!url) {
    return (
      <span className="text-xs text-muted-foreground">{t('admin.roleApps.detail.noDocument')}</span>
    );
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      <Download className="h-3 w-3" />
      {label}
    </a>
  );
}

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

function DetailSheet({
  app,
  open,
  onOpenChange,
}: {
  app: RoleApplication | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  if (!app) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{t('admin.roleApps.detail.title')}</SheetTitle>
        </SheetHeader>

        <div className="mt-2 space-y-6 px-4">
          {/* Company info */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('admin.roleApps.detail.companyInfo')}</h3>
            <div className="rounded-lg border p-3 space-y-1">
              <p className="text-sm font-medium">{app.company_name}</p>
              <p className="text-xs text-muted-foreground">
                {t('admin.roleApps.detail.inn')}: {app.company_inn}
              </p>
            </div>
          </section>

          <Separator />

          {/* Role & Status */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.requestedRole')}</span>
              <Badge variant="outline">{app.requested_type_name}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.currentStatus')}</span>
              <Badge variant={statusVariant(app.status)}>{app.status_display}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.submittedBy')}</span>
              <span className="text-sm">{app.submitted_by_email || '—'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.submittedAt')}</span>
              <span className="text-sm">{app.created_at ? new Date(app.created_at).toLocaleDateString() : '—'}</span>
            </div>
          </section>

          <Separator />

          {/* Documents */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t('admin.roleApps.detail.documents')}
            </h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.contractFile')}</span>
                <DocLink url={app.contract_file} label={t('admin.roleApps.detail.download')} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.ndaFile')}</span>
                <DocLink url={app.nda_file} label={t('admin.roleApps.detail.download')} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.partnershipAgreement')}</span>
                <DocLink url={app.partnership_agreement} label={t('admin.roleApps.detail.download')} />
              </div>
            </div>
          </section>

          <Separator />

          {/* Review */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('admin.roleApps.detail.review')}</h3>
            {app.reviewed_by_email ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.reviewedBy')}</span>
                  <span className="text-sm">{app.reviewed_by_email}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">{t('admin.roleApps.detail.reviewedAt')}</span>
                  <span className="text-sm">{app.reviewed_at ? new Date(app.reviewed_at).toLocaleDateString() : '—'}</span>
                </div>
                {app.review_notes && (
                  <div className="rounded-lg border bg-muted/50 p-3">
                    <p className="text-xs text-muted-foreground mb-1">{t('admin.roleApps.detail.reviewNotes')}</p>
                    <p className="text-sm">{app.review_notes}</p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t('admin.roleApps.detail.noReview')}</p>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function AdminRoleApplicationsPage() {
  const { t } = useTranslation();
  const { data: apps, isLoading } = useRoleApplications();
  const approveMutation = useApproveRoleApplication();

  const [rejectTarget, setRejectTarget] = useState<RoleApplication | null>(null);
  const [detailTarget, setDetailTarget] = useState<RoleApplication | null>(null);

  const handleApprove = async (id: number) => {
    try {
      await approveMutation.mutateAsync(id);
      toast.success(t('admin.roleApps.approved'));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('common.error');
      toast.error(msg);
    }
  };

  const pending = apps?.filter(a => isPending(a.status)) ?? [];

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
                  <TableRow
                    key={app.id}
                    className="cursor-pointer"
                    onClick={() => setDetailTarget(app)}
                  >
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
                      {isPending(app.status) ? (
                        <div className="flex justify-center gap-1" onClick={(e) => e.stopPropagation()}>
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
                            onClick={() => setRejectTarget(app)}
                            title={t('admin.roleApps.reject')}
                          >
                            <X className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDetailTarget(app)}
                            title={t('admin.roleApps.detail.title')}
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ) : app.status === 'APPROVED' ? (
                        <Badge variant="default" className="gap-1">
                          <Check className="h-3 w-3" /> {t('admin.roleApps.approvedLabel')}
                        </Badge>
                      ) : app.status === 'REJECTED' ? (
                        <Badge variant="destructive" className="gap-1">
                          <X className="h-3 w-3" /> {t('admin.roleApps.rejectedLabel')}
                        </Badge>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <RejectDialog
        app={rejectTarget}
        open={!!rejectTarget}
        onOpenChange={(open) => { if (!open) setRejectTarget(null); }}
      />

      <DetailSheet
        app={detailTarget}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default AdminRoleApplicationsPage;
