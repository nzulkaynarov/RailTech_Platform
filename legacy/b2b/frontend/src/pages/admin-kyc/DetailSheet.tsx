import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { downloadFile } from '@/lib/download';
import { formatDate } from '@/lib/formatLocale';
import { translateApiError } from '@/lib/apiError';
import {
  ShieldCheck, FileText, Upload, Download, Trash2,
  BadgeCheck, XCircle, FileQuestion,
  Users as UsersIcon, Calendar as CalendarIcon, CheckCircle2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useVerifyCompany, useUploadDocument, useDeleteDocument } from '@/hooks/useAccounts';
import { AdminDetailLayout } from '@/components/Admin/AdminDetailLayout';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import { kycDocTypeLabelKey } from '@/lib/codes';
import type { Company } from '@/api/accountsApi';
import { STATUS_BADGE_MAP, DOC_TYPE_OPTIONS, getStatusCode, type KYCCode } from './constants';

// ───────────────────────────────────────────────────────────────────────
// Detail sheet (uses AdminDetailLayout internally)
// ───────────────────────────────────────────────────────────────────────

export function DetailSheet({
  company,
  open,
  onOpenChange,
}: {
  company: Company | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  // `doc_type_display` is the Russian-only lookup name — fallback for an unknown code
  // (operators can add KYCDocType rows via Unfold).
  const docTypeLabel = (code?: string | null, fallback?: string | null): string => {
    const key = kycDocTypeLabelKey(code);
    return key ? t(key) : fallback || '';
  };
  const verifyMutation = useVerifyCompany();
  const uploadMutation = useUploadDocument();
  const deleteMutation = useDeleteDocument();
  const [selectedDocType, setSelectedDocType] = useState('CHARTER');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [confirmAction, setConfirmAction] = useState<null | 'approve-l2' | 'upgrade-l3' | 'revoke-l1'>(null);
  // UX-01: deleting a KYC document is irreversible (compliance evidence) — gate it behind
  // the same ConfirmActionDialog every other destructive action here already uses.
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState<number | null>(null);

  if (!company) return null;

  const statusCode = getStatusCode(company) as KYCCode;
  const badge = STATUS_BADGE_MAP[statusCode] || STATUS_BADGE_MAP.L1_UNVERIFIED;

  // F4: verifying KYC without evidence (no uploaded documents / no INN) stays ALLOWED
  // (owner policy 2026-06-03) but must be a conscious, JUSTIFIED exception — the L2 dialog
  // turns into a warning and requires a reason, so the audit trail records WHY a company
  // was trusted without checked evidence instead of it being a silent one-click approval.
  const docCount = company.kyc_documents?.length || 0;
  const hasInn = !!(company.inn && String(company.inn).trim());
  const evidenceGaps = [
    ...(docCount === 0 ? [t('kycManager.gapNoDocs')] : []),
    ...(!hasInn ? [t('kycManager.gapNoInn')] : []),
  ];
  const missingEvidence = evidenceGaps.length > 0;

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
                  {docTypeLabel(doc.doc_type_code, doc.doc_type_display)}
                  {doc.uploaded_at ? ` · ${formatDate(doc.uploaded_at)}` : ''}
                </div>
              </div>
              {doc.file ? (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  aria-label={t('fileUpload.download')}
                  onClick={async () => {
                    try {
                      await downloadFile(
                        `accounts/companies/${company.id}/download-document/${doc.id}/`,
                        doc.original_filename || `document_${doc.id}`,
                      );
                    } catch {
                      toast.error(t('fileUpload.errors.removeFailed'));
                    }
                  }}
                >
                  <Download className="h-3.5 w-3.5" />
                </Button>
              ) : null}
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive"
                disabled={deleteMutation.isPending}
                onClick={() => setConfirmDeleteDoc(doc.id)}
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
          description={
            missingEvidence ? (
              <>
                {t('adminQueue.confirm.kycApproveDescription', { name: company.name })}
                <span className="mt-2 block font-medium text-warning">
                  {t('kycManager.approveWithoutEvidence', { gaps: evidenceGaps.join(', ') })}
                </span>
              </>
            ) : (
              t('adminQueue.confirm.kycApproveDescription', { name: company.name })
            )
          }
          diff={[{ label: t('confirmDialog.kycLevel'), before: statusCode, after: 'L2_VERIFIED' }]}
          showReason
          requireReason={missingEvidence}
          reasonLabel={missingEvidence ? t('kycManager.approveReasonRequired') : t('adminQueue.confirm.commentOptional')}
          confirmLabel={t('common.approve')}
          variant={missingEvidence ? 'warning' : 'primary'}
          onConfirm={(p) => runVerify('L2_VERIFIED', p.reason)}
          translateError={(code) => translateApiError(code)}
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
          translateError={(code) => translateApiError(code)}
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
          translateError={(code) => translateApiError(code)}
        />
        <ConfirmActionDialog
          open={confirmDeleteDoc !== null}
          onOpenChange={(v) => !v && setConfirmDeleteDoc(null)}
          title={t('kycManager.confirmDeleteDocTitle')}
          description={t('kycManager.confirmDeleteDocDesc')}
          confirmLabel={t('common.delete')}
          variant="destructive"
          onConfirm={async () => {
            if (confirmDeleteDoc !== null) await handleDeleteDoc(confirmDeleteDoc);
          }}
        />
      </SheetContent>
    </Sheet>
  );
}
