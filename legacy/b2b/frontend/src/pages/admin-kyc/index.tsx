import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { formatDate } from '@/lib/formatLocale';
import { ShieldCheck, XCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useCompanies, useVerifyCompany } from '@/hooks/useAccounts';
import { useBulkVerifyKYC } from '@/hooks/useAdmin';
import { AdminDataTable } from '@/components/Admin/AdminDataTable';
import { useAdminTableQueryState } from '@/components/Admin/useAdminTableQueryState';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { PageShell, ErrorState } from '../shared/PageShell';
import type { Company } from '@/api/accountsApi';
import { STORAGE_KEY, STATUS_BADGE_MAP, getStatusCode } from './constants';
import { DetailSheet } from './DetailSheet';

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

  // `fetchAll` обязателен обоим запросам. Без него оба брали ПЕРВУЮ страницу (20 записей из
  // 42 на дев-стенде): реестр молча обрезался, а счётчики вкладок — «Всего», «На проверке»,
  // «Верифицированы» — считались по этим же 20 и показывали неправду. Соседние реестры
  // (AdminCompaniesPage, admin-users) давно ходят с `fetchAll`, здесь флаг просто забыли.
  const { data: allCompanies = [] } = useCompanies({ fetchAll: true });
  const { data: companies = [], isLoading, isError, refetch } = useCompanies({ ...(queryParams ?? {}), fetchAll: true });
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
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
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
              const badgeConfig = STATUS_BADGE_MAP[code] || STATUS_BADGE_MAP.L1_UNVERIFIED;
              return <Badge variant={badgeConfig.variant}>{t(badgeConfig.label)}</Badge>;
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
                  {formatDate(c.created_at)}
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
      )}

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
        translateError={(code) => translateApiError(code)}
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
        translateError={(code) => translateApiError(code)}
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
        translateError={(code) => translateApiError(code)}
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
