import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Building2, Pencil, Trash2, UserPlus } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/AdminTable';

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

const KYC_FILTER_OPTIONS = ['L1_UNVERIFIED', 'PROFILE_SUBMITTED', 'L2_VERIFIED', 'L3_CONTRACTED'];
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import {
  useCompanies, useCreateCompany, useUpdateCompany, useDeleteCompany,
  useCompanyTeam, useInviteMember,
} from '@/hooks/useAccounts';
import type { Company } from '@/api/accountsApi';

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
    } catch {
      toast.error(t('adminCompanies.inviteFailed'));
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
  const [draft, setDraft] = useState<Draft>(() => target ?? emptyDraft());

  useMemo(() => setDraft(target ? { ...target } : emptyDraft()), [target]);

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
    } catch {
      toast.error(t('adminCompanies.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminCompanies.edit') : t('adminCompanies.new')}</SheetTitle>
        </SheetHeader>

        <Tabs defaultValue="registry" className="mt-4 px-4">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="registry">{t('adminCompanies.tabs.registry')}</TabsTrigger>
            <TabsTrigger value="members" disabled={!isEdit}>
              {t('adminCompanies.tabs.members')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="registry" className="mt-4 space-y-4">
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

export function AdminCompaniesPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['kyc', 'type'] as const, { defaultOrdering: 'name' });
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (listParams.search) p.search = listParams.search;
    if (listParams.filters.kyc !== 'all') p.verification_status__code = listParams.filters.kyc;
    if (listParams.filters.type !== 'all') p.types__code = listParams.filters.type;
    return Object.keys(p).length ? p : undefined;
  }, [listParams.search, listParams.filters]);
  const { data: companies, isLoading } = useCompanies(queryParams);
  const deleteMut = useDeleteCompany();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Company | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Company | null>(null);

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
    } catch {
      toast.error(t('adminCompanies.deleteFailed'));
    }
  };

  const stats = [
    { label: t('adminCompanies.stats.total'), value: String(companies?.length ?? '—') },
  ];

  return (
    <PageShell
      title={t('adminCompanies.title')}
      description={t('adminCompanies.description')}
      icon={<Building2 className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('adminCompanies.searchPlaceholder')}
        filters={[
          {
            key: 'kyc',
            value: listParams.filters.kyc,
            onChange: (v) => listParams.setFilter('kyc', v),
            allLabel: t('adminCompanies.allKyc'),
            options: KYC_FILTER_OPTIONS.map((k) => ({ value: k, label: t(KYC_BADGE[k].labelKey) })),
          },
          {
            key: 'type',
            value: listParams.filters.type,
            onChange: (v) => listParams.setFilter('type', v),
            allLabel: t('adminCompanies.allTypes'),
            options: Object.entries(TYPE_LABEL_KEY).map(([code, labelKey]) => ({
              value: code, label: t(labelKey),
            })),
          },
        ]}
        newLabel={t('adminCompanies.new')}
        onNew={onNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(companies ?? [], listParams, {
              searchFields: (c) => [c.name, c.inn, c.mfo, c.contact_person, c.email],
              sortAccessors: {
                name: (c) => c.name,
                inn: (c) => c.inn,
                kyc: (c) => c.verification_status_code ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (!pageItems.length) return <EmptyState icon={<Building2 className="h-5 w-5" />} message={t('adminCompanies.emptyState')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('adminCompanies.table.name')}
                  </SortableHead>
                  <SortableHead sortKey="inn" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('adminCompanies.table.inn')}
                  </SortableHead>
                  <SortableHead sortKey="kyc" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('adminCompanies.table.kyc')}
                  </SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}}>
                    {t('adminCompanies.table.types')}
                  </SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}} className="text-right">
                    {t('adminCompanies.table.actions')}
                  </SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((c) => {
                  const code = c.verification_status_code ?? '';
                  const badge = KYC_BADGE[code];
                  return (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.name}</TableCell>
                    <TableCell className="font-mono text-xs">{c.inn}</TableCell>
                    <TableCell>
                      {badge
                        ? <Badge variant={badge.variant}>{t(badge.labelKey)}</Badge>
                        : <Badge variant="outline">—</Badge>}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {(c.company_types ?? []).map((code2) =>
                        TYPE_LABEL_KEY[code2] ? t(TYPE_LABEL_KEY[code2]) : code2
                      ).join(', ') || '—'}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(c)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(c)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );})}
              </TableBody>
            </Table>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
            </>
            );
          })()}
        </CardContent>
      </Card>

      <CompanyFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

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
