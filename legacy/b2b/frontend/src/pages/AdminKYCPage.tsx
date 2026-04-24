import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ShieldCheck, FileText, Upload, Download, Trash2,
  BadgeCheck, XCircle, FileQuestion,
  Users as UsersIcon, Calendar as CalendarIcon, CheckCircle2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useCompanies, useVerifyCompany, useUploadDocument, useDeleteDocument } from '@/hooks/useAccounts';
import { useBulkVerifyKYC } from '@/hooks/useAdmin';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import { AdminDetailLayout } from '@/components/Admin/AdminDetailLayout';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import { PageShell } from './shared/PageShell';
import type { Company } from '@/api/accountsApi';

type KYCCode = 'L1_UNVERIFIED' | 'PROFILE_SUBMITTED' | 'L2_VERIFIED' | 'L3_CONTRACTED';

const STORAGE_KEY = 'adminKyc';

const STATUS_BADGE_MAP: Record<
  string,
  { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }
> = {
  L1_UNVERIFIED: { variant: 'secondary', label: 'kycManager.status.P_PENDING' },
  PROFILE_SUBMITTED: { variant: 'outline', label: 'kycManager.status.P_SUBMITTED' },
  L2_VERIFIED: { variant: 'default', label: 'kycManager.status.V_VERIFIED_L2' },
  L3_CONTRACTED: { variant: 'default', label: 'kycManager.status.V_PARTNER_L3' },
};

const DOC_TYPE_OPTIONS = [
  { value: 'CHARTER', labelKey: 'kycManager.docTypes.charter' },
  { value: 'LICENSE', labelKey: 'kycManager.docTypes.license' },
  { value: 'PASSPORT', labelKey: 'kycManager.docTypes.passport' },
  { value: 'TAX_CERT', labelKey: 'kycManager.docTypes.taxCert' },
  { value: 'OTHER', labelKey: 'kycManager.docTypes.other' },
];

function getStatusCode(company: Company): string {
  return (company.verification_status_code || String(company.verification_status)) as string;
}

// ───────────────────────────────────────────────────────────────────────
// Detail sheet (uses AdminDetailLayout internally)
// ───────────────────────────────────────────────────────────────────────

