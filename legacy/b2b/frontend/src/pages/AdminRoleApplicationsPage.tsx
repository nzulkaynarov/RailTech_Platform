import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ClipboardCheck, Check, X, FileText, Download,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useRoleApplications, useApproveRoleApplication, useRejectRoleApplication } from '@/hooks/useAccounts';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import { AdminDetailLayout } from '@/components/Admin/AdminDetailLayout';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { PageShell } from './shared/PageShell';
import type { RoleApplication } from '@/api/accountsApi';

const STORAGE_KEY = 'adminRoleApps';

const statusVariant = (status: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
  switch (status) {
    case 'APPROVED': return 'default';
    case 'PENDING': return 'secondary';
    case 'DOCUMENTS_REQUIRED':
    case 'PAYMENT_REQUIRED': return 'outline';
    case 'REJECTED': return 'destructive';
    default: return 'outline';
  }
};

const isPending = (status: string) =>
  ['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'].includes(status);

// ───────────────────────────────────────────────────────────────────────
// Detail sheet
// ───────────────────────────────────────────────────────────────────────

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

  const overview = (
    <div className="space-y-4">
      <dl className="grid grid-cols-1 gap-2 rounded-md border p-3 text-xs sm:grid-cols-2">
        <div className="flex items-start justify-between gap-2">
          <dt className="text-muted-foreground">{t('admin.roleApps.detail.inn')}</dt>
          <dd className="text-right font-medium tabular-nums">{app.company_inn}</dd>
        </div>
        <div className="flex items-start justify-between gap-2">
          <dt className="text-muted-foreground">{t('admin.roleApps.detail.requestedRole')}</dt>
          <dd className="text-right">
            <Badge variant="outline">{app.requested_type_name}</Badge>
          </dd>
        </div>
        <div className="flex items-start justify-between gap-2">
          <dt className="text-muted-foreground">{t('admin.roleApps.detail.currentStatus')}</dt>
          <dd className="text-right">
            <Badge variant={statusVariant(app.status)}>{app.status_display}</Badge>
          </dd>
        </div>
        <div className="flex items-start justify-between gap-2">
          <dt className="text-muted-foreground">{t('admin.roleApps.detail.submittedBy')}</dt>
          <dd className="text-right">{app.submitted_by_email || '—'}</dd>
        </div>
        <div className="flex items-start justify-between gap-2">
          <dt className="text-muted-foreground">{t('admin.roleApps.detail.submittedAt')}</dt>
          <dd className="text-right">
            {app.created_at ? new Date(app.created_at).toLocaleDateString() : '—'}
          </dd>
        </div>
      </dl>

      {app.reviewed_by_email ? (
        <div className="rounded-md border p-3 text-xs">
          <div className="mb-1 font-semibold">{t('admin.roleApps.detail.review')}</div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t('admin.roleApps.detail.reviewedBy')}</span>
            <span>{app.reviewed_by_email}</span>
          </div>
          <div className="mt-1 flex justify-between">
            <span className="text-muted-foreground">{t('admin.roleApps.detail.reviewedAt')}</span>
            <span>{app.reviewed_at ? new Date(app.reviewed_at).toLocaleDateString() : '—'}</span>
          </div>
          {app.review_notes ? (
            <div className="mt-2 rounded bg-muted/50 p-2">
              <div className="text-muted-foreground">{t('admin.roleApps.detail.reviewNotes')}</div>
              <div>{app.review_notes}</div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  const documents = (
    <div className="space-y-2 rounded-md border p-3 text-xs">
      <h3 className="flex items-center gap-2 text-xs font-semibold">
        <FileText className="h-3.5 w-3.5" />
        {t('admin.roleApps.detail.documents')}
      </h3>
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">{t('admin.roleApps.detail.contractFile')}</span>
        <DocLink url={app.contract_file} label={t('admin.roleApps.detail.download')} />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">{t('admin.roleApps.detail.ndaFile')}</span>
        <DocLink url={app.nda_file} label={t('admin.roleApps.detail.download')} />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">{t('admin.roleApps.detail.partnershipAgreement')}</span>
        <DocLink url={app.partnership_agreement} label={t('admin.roleApps.detail.download')} />
      </div>
    </div>
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto p-0 sm:max-w-2xl">
        <SheetHeader className="sr-only">
          <SheetTitle>{app.company_name}</SheetTitle>
        </SheetHeader>
        <div className="p-4 md:p-5">
          <AdminDetailLayout
            title={app.company_name}
            subtitle={app.requested_type_name}
            leading={
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                <ClipboardCheck className="h-5 w-5" />
              </div>
            }
            badges={[{ label: app.status_display, variant: statusVariant(app.status) }]}
            tabs={[
              { id: 'overview', label: t('admin.roleApps.detail.title'), content: overview },
              { id: 'documents', label: t('admin.roleApps.detail.documents'), content: documents },
              {
                id: 'timeline',
                label: t('platformAdmin.activity.title'),
                content: <AdminActivityTimeline entityType="role_application" entityId={app.id} />,
              },
            ]}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ───────────────────────────────────────────────────────────────────────
// List page
// ───────────────────────────────────────────────────────────────────────

export function AdminRoleApplicationsPage() {
  const { t } = useTranslation();
  const { data: apps = [], isLoading } = useRoleApplications();
  const approveMutation = useApproveRoleApplication();
  const rejectMutation = useRejectRoleApplication();

  const [detailTarget, setDetailTarget] = useState<RoleApplication | null>(null);
  const [confirm, setConfirm] = useState<null | {
    kind: 'approve' | 'reject';
    app: RoleApplication;
  }>(null);

  const tableState = useAdminTableQueryState(STORAGE_KEY);

  const filtered = useMemo(() => {
    const q = tableState.search.toLowerCase();
    return apps.filter((a) => {
      const tab = tableState.tab || 'all';
      if (tab === 'pending' && !isPending(a.status)) return false;
      if (tab === 'approved' && a.status !== 'APPROVED') return false;
      if (tab === 'rejected' && a.status !== 'REJECTED') return false;
      if (!q) return true;
      return (
        a.company_name.toLowerCase().includes(q) ||
        (a.company_inn || '').toLowerCase().includes(q) ||
        (a.submitted_by_email || '').toLowerCase().includes(q)
      );
    });
  }, [apps, tableState.search, tableState.tab]);

  const counts = useMemo(() => ({
    all: apps.length,
    pending: apps.filter((a) => isPending(a.status)).length,
    approved: apps.filter((a) => a.status === 'APPROVED').length,
    rejected: apps.filter((a) => a.status === 'REJECTED').length,
  }), [apps]);

  async function runApprove(app: RoleApplication) {
    await approveMutation.mutateAsync(app.id);
    toast.success(t('admin.roleApps.approved'));
    setConfirm(null);
  }

  async function runReject(app: RoleApplication, reason: string) {
    await rejectMutation.mutateAsync({ id: app.id, reason });
    toast.success(t('admin.roleApps.rejected'));
    setConfirm(null);
  }

  return (
    <PageShell
      title={t('admin.roleApps.title')}
      description={t('admin.roleApps.description')}
      icon={<ClipboardCheck className="h-5 w-5" />}
      stats={[
        { label: t('admin.roleApps.stats.total'), value: String(counts.all) },
        { label: t('admin.roleApps.stats.pending'), value: String(counts.pending) },
        { label: t('admin.roleApps.stats.approved'), value: String(counts.approved) },
        { label: t('admin.roleApps.stats.rejected'), value: String(counts.rejected) },
      ]}
    >
      <AdminDataTable<RoleApplication>
        storageKey={STORAGE_KEY}
        rows={filtered}
        getRowId={(a) => a.id}
        isLoading={isLoading}
        onRowClick={(a) => setDetailTarget(a)}
        searchPlaceholder={t('adminTable.search')}
        tabs={[
          { id: 'all', label: t('common.all'), count: counts.all },
          { id: 'pending', label: t('admin.roleApps.stats.pending'), count: counts.pending },
          { id: 'approved', label: t('admin.roleApps.stats.approved'), count: counts.approved },
          { id: 'rejected', label: t('admin.roleApps.stats.rejected'), count: counts.rejected },
        ]}
        columns={[
          {
            id: 'company',
            header: t('admin.roleApps.table.company'),
            cell: (a) => (
              <div>
                <div className="font-medium">{a.company_name}</div>
                <div className="text-[11px] text-muted-foreground font-mono">{a.company_inn}</div>
              </div>
            ),
            alwaysVisible: true,
          },
          {
            id: 'requestedType',
            header: t('admin.roleApps.table.requestedType'),
            cell: (a) => <Badge variant="outline">{a.requested_type_name}</Badge>,
          },
          {
            id: 'status',
            header: t('admin.roleApps.table.status'),
            cell: (a) => <Badge variant={statusVariant(a.status)}>{a.status_display}</Badge>,
          },
          {
            id: 'submittedBy',
            header: t('admin.roleApps.table.submittedBy'),
            cell: (a) => (
              <span className="text-muted-foreground">{a.submitted_by_email || '—'}</span>
            ),
          },
          {
            id: 'date',
            header: t('admin.roleApps.table.date'),
            cell: (a) => (
              <span className="text-muted-foreground">
                {a.created_at ? new Date(a.created_at).toLocaleDateString() : '—'}
              </span>
            ),
          },
        ]}
        rowActions={[
          {
            id: 'approve',
            label: t('admin.roleApps.approve'),
            icon: <Check className="h-3.5 w-3.5 text-success" />,
            onRun: (a) => {
              if (!isPending(a.status)) {
                toast.error(t('admin.roleApps.notPending'));
                return;
              }
              setConfirm({ kind: 'approve', app: a });
            },
          },
          {
            id: 'reject',
            label: t('admin.roleApps.reject'),
            icon: <X className="h-3.5 w-3.5 text-destructive" />,
            variant: 'destructive',
            onRun: (a) => {
              if (!isPending(a.status)) {
                toast.error(t('admin.roleApps.notPending'));
                return;
              }
              setConfirm({ kind: 'reject', app: a });
            },
          },
        ]}
        emptyIcon={<ClipboardCheck className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('pages.common.noData')}
      />

      <ConfirmActionDialog
        open={confirm?.kind === 'approve'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('admin.roleApps.confirmApproveTitle')}
        description={
          confirm?.kind === 'approve'
            ? t('admin.roleApps.confirmApproveDescription', {
                company: confirm.app.company_name,
                role: confirm.app.requested_type_name,
              })
            : ''
        }
        diff={
          confirm?.kind === 'approve'
            ? [
                { label: t('admin.roleApps.detail.currentStatus'), before: confirm.app.status, after: 'APPROVED' },
                { label: t('admin.roleApps.detail.requestedRole'), after: confirm.app.requested_type_name },
              ]
            : undefined
        }
        confirmLabel={t('common.approve')}
        variant="primary"
        onConfirm={() =>
          confirm?.kind === 'approve' ? runApprove(confirm.app) : Promise.resolve()
        }
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'reject'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('admin.roleApps.rejectDialog.title')}
        description={
          confirm?.kind === 'reject'
            ? t('admin.roleApps.rejectDialog.description', { company: confirm.app.company_name })
            : ''
        }
        requireReason
        reasonLabel={t('admin.roleApps.rejectDialog.reason')}
        reasonTemplates={[
          t('admin.roleApps.rejectTemplates.docsInvalid'),
          t('admin.roleApps.rejectTemplates.outOfScope'),
          t('admin.roleApps.rejectTemplates.other'),
        ]}
        confirmLabel={t('admin.roleApps.rejectDialog.confirm')}
        variant="destructive"
        onConfirm={(p) =>
          confirm?.kind === 'reject' ? runReject(confirm.app, p.reason) : Promise.resolve()
        }
      />

      <Separator />
      <DetailSheet
        app={detailTarget}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default AdminRoleApplicationsPage;
