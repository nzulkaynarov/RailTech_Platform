import { useState, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ShieldCheck, Search, FileText, Upload, Download, Trash2,
  BadgeCheck, XCircle, FileQuestion, Eye,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter,
} from '@/components/ui/sheet';
import { useCompanies, useVerifyCompany, useUploadDocument, useDeleteDocument } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { Company } from '@/api/accountsApi';

/* ─── Helpers ──────────────────────────────────────────────────────── */

type FilterStatus = 'all' | 'L1_UNVERIFIED' | 'PROFILE_SUBMITTED' | 'L2_VERIFIED' | 'L3_CONTRACTED';

function getStatusCode(company: Company): string {
  return (company.verification_status_code || String(company.verification_status)) as string;
}

const STATUS_BADGE_MAP: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  L1_UNVERIFIED: { variant: 'secondary', label: 'kycManager.status.P_PENDING' },
  PROFILE_SUBMITTED: { variant: 'outline', label: 'kycManager.status.P_SUBMITTED' },
  L2_VERIFIED: { variant: 'default', label: 'kycManager.status.V_VERIFIED_L2' },
  L3_CONTRACTED: { variant: 'default', label: 'kycManager.status.V_PARTNER_L3' },
};

const STATUS_FILTER_OPTIONS: FilterStatus[] = ['L1_UNVERIFIED', 'PROFILE_SUBMITTED', 'L2_VERIFIED', 'L3_CONTRACTED'];

