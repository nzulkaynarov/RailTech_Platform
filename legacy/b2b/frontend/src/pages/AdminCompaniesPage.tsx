import { useState, useMemo } from 'react';
import { useDraftState } from '@/hooks/useDraftState';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Building2, Pencil, Trash2, UserPlus, GitMerge, Archive, ArchiveRestore } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatDate } from '@/lib/formatLocale';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { AdminDataTable } from '@/components/Admin/AdminDataTable';
import { useAdminTableQueryState } from '@/components/Admin/useAdminTableQueryState';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import { translateApiError } from '@/lib/apiError';

const KYC_BADGE: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; labelKey: string }> = {
  L1_UNVERIFIED: { variant: 'secondary', labelKey: 'kycManager.status.P_PENDING' },
  PROFILE_SUBMITTED: { variant: 'outline', labelKey: 'kycManager.status.P_SUBMITTED' },
  L2_VERIFIED: { variant: 'default', labelKey: 'kycManager.status.V_VERIFIED_L2' },
  L3_CONTRACTED: { variant: 'default', labelKey: 'kycManager.status.V_PARTNER_L3' },
};

const TYPE_LABEL_KEY: Record<string, string> = {
  CLIENT: 'companyStatus.BUYER',
  SUPPLIER: 'companyStatus.SELLER',
  MANUFACTURER: 'companyStatus.MANUFACTURER',
};

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { MergeDuplicatesDialog } from '@/components/Admin/MergeDuplicatesDialog';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  useCompanies, useCreateCompany, useUpdateCompany, useDeleteCompany,
  useArchiveCompany, useUnarchiveCompany,
  useCompanyTeam, useInviteMember,
  useUploadCompanyLogo, useDeleteCompanyLogo,
  useUploadDocument, useDeleteDocument,
} from '@/hooks/useAccounts';
import { accountsApi } from '@/api/accountsApi';
import { useQuery } from '@tanstack/react-query';
import { kycDocTypeLabelKey } from '@/lib/codes';
import type { Company } from '@/api/accountsApi';
import { ImageUpload } from '@/components/Shared/ImageUpload';
import { FileUpload } from '@/components/Shared/FileUpload';

type Draft = Partial<Company>;

function emptyDraft(): Draft {
  return { name: '', inn: '' };
}