function DetailSheet({
  company,
  open,
  onOpenChange,
}: {
  company: Company | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const verifyMutation = useVerifyCompany();
  const uploadMutation = useUploadDocument();
  const deleteMutation = useDeleteDocument();
  const [selectedDocType, setSelectedDocType] = useState('CHARTER');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [confirmAction, setConfirmAction] = useState<null | 'approve-l2' | 'upgrade-l3' | 'revoke-l1'>(null);

  if (!company) return null;

  const statusCode = getStatusCode(company) as KYCCode;
  const badge = STATUS_BADGE_MAP[statusCode] || STATUS_BADGE_MAP.L1_UNVERIFIED;

  async function runVerify(target: string, reason: string) {
    if (!company) return;
    await verifyMutation.mutateAsync({
      companyId: company.id,
      status_code: target,
      reason: reason || undefined,
    });
    toast.success(t('kycManager.verified'));
    setConfirmAction(null);
  }

  async function handleUpload(file: File) {
    if (!company) return;
    try {
      await uploadMutation.mutateAsync({ companyId: company.id, file, docType: selectedDocType });
      toast.success(t('kycManager.importDoc'));
    } catch {
      toast.error(t('kycManager.uploadFailure'));
    }
  }

  async function handleDeleteDoc(docId: number) {
    if (!company) return;
    try {
      await deleteMutation.mutateAsync({ companyId: company.id, docId });
      toast.success(t('fileUpload.removed'));
    } catch {
      toast.error(t('fileUpload.errors.removeFailed'));
    }
  }

  const createdDate = company.created_at ? new Date(company.created_at) : null;
  const ageDays = createdDate
    ? Math.max(0, Math.floor((Date.now() - createdDate.getTime()) / 86_400_000))
    : null;

  const overview = (
    <div className="space-y-4">
      <DetailKPIGrid
        columns={4}
        items={[
          {
            label: t('kycManager.stats.verified'),
            value: t(STATUS_BADGE_MAP[statusCode]?.label || 'kycManager.status.P_PENDING'),
            icon: <CheckCircle2 className="h-3.5 w-3.5" />,
            tone:
              statusCode === 'L2_VERIFIED' || statusCode === 'L3_CONTRACTED'
                ? 'success'
                : statusCode === 'PROFILE_SUBMITTED'
                  ? 'warning'
                  : 'default',
          },
          {
            label: t('kycManager.docRecords'),
            value: String(company.kyc_documents?.length || 0),
            icon: <FileText className="h-3.5 w-3.5" />,
          },
          {
            label: t('kycManager.registryFields.mfoCode'),
            value: company.mfo || '—',
            icon: <UsersIcon className="h-3.5 w-3.5" />,
          },
          {
            label: t('kycManager.accountAge'),
            value: ageDays != null ? t('kycManager.ageDays', { count: ageDays }) : '—',
            icon: <CalendarIcon className="h-3.5 w-3.5" />,
            hint: createdDate ? createdDate.toLocaleDateString() : undefined,
          },
        ]}
      />
      <dl className="grid grid-cols-1 gap-2 rounded-md border p-3 text-xs sm:grid-cols-2">
        {[
          { label: t('kycManager.registryFields.taxId'), value: company.inn },
          { label: t('kycManager.registryFields.mfoCode'), value: company.mfo || '—' },
          { label: t('kycManager.registryFields.bankAcc'), value: company.bank_account || '—' },
          { label: t('kycManager.registryFields.opContact'), value: company.contact_person || '—' },
          { label: t('kycManager.registryFields.email') ?? 'Email', value: company.email || '—' },
          { label: t('kycManager.registryFields.website') ?? 'Website', value: company.website || '—' },
        ].map((r) => (
          <div key={r.label} className="flex items-start justify-between gap-2">
            <dt className="text-muted-foreground">{r.label}</dt>
            <dd className="truncate text-right font-medium tabular-nums">{r.value}</dd>
          </div>
        ))}
      </dl>
      {company.legal_address ? (
        <div className="rounded-md border p-3 text-xs">
          <div className="mb-1 text-muted-foreground">{t('kycManager.physicalAddress')}</div>
          <div>{company.legal_address}</div>
        </div>
      ) : null}
    </div>
  );

  const documents = (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold">
          {t('kycManager.docRecords')}
          <span className="ml-1 text-muted-foreground">
            ({company.kyc_documents?.length || 0})
          </span>
        </h3>
      </div>
      {(company.kyc_documents || []).length > 0 ? (
        <div className="space-y-2">
          {company.kyc_documents!.map((doc) => (
            <div key={doc.id} className="flex items-center gap-2 rounded-md border p-2 text-xs">
              <FileText className="h-3.5 w-3.5 text-primary shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{doc.original_filename}</div>
                <div className="text-muted-foreground">
                  {doc.doc_type_display}
                  {doc.uploaded_at ? ` · ${new Date(doc.uploaded_at).toLocaleDateString()}` : ''}
                </div>
              </div>
              {doc.file ? (
                <Button asChild size="icon" variant="ghost" className="h-7 w-7" aria-label={t('fileUpload.download')}>
                  <a href={doc.file} target="_blank" rel="noreferrer">
                    <Download className="h-3.5 w-3.5" />
                  </a>
                </Button>
              ) : null}
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive"
                disabled={deleteMutation.isPending}
                onClick={() => handleDeleteDoc(doc.id)}
                aria-label={t('fileUpload.remove')}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-6 text-xs text-muted-foreground">
          <FileQuestion className="mb-1.5 h-5 w-5" />
          {t('kycManager.noDocuments')}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Select value={selectedDocType} onValueChange={setSelectedDocType}>
          <SelectTrigger className="h-8 flex-1 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DOC_TYPE_OPTIONS.map((dt) => (
              <SelectItem key={dt.value} value={dt.value} className="text-xs">
                {t(dt.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.doc,.docx,.jpg,.png"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
            e.target.value = '';
          }}
        />
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 text-xs"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMutation.isPending}
        >
          <Upload className="h-3.5 w-3.5" />
          {t('kycManager.importDoc')}
        </Button>
      </div>
    </div>
  );

  const dangerZone = (
    <div className="space-y-3 rounded-md border border-destructive/40 p-3">
      <h3 className="text-xs font-semibold text-destructive">
        {t('adminDetail.dangerZone')}
      </h3>
      <p className="text-xs text-muted-foreground">
        {t('kycManager.revokeHint')}
      </p>
      <Button
        size="sm"
        variant="destructive"
        className="h-8 gap-1.5 text-xs"
        disabled={statusCode === 'L1_UNVERIFIED'}
        onClick={() => setConfirmAction('revoke-l1')}
      >
        <XCircle className="h-3.5 w-3.5" />
        {t('kycManager.revokeL1')}
      </Button>
    </div>
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto p-0 sm:max-w-2xl">
        <SheetHeader className="sr-only">
          <SheetTitle>{company.name}</SheetTitle>
        </SheetHeader>
        <div className="p-4 md:p-5">
          <AdminDetailLayout
            title={company.name}
            subtitle={company.inn ? `INN ${company.inn}` : undefined}
            leading={
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                <ShieldCheck className="h-5 w-5" />
              </div>
            }
            badges={[{ label: t(badge.label), variant: badge.variant }]}
            actions={
              <>
                {(statusCode === 'L1_UNVERIFIED' || statusCode === 'PROFILE_SUBMITTED') ? (
                  <Button
                    size="sm"
                    className="h-8 gap-1.5 text-xs"
                    onClick={() => setConfirmAction('approve-l2')}
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    {t('kycManager.approveL2')}
                  </Button>
                ) : null}
                {statusCode === 'L2_VERIFIED' ? (
                  <Button
                    size="sm"
                    className="h-8 gap-1.5 text-xs"
                    onClick={() => setConfirmAction('upgrade-l3')}
                  >
                    <BadgeCheck className="h-3.5 w-3.5" />
                    {t('kycManager.upgradeL3')}
                  </Button>
                ) : null}
              </>
            }
            tabs={[
              { id: 'overview', label: t('kycManager.registryData'), content: overview },
              { id: 'documents', label: t('kycManager.docRecords'), content: documents },
              {
                id: 'timeline',
                label: t('platformAdmin.activity.title'),
                content: <AdminActivityTimeline entityType="company" entityId={company.id} />,
              },
            ]}
            dangerZone={dangerZone}
          />
        </div>

        <ConfirmActionDialog
          open={confirmAction === 'approve-l2'}
          onOpenChange={(v) => !v && setConfirmAction(null)}
          title={t('adminQueue.confirm.kycApproveTitle')}
          description={t('adminQueue.confirm.kycApproveDescription', { name: company.name })}
          diff={[{ label: t('confirmDialog.kycLevel'), before: statusCode, after: 'L2_VERIFIED' }]}
          showReason
          reasonLabel={t('adminQueue.confirm.commentOptional')}
          confirmLabel={t('common.approve')}
          variant="primary"
          onConfirm={(p) => runVerify('L2_VERIFIED', p.reason)}
        />
        <ConfirmActionDialog
          open={confirmAction === 'upgrade-l3'}
          onOpenChange={(v) => !v && setConfirmAction(null)}
          title={t('kycManager.upgradeL3')}
          description={company.name}
          diff={[{ label: t('confirmDialog.kycLevel'), before: 'L2_VERIFIED', after: 'L3_CONTRACTED' }]}
          showReason
          reasonLabel={t('adminQueue.confirm.commentOptional')}
          confirmLabel={t('common.confirm')}
          variant="primary"
          onConfirm={(p) => runVerify('L3_CONTRACTED', p.reason)}
        />
        <ConfirmActionDialog
          open={confirmAction === 'revoke-l1'}
          onOpenChange={(v) => !v && setConfirmAction(null)}
          title={t('adminQueue.confirm.kycRevokeTitle')}
          description={t('adminQueue.confirm.kycRevokeDescription', { name: company.name })}
          diff={[{ label: t('confirmDialog.kycLevel'), before: statusCode, after: 'L1_UNVERIFIED' }]}
          requireReason
          reasonTemplates={[
            t('adminQueue.reasonTemplates.docsInvalid'),
            t('adminQueue.reasonTemplates.innMismatch'),
            t('adminQueue.reasonTemplates.other'),
          ]}
          confirmLabel={t('common.revoke')}
          variant="destructive"
          onConfirm={(p) => runVerify('L1_UNVERIFIED', p.reason)}
        />
      </SheetContent>
    </Sheet>
  );
}

// ───────────────────────────────────────────────────────────────────────
// List page
// ───────────────────────────────────────────────────────────────────────

export function AdminKYCPage() {
  const { t } = useTranslation();
  const verifyMutation = useVerifyCompany();
  const bulkVerify = useBulkVerifyKYC();

  const [detailTarget, setDetailTarget] = useState<Company | null>(null);
  const [confirmRow, setConfirmRow] = useState<null | {
    kind: 'approve-l2' | 'revoke-l1';
    company: Company;
  }>(null);
  const [confirmBulk, setConfirmBulk] = useState<null | { companies: Company[] }>(null);

  const tableState = useAdminTableQueryState(STORAGE_KEY);
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (tableState.search) p.search = tableState.search;
    const tab = tableState.tab || 'all';
    if (tab !== 'all') p.verification_status__code = tab;
    return Object.keys(p).length ? p : undefined;
  }, [tableState.search, tableState.tab]);

  // All-companies query for accurate tab counts
  const { data: allCompanies = [] } = useCompanies();
  const { data: companies = [], isLoading } = useCompanies(queryParams);
  const kept = companies;

  const selectedCompany = useMemo(() => {
    if (!detailTarget) return null;
    return (allCompanies.find((c) => c.id === detailTarget.id) ?? detailTarget);
  }, [allCompanies, detailTarget]);

  const counts = useMemo(() => {
    const buckets: Record<string, number> = {
      all: allCompanies.length,
      L1_UNVERIFIED: 0,
      PROFILE_SUBMITTED: 0,
      L2_VERIFIED: 0,
      L3_CONTRACTED: 0,
    };
    allCompanies.forEach((c) => {
      const code = getStatusCode(c);
      if (code in buckets) buckets[code] += 1;
    });
    return buckets;
  }, [allCompanies]);

  async function runRowApprove(company: Company, reason: string) {
    await verifyMutation.mutateAsync({
      companyId: company.id,
      status_code: 'L2_VERIFIED',
      reason: reason || undefined,
    });
    toast.success(t('kycManager.verified'));
    setConfirmRow(null);
  }

  async function runRowRevoke(company: Company, reason: string) {
    await verifyMutation.mutateAsync({
      companyId: company.id,
      status_code: 'L1_UNVERIFIED',
      reason,
    });
    toast.success(t('adminQueue.kycRevoked'));
    setConfirmRow(null);
  }

  async function runBulkApprove(rows: Company[], reason: string) {
    const res = await bulkVerify.mutateAsync({
      ids: rows.map((r) => r.id),
      level: 'L2_VERIFIED',
      reason: reason || undefined,
    });
    toast.success(
      t('kycManager.bulkApprovedResult', {
        approved: res.approved,
        skipped: res.skipped.length,
      }),
    );
    if (res.skipped.length) {
      toast.warning(res.skipped.map((s) => `${s.name}: ${s.error}`).join('; '));
    }
    setConfirmBulk(null);
  }

  return (
    <PageShell
      title={t('kycManager.title')}
      description={t('kycManager.description')}
      icon={<ShieldCheck className="h-5 w-5" />}
      stats={[
        { label: t('kycManager.stats.total'), value: String(counts.all) },
        {
          label: t('kycManager.stats.pending'),
          value: String(counts.L1_UNVERIFIED + counts.PROFILE_SUBMITTED),
        },
        { label: t('kycManager.stats.verified'), value: String(counts.L2_VERIFIED) },
        { label: t('kycManager.stats.partner'), value: String(counts.L3_CONTRACTED) },
      ]}
    >
      <AdminDataTable<Company>
        storageKey={STORAGE_KEY}
        rows={kept}
        getRowId={(c) => c.id}
        isLoading={isLoading}
        onRowClick={(c) => setDetailTarget(c)}
        searchPlaceholder={t('kycManager.searchPlaceholder')}
        exportUrl={`${window.location.origin}/api/v1/accounts/companies/export/`}
        tabs={[
          { id: 'all', label: t('kycManager.allStatuses'), count: counts.all },
          { id: 'PROFILE_SUBMITTED', label: t('kycManager.status.P_SUBMITTED'), count: counts.PROFILE_SUBMITTED },
          { id: 'L1_UNVERIFIED', label: t('kycManager.status.P_PENDING'), count: counts.L1_UNVERIFIED },
          { id: 'L2_VERIFIED', label: t('kycManager.status.V_VERIFIED_L2'), count: counts.L2_VERIFIED },
          { id: 'L3_CONTRACTED', label: t('kycManager.status.V_PARTNER_L3'), count: counts.L3_CONTRACTED },
        ]}
        columns={[
          {
            id: 'name',
            header: t('kycManager.table.company'),
            cell: (c) => <span className="font-medium">{c.name}</span>,
            alwaysVisible: true,
          },
          {
            id: 'inn',
            header: t('kycManager.table.inn'),
            cell: (c) => <span className="font-mono tabular-nums">{c.inn}</span>,
          },
          {
            id: 'status',
            header: t('kycManager.table.status'),
            cell: (c) => {
              const code = getStatusCode(c);
              const b = STATUS_BADGE_MAP[code] || STATUS_BADGE_MAP.L1_UNVERIFIED;
              return <Badge variant={b.variant}>{t(b.label)}</Badge>;
            },
          },
          {
            id: 'docs',
            header: t('kycManager.table.docs'),
            cell: (c) => (
              <span className="text-muted-foreground tabular-nums">
                {c.kyc_documents?.length || 0}
              </span>
            ),
          },
          {
            id: 'created',
            header: t('kycManager.table.date'),
            cell: (c) =>
              c.created_at ? (
                <span className="text-muted-foreground">
                  {new Date(c.created_at).toLocaleDateString()}
                </span>
              ) : (
                <span className="text-muted-foreground">—</span>
              ),
          },
        ]}
        rowActions={[
          {
            id: 'approve-l2',
            label: t('kycManager.approveL2'),
            icon: <ShieldCheck className="h-3.5 w-3.5" />,
            onRun: (c) => setConfirmRow({ kind: 'approve-l2', company: c }),
          },
          {
            id: 'revoke',
            label: t('kycManager.revokeL1'),
            icon: <XCircle className="h-3.5 w-3.5" />,
            variant: 'destructive',
            onRun: (c) => setConfirmRow({ kind: 'revoke-l1', company: c }),
          },
        ]}
        bulkActions={[
          {
            id: 'bulk-approve',
            label: t('kycManager.bulkApproveL2'),
            onRun: (rows) => {
              setConfirmBulk({ companies: rows });
            },
          },
        ]}
        emptyIcon={<ShieldCheck className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('kycManager.emptyState')}
      />

      {/* Row-level confirms */}
      <ConfirmActionDialog
        open={confirmRow?.kind === 'approve-l2'}
        onOpenChange={(v) => !v && setConfirmRow(null)}
        title={t('adminQueue.confirm.kycApproveTitle')}
        description={
          confirmRow?.kind === 'approve-l2'
            ? t('adminQueue.confirm.kycApproveDescription', { name: confirmRow.company.name })
            : ''
        }
        diff={
          confirmRow?.kind === 'approve-l2'
            ? [
                {
                  label: t('confirmDialog.kycLevel'),
                  before: getStatusCode(confirmRow.company),
                  after: 'L2_VERIFIED',
                },
              ]
            : undefined
        }
        showReason
        reasonLabel={t('adminQueue.confirm.commentOptional')}
        confirmLabel={t('common.approve')}
        variant="primary"
        onConfirm={(p) =>
          confirmRow?.kind === 'approve-l2'
            ? runRowApprove(confirmRow.company, p.reason)
            : Promise.resolve()
        }
      />
      <ConfirmActionDialog
        open={confirmRow?.kind === 'revoke-l1'}
        onOpenChange={(v) => !v && setConfirmRow(null)}
        title={t('adminQueue.confirm.kycRevokeTitle')}
        description={
          confirmRow?.kind === 'revoke-l1'
            ? t('adminQueue.confirm.kycRevokeDescription', { name: confirmRow.company.name })
            : ''
        }
        diff={
          confirmRow?.kind === 'revoke-l1'
            ? [
                {
                  label: t('confirmDialog.kycLevel'),
                  before: getStatusCode(confirmRow.company),
                  after: 'L1_UNVERIFIED',
                },
              ]
            : undefined
        }
        requireReason
        reasonTemplates={[
          t('adminQueue.reasonTemplates.docsInvalid'),
          t('adminQueue.reasonTemplates.innMismatch'),
          t('adminQueue.reasonTemplates.other'),
        ]}
        confirmLabel={t('common.revoke')}
        variant="destructive"
        onConfirm={(p) =>
          confirmRow?.kind === 'revoke-l1'
            ? runRowRevoke(confirmRow.company, p.reason)
            : Promise.resolve()
        }
      />

      {/* Bulk */}
      <ConfirmActionDialog
        open={Boolean(confirmBulk)}
        onOpenChange={(v) => !v && setConfirmBulk(null)}
        title={t('kycManager.bulkApproveL2')}
        description={
          confirmBulk
            ? t('kycManager.bulkApproveDesc', { count: confirmBulk.companies.length })
            : ''
        }
        showReason
        reasonLabel={t('adminQueue.confirm.commentOptional')}
        confirmLabel={t('common.approve')}
        variant="primary"
        onConfirm={(p) =>
          confirmBulk
            ? runBulkApprove(confirmBulk.companies, p.reason)
            : Promise.resolve()
        }
      />

      <Separator />
      <DetailSheet
        company={selectedCompany}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default AdminKYCPage;