const DOC_TYPE_OPTIONS = [
  { value: 'CHARTER', labelKey: 'kycManager.docTypes.charter' },
  { value: 'LICENSE', labelKey: 'kycManager.docTypes.license' },
  { value: 'PASSPORT', labelKey: 'kycManager.docTypes.passport' },
  { value: 'TAX_CERT', labelKey: 'kycManager.docTypes.taxCert' },
  { value: 'OTHER', labelKey: 'kycManager.docTypes.other' },
];

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

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
  const [comment, setComment] = useState('');
  const [selectedDocType, setSelectedDocType] = useState('CHARTER');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const verifyMutation = useVerifyCompany();
  const uploadMutation = useUploadDocument();
  const deleteMutation = useDeleteDocument();

  if (!company) return null;

  const statusCode = getStatusCode(company);
  const badge = STATUS_BADGE_MAP[statusCode] || STATUS_BADGE_MAP.L1_UNVERIFIED;
  const busy = verifyMutation.isPending || uploadMutation.isPending;

  const handleVerify = async (targetStatus: string) => {
    try {
      await verifyMutation.mutateAsync({ id: company.id, statusCode: targetStatus, comment: comment.trim() || undefined });
      toast.success(t('kycManager.verified'));
      onOpenChange(false);
      setComment('');
    } catch {
      toast.error(t('kycManager.operationFailure'));
    }
  };

  const handleUpload = async (file: File) => {
    try {
      await uploadMutation.mutateAsync({ companyId: company.id, file, docType: selectedDocType });
      toast.success(t('kycManager.importDoc'));
    } catch {
      toast.error(t('kycManager.uploadFailure'));
    }
  };

  const handleDeleteDoc = async (docId: number) => {
    try {
      await deleteMutation.mutateAsync({ companyId: company.id, docId });
      toast.success(t('fileUpload.removed'));
    } catch {
      toast.error(t('fileUpload.errors.removeFailed'));
    }
  };

  const infoRows = [
    { label: t('kycManager.registryFields.taxId'), value: company.inn },
    { label: t('kycManager.registryFields.mfoCode'), value: company.mfo || '—' },
    { label: t('kycManager.registryFields.bankAcc'), value: company.bank_account || '—' },
    { label: t('kycManager.registryFields.opContact'), value: company.contact_person || '—' },
  ];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{company.name}</SheetTitle>
        </SheetHeader>

        <div className="mt-2 space-y-6 px-4">
          {/* Status */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('kycManager.authStatus')}</h3>
            <Badge variant={badge.variant}>{t(badge.label)}</Badge>
          </section>

          <Separator />

          {/* Company Info */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('kycManager.registryData')}</h3>
            {infoRows.map((r) => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{r.label}</span>
                <span className="text-sm tabular-nums">{r.value}</span>
              </div>
            ))}
            {company.legal_address && (
              <div className="rounded-lg border bg-muted/50 p-3">
                <p className="text-xs text-muted-foreground mb-1">{t('kycManager.physicalAddress')}</p>
                <p className="text-sm">{company.legal_address}</p>
              </div>
            )}
          </section>

          <Separator />

          {/* Documents */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t('kycManager.docRecords')}
              <span className="text-xs text-muted-foreground ml-auto">
                {t('kycManager.docCount', { count: company.kyc_documents?.length || 0 })}
              </span>
            </h3>
            {(company.kyc_documents || []).length > 0 ? (
              <div className="space-y-2">
                {company.kyc_documents!.map((doc) => (
                  <div key={doc.id} className="flex items-center gap-2 rounded-lg border p-2">
                    <FileText className="h-3.5 w-3.5 text-primary shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm truncate">{doc.original_filename}</p>
                      <p className="text-xs text-muted-foreground">
                        {doc.doc_type_display}
                        {doc.uploaded_at ? ` · ${new Date(doc.uploaded_at).toLocaleDateString()}` : ''}
                      </p>
                    </div>
                    {doc.file && (
                      <Button
                        asChild
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t('fileUpload.download')}
                      >
                        <a href={doc.file} target="_blank" rel="noreferrer">
                          <Download className="h-3.5 w-3.5" />
                        </a>
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t('fileUpload.remove')}
                      disabled={deleteMutation.isPending}
                      onClick={() => handleDeleteDoc(doc.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-6 text-muted-foreground">
                <FileQuestion className="h-6 w-6 mb-1.5" />
                <p className="text-sm">{t('kycManager.noDocuments')}</p>
              </div>
            )}

            {/* Upload */}
            <div className="flex items-center gap-2">
              <Select value={selectedDocType} onValueChange={setSelectedDocType}>
                <SelectTrigger className="flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DOC_TYPE_OPTIONS.map((dt) => (
                    <SelectItem key={dt.value} value={dt.value}>{t(dt.labelKey)}</SelectItem>
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
                onClick={() => fileInputRef.current?.click()}
                disabled={busy}
                className="gap-2"
              >
                <Upload className="h-3.5 w-3.5" />
                {t('kycManager.importDoc')}
              </Button>
            </div>
          </section>

          <Separator />

          {/* Notes */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('kycManager.observations')}</h3>
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={t('kycManager.observationsPlaceholder')}
              rows={3}
            />
          </section>
        </div>

        <SheetFooter className="mt-6 flex flex-col gap-2 sm:flex-col">
          {(statusCode === 'L1_UNVERIFIED' || statusCode === 'PROFILE_SUBMITTED') && (
            <Button
              onClick={() => handleVerify('L2_VERIFIED')}
              disabled={busy}
              className="w-full gap-2"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              {t('kycManager.approveL2')}
            </Button>
          )}
          {statusCode === 'L2_VERIFIED' && (
            <Button
              onClick={() => handleVerify('L3_CONTRACTED')}
              disabled={busy}
              className="w-full gap-2"
            >
              <BadgeCheck className="h-3.5 w-3.5" />
              {t('kycManager.upgradeL3')}
            </Button>
          )}
          {statusCode !== 'L1_UNVERIFIED' && (
            <Button
              variant="destructive"
              onClick={() => handleVerify('L1_UNVERIFIED')}
              disabled={busy}
              className="w-full gap-2"
            >
              <XCircle className="h-3.5 w-3.5" />
              {t('kycManager.revokeL1')}
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function AdminKYCPage() {
  const { t } = useTranslation();
  const { data: companies, isLoading } = useCompanies();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<FilterStatus>('all');
  const [detailTarget, setDetailTarget] = useState<Company | null>(null);

  // Keep selected company fresh after refetch
  const selectedCompany = useMemo(() => {
    if (!detailTarget || !companies) return null;
    return companies.find((c) => c.id === detailTarget.id) ?? detailTarget;
  }, [companies, detailTarget]);

  const filtered = useMemo(() => {
    if (!companies) return [];
    return companies.filter((c) => {
      const matchesSearch = !search ||
        c.name.toLowerCase().includes(search.toLowerCase()) ||
        c.inn.includes(search);
      const matchesStatus = statusFilter === 'all' || getStatusCode(c) === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [companies, search, statusFilter]);

  const stats = [
    { label: t('kycManager.stats.total'), value: String(companies?.length ?? '—') },
    { label: t('kycManager.stats.pending'), value: String(companies?.filter((c) => getStatusCode(c) === 'L1_UNVERIFIED' || getStatusCode(c) === 'PROFILE_SUBMITTED').length ?? '—') },
    { label: t('kycManager.stats.verified'), value: String(companies?.filter((c) => getStatusCode(c) === 'L2_VERIFIED').length ?? '—') },
    { label: t('kycManager.stats.partner'), value: String(companies?.filter((c) => getStatusCode(c) === 'L3_CONTRACTED').length ?? '—') },
  ];

  return (
    <PageShell
      title={t('kycManager.title') + ' ' + t('kycManager.titleHighlight')}
      description={t('kycManager.description')}
      icon={<ShieldCheck className="h-5 w-5" />}
      stats={stats}
    >
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t('kycManager.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as FilterStatus)}>
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('kycManager.allStatuses')}</SelectItem>
            {STATUS_FILTER_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>{t(STATUS_BADGE_MAP[s].label)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !filtered.length ? (
            <EmptyState icon={<ShieldCheck className="h-5 w-5" />} message={t('kycManager.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('kycManager.table.company')}</TableHead>
                  <TableHead>{t('kycManager.table.inn')}</TableHead>
                  <TableHead>{t('kycManager.table.status')}</TableHead>
                  <TableHead>{t('kycManager.table.docs')}</TableHead>
                  <TableHead>{t('kycManager.table.date')}</TableHead>
                  <TableHead className="text-center">{t('kycManager.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((company) => {
                  const code = getStatusCode(company);
                  const badge = STATUS_BADGE_MAP[code] || STATUS_BADGE_MAP.L1_UNVERIFIED;
                  return (
                    <TableRow
                      key={company.id}
                      className="cursor-pointer"
                      onClick={() => setDetailTarget(company)}
                    >
                      <TableCell>
                        <span className="font-medium">{company.name}</span>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {company.inn}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{t(badge.label)}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {company.kyc_documents?.length || 0}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {company.created_at ? new Date(company.created_at).toLocaleDateString() : '—'}
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDetailTarget(company)}
                            title={t('kycManager.entityReview')}
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DetailSheet
        company={selectedCompany}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default AdminKYCPage;