function MembersPanel({ companyId }: { companyId: number }) {
  const { t } = useTranslation();
  const { data: members, isLoading } = useCompanyTeam(companyId);
  const inviteMut = useInviteMember();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('PROCUREMENT_MANAGER');

  const handleInvite = async () => {
    if (!email.trim()) {
      toast.error(t('adminCompanies.emailRequired'));
      return;
    }
    try {
      await inviteMut.mutateAsync({ companyId, email, role });
      toast.success(t('adminCompanies.invited'));
      setEmail('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-3 rounded-lg border p-3">
        <div className="space-y-2">
          <Label>{t('adminCompanies.members.inviteEmail')}</Label>
          <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@example.com" />
        </div>
        <div className="space-y-2">
          <Label>{t('adminCompanies.members.role')}</Label>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="OWNER">{t('adminCompanies.members.roleOwner')}</SelectItem>
              <SelectItem value="PROCUREMENT_MANAGER">{t('adminCompanies.members.roleProcurement')}</SelectItem>
              <SelectItem value="MEMBER">{t('adminCompanies.members.roleMember')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button onClick={handleInvite} disabled={inviteMut.isPending} className="gap-2 w-full">
          <UserPlus className="h-3.5 w-3.5" />
          {t('adminCompanies.members.invite')}
        </Button>
      </div>

      <Separator />

      <div>
        <h4 className="text-sm font-semibold mb-2">{t('adminCompanies.members.current')}</h4>
        {isLoading ? <LoadingRows rows={3} /> : !members?.length ? (
          <EmptyState icon={<Building2 className="h-5 w-5" />} message={t('adminCompanies.members.empty')} />
        ) : (
          <div className="space-y-2">
            {members.map((m) => (
              <div key={m.id} className="flex items-center justify-between rounded-lg border p-2 text-sm">
                <div>
                  <p className="font-medium">{m.first_name} {m.last_name}</p>
                  <p className="text-xs text-muted-foreground">{m.email}</p>
                </div>
                <Badge variant="outline">{m.workspace_role ?? '—'}</Badge>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CompanyFilesPanel({ companyId }: { companyId: number }) {
  const { t } = useTranslation();
  const { data: company, refetch } = useQuery({
    queryKey: ['company-detail', companyId],
    queryFn: () => accountsApi.getCompanyDetail(companyId),
  });
  const uploadLogo = useUploadCompanyLogo();
  const deleteLogo = useDeleteCompanyLogo();
  const uploadDoc = useUploadDocument();
  const deleteDoc = useDeleteDocument();

  const handleLogoUpload = async (file: File) => {
    await uploadLogo.mutateAsync({ companyId, file });
    await refetch();
  };
  const handleLogoRemove = async () => {
    await deleteLogo.mutateAsync(companyId);
    await refetch();
  };
  const handleDocUpload = async (file: File) => {
    await uploadDoc.mutateAsync({ companyId, file, docType: 'OTHER' });
    await refetch();
  };
  const handleDocRemove = async (id: string | number) => {
    await deleteDoc.mutateAsync({ companyId, docId: Number(id) });
    await refetch();
  };

  // `doc_type_display` is the Russian-only lookup name — fallback for an unknown code.
  const docTypeLabel = (doc: { doc_type_code?: string | null; doc_type_display?: string | null }): string => {
    const key = kycDocTypeLabelKey(doc.doc_type_code);
    return key ? t(key) : doc.doc_type_display || '';
  };

  const docs = (company?.kyc_documents ?? []).map(d => ({
    id: d.id,
    name: docTypeLabel(d)
      ? `${docTypeLabel(d)} — ${d.original_filename}`
      : d.original_filename,
    url: d.file ?? null,
    uploaded_at: d.uploaded_at,
  }));

  return (
    <div className="space-y-4">
      <ImageUpload
        value={company?.logo ?? null}
        onUpload={handleLogoUpload}
        onRemove={handleLogoRemove}
        fallback={company?.name ? company.name.slice(0, 2).toUpperCase() : '—'}
        label={t('profile.companyInfo.logo')}
        description={t('profile.companyInfo.logoDescription')}
      />
      <Separator />
      <div>
        <Label className="text-sm font-medium">{t('profile.companyInfo.kycDocuments')}</Label>
        <FileUpload
          className="mt-2"
          files={docs}
          onUpload={handleDocUpload}
          onRemove={handleDocRemove}
          description={t('profile.companyInfo.kycDocumentsHelp')}
        />
      </div>
    </div>
  );
}

function CompanyFormSheet({
  open, onOpenChange, target,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: Company | null;
}) {
  const { t } = useTranslation();
  const createMut = useCreateCompany();
  const updateMut = useUpdateCompany();
  const [draft, setDraft] = useDraftState<Company | null, Draft>(target, (t) => (t ? { ...t } : emptyDraft()));


  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);
  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.name?.trim() || !draft.inn?.trim()) {
      toast.error(t('adminCompanies.requiredFields'));
      return;
    }
    const payload: Partial<Company> = {
      name: draft.name,
      inn: draft.inn,
      legal_address: draft.legal_address ?? '',
      bank_account: draft.bank_account ?? '',
      mfo: draft.mfo ?? '',
      contact_person: draft.contact_person ?? '',
      contact_info: draft.contact_info ?? '',
      email: draft.email ?? '',
      website: draft.website ?? '',
    };
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('adminCompanies.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminCompanies.created'));
      }
      onOpenChange(false);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminCompanies.edit') : t('adminCompanies.new')}</SheetTitle>
        </SheetHeader>

        <Tabs defaultValue="registry" className="mt-4 px-4">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="registry" className="text-xs">{t('adminCompanies.tabs.registry')}</TabsTrigger>
            <TabsTrigger value="members" disabled={!isEdit} className="text-xs">
              {t('adminCompanies.tabs.members')}
            </TabsTrigger>
            <TabsTrigger value="files" disabled={!isEdit} className="text-xs">
              {t('adminCompanies.tabs.files')}
            </TabsTrigger>
            <TabsTrigger value="timeline" disabled={!isEdit} className="text-xs">
              {t('platformAdmin.activity.title')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="registry" className="mt-4 space-y-4">
            {isEdit && target ? (
              <DetailKPIGrid
                columns={4}
                items={[
                  {
                    label: t('adminCompanies.table.kyc'),
                    value: target.verification_status_code ?? '—',
                    tone:
                      target.verification_status_code === 'L2_VERIFIED' ||
                      target.verification_status_code === 'L3_CONTRACTED'
                        ? 'success'
                        : target.verification_status_code === 'PROFILE_SUBMITTED'
                          ? 'warning'
                          : 'default',
                  },
                  {
                    label: t('adminCompanies.table.types'),
                    value: (target.company_types ?? []).join(', ') || '—',
                  },
                  {
                    label: t('adminCompanies.stats.members'),
                    value: String(target.user_count ?? 0),
                  },
                  {
                    label: t('adminCompanies.table.created'),
                    value: target.created_at
                      ? formatDate(target.created_at)
                      : '—',
                  },
                ]}
              />
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2 col-span-2">
                <Label>{t('adminCompanies.fields.name')}</Label>
                <Input value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.inn')}</Label>
                <Input value={draft.inn ?? ''} onChange={(e) => update({ inn: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.mfo')}</Label>
                <Input value={draft.mfo ?? ''} onChange={(e) => update({ mfo: e.target.value })} />
              </div>
              <div className="space-y-2 col-span-2">
                <Label>{t('adminCompanies.fields.bankAccount')}</Label>
                <Input value={draft.bank_account ?? ''} onChange={(e) => update({ bank_account: e.target.value })} />
              </div>
              <div className="space-y-2 col-span-2">
                <Label>{t('adminCompanies.fields.legalAddress')}</Label>
                <Input value={draft.legal_address ?? ''} onChange={(e) => update({ legal_address: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.contactPerson')}</Label>
                <Input value={draft.contact_person ?? ''} onChange={(e) => update({ contact_person: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.contactInfo')}</Label>
                <Input value={draft.contact_info ?? ''} onChange={(e) => update({ contact_info: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.email')}</Label>
                <Input value={draft.email ?? ''} onChange={(e) => update({ email: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('adminCompanies.fields.website')}</Label>
                <Input value={draft.website ?? ''} onChange={(e) => update({ website: e.target.value })} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="members" className="mt-4">
            {isEdit && target ? <MembersPanel companyId={target.id} /> : null}
          </TabsContent>

          <TabsContent value="files" className="mt-4">
            {isEdit && target ? <CompanyFilesPanel companyId={target.id} /> : null}
          </TabsContent>

          <TabsContent value="timeline" className="mt-4">
            {isEdit && target ? (
              <AdminActivityTimeline entityType="company" entityId={target.id} />
            ) : null}
          </TabsContent>
        </Tabs>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminCompanies.save') : t('adminCompanies.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

const STORAGE_KEY = 'adminCompanies';

export function AdminCompaniesPage() {
  const { t } = useTranslation();
  const tableState = useAdminTableQueryState(STORAGE_KEY);
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (tableState.search) p.search = tableState.search;
    const tab = tableState.tab || 'all';
    if (tab.startsWith('kyc:')) {
      p.verification_status__code = tab.slice(4);
    } else if (tab.startsWith('type:')) {
      p['types__code'] = tab.slice(5);
    } else if (tab === 'archived') {
      p.is_active = 'false';
    }
    // Вкладка «Архивные» — единственный способ увидеть выведенные из оборота компании; на
    // остальных вкладках их не показываем, иначе архив не выводит из оборота, а только красит.
    if (tab !== 'archived') p.is_active = 'true';
    return Object.keys(p).length ? p : undefined;
  }, [tableState.search, tableState.tab]);
  // Реестр без пагинации в UI: без полной выборки оператор видел первые 20 компаний из 42,
  // а плашка «Всего» печатала 20 — то есть врала уверенно.
  const { data: companies = [], isLoading, isError, refetch } = useCompanies({ ...(queryParams ?? {}), fetchAll: true });
  const deleteMut = useDeleteCompany();
  const archiveMut = useArchiveCompany();
  const unarchiveMut = useUnarchiveCompany();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Company | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Company | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Company | null>(null);
  const [mergeTarget, setMergeTarget] = useState<Company | null>(null);

  const onEdit = (c: Company) => {
    setEditTarget(c);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };
  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('adminCompanies.deleted'));
      setDeleteTarget(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onArchive = async (reason: string) => {
    if (!archiveTarget) return;
    await archiveMut.mutateAsync({ id: archiveTarget.id, reason });
    toast.success(t('adminCompanies.archived'));
    setArchiveTarget(null);
  };

  const onUnarchive = async (company: Company) => {
    try {
      await unarchiveMut.mutateAsync(company.id);
      toast.success(t('adminCompanies.unarchived'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const stats = [
    { label: t('adminCompanies.stats.total'), value: String(companies.length) },
  ];

  return (
    <PageShell
      title={t('adminCompanies.title')}
      description={t('adminCompanies.description')}
      icon={<Building2 className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
      <AdminDataTable<Company>
        storageKey={STORAGE_KEY}
        rows={companies}
        getRowId={(c) => c.id}
        isLoading={isLoading}
        onRowClick={(c) => onEdit(c)}
        searchPlaceholder={t('adminCompanies.searchPlaceholder')}
        exportUrl={`${window.location.origin}/api/v1/accounts/companies/export/`}
        primaryAction={
          <Button size="sm" className="h-8 text-xs" onClick={onNew}>
            {t('adminCompanies.new')}
          </Button>
        }
        tabs={[
          { id: 'all', label: t('common.all') },
          { id: 'kyc:PROFILE_SUBMITTED', label: t('kycManager.status.P_SUBMITTED') },
          { id: 'kyc:L2_VERIFIED', label: t('kycManager.status.V_VERIFIED_L2') },
          { id: 'kyc:L1_UNVERIFIED', label: t('kycManager.status.P_PENDING') },
          { id: 'type:CLIENT', label: t('companyStatus.BUYER') },
          { id: 'type:SUPPLIER', label: t('companyStatus.SELLER') },
          { id: 'type:MANUFACTURER', label: t('companyStatus.MANUFACTURER') },
          // Odoo держит архив за фильтром, а не прячет: иначе выведенная из оборота компания
          // исчезает навсегда — ровно тот тупик, что был у справочников (#603).
          { id: 'archived', label: t('adminCompanies.archive.tab') },
        ]}
        columns={[
          {
            id: 'name',
            header: t('adminCompanies.table.name'),
            cell: (c) => <span className="font-medium">{c.name}</span>,
            alwaysVisible: true,
            sortKey: 'name',
          },
          {
            id: 'inn',
            header: t('adminCompanies.table.inn'),
            cell: (c) => <span className="font-mono tabular-nums">{c.inn}</span>,
          },
          {
            id: 'kyc',
            header: t('adminCompanies.table.kyc'),
            cell: (c) => {
              const code = c.verification_status_code ?? '';
              const badge = KYC_BADGE[code];
              return badge ? (
                <Badge variant={badge.variant}>{t(badge.labelKey)}</Badge>
              ) : (
                <Badge variant="outline">—</Badge>
              );
            },
          },
          {
            id: 'types',
            header: t('adminCompanies.table.types'),
            cell: (c) => (
              <span className="text-muted-foreground">
                {(c.company_types ?? [])
                  .map((code2) =>
                    TYPE_LABEL_KEY[code2] ? t(TYPE_LABEL_KEY[code2]) : code2,
                  )
                  .join(', ') || '—'}
              </span>
            ),
          },
          {
            id: 'created',
            header: t('adminCompanies.table.created'),
            cell: (c) =>
              c.created_at ? (
                <span className="text-muted-foreground">
                  {formatDate(c.created_at)}
                </span>
              ) : (
                <span className="text-muted-foreground">—</span>
              ),
            hideByDefault: true,
          },
        ]}
        rowActions={[
          {
            id: 'edit',
            label: t('adminCompanies.edit'),
            icon: <Pencil className="h-3.5 w-3.5" />,
            onRun: (c) => onEdit(c),
          },
          {
            id: 'merge',
            label: t('adminCompanies.merge.action'),
            icon: <GitMerge className="h-3.5 w-3.5" />,
            onRun: (c) => setMergeTarget(c),
          },
          {
            id: 'archive',
            label: t('adminCompanies.archive.action'),
            icon: <Archive className="h-3.5 w-3.5" />,
            // Архив — штатная замена удалению (Odoo Archive): компания уходит из подбора и
            // справочников, история остаётся. У уже архивной действие бессмысленно.
            disabled: (c) => c.is_active === false,
            onRun: (c) => setArchiveTarget(c),
          },
          {
            id: 'unarchive',
            label: t('adminCompanies.archive.restore'),
            icon: <ArchiveRestore className="h-3.5 w-3.5" />,
            disabled: (c) => c.is_active !== false,
            onRun: (c) => onUnarchive(c),
          },
          {
            id: 'delete',
            label: t('adminCompanies.delete'),
            icon: <Trash2 className="h-3.5 w-3.5" />,
            variant: 'destructive',
            // Способность приходит с сервера (Salesforce `deletable`): компанию с историей
            // удалить нельзя ни в одном эталоне, и кнопка, которая ГАРАНТИРОВАННО откажет, —
            // тот же тупик, только вежливый. Причина видна в подсказке пункта.
            disabled: (c) => c.can_delete === false,
            onRun: (c) => setDeleteTarget(c),
          },
        ]}
        emptyIcon={<Building2 className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('adminCompanies.emptyState')}
      />
      )}

      <CompanyFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

      <MergeDuplicatesDialog
        survivor={mergeTarget}
        onOpenChange={(open) => !open && setMergeTarget(null)}
      />

      <ConfirmActionDialog
        open={!!archiveTarget}
        onOpenChange={(open) => !open && setArchiveTarget(null)}
        title={t('adminCompanies.archive.title')}
        description={t('adminCompanies.archive.description', { name: archiveTarget?.name ?? '' })}
        requireReason
        confirmLabel={t('adminCompanies.archive.confirm')}
        variant="warning"
        translateError={(code) => translateApiError(code)}
        onConfirm={(payload) => onArchive(payload.reason)}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('adminCompanies.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('adminCompanies.confirmDeleteDesc', { name: deleteTarget?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('adminCompanies.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('adminCompanies.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminCompaniesPage;
