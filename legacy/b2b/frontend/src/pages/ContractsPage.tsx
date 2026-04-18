import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { FileText, Download, PenLine, Upload, Ban, FileSignature } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import {
  useContracts, useSignContractClient, useSignContractManager,
  useUploadSignedContract, useCancelContract,
} from '@/hooks/useBilling';
import type { Contract, ContractStatus } from '@/api/contractsApi';

const STATUS_VARIANT: Record<ContractStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  PENDING_CLIENT: 'outline',
  PENDING_MANAGER: 'outline',
  SIGNED: 'default',
  CANCELLED: 'destructive',
};

const STATUS_CODES: ContractStatus[] = [
  'DRAFT', 'PENDING_CLIENT', 'PENDING_MANAGER', 'SIGNED', 'CANCELLED',
];

export function ContractsPage() {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Contract | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Contract | null>(null);
  const [cancelReason, setCancelReason] = useState('');

  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (statusFilter !== 'all') p.status = statusFilter;
    if (search) p.search = search;
    return Object.keys(p).length ? p : undefined;
  }, [statusFilter, search]);

  const { data: contracts, isLoading } = useContracts(queryParams);
  const signClient = useSignContractClient();
  const signManager = useSignContractManager();
  const uploadSigned = useUploadSignedContract();
  const cancelMut = useCancelContract();

  const stats = useMemo(() => {
    const list = contracts ?? [];
    return [
      { label: t('contractsPage.stats.total'), value: String(list.length) },
      {
        label: t('contractsPage.stats.pending'),
        value: String(list.filter((c) => c.status === 'PENDING_CLIENT' || c.status === 'PENDING_MANAGER').length),
      },
      {
        label: t('contractsPage.stats.signed'),
        value: String(list.filter((c) => c.status === 'SIGNED').length),
      },
    ];
  }, [contracts, t]);

  const onSignClient = async (c: Contract) => {
    try {
      await signClient.mutateAsync(c.id);
      toast.success(t('contractsPage.signedClient'));
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  const onSignManager = async (c: Contract) => {
    try {
      await signManager.mutateAsync(c.id);
      toast.success(t('contractsPage.signedManager'));
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  const onUploadFile = async (c: Contract, file: File) => {
    try {
      await uploadSigned.mutateAsync({ id: c.id, file });
      toast.success(t('contractsPage.uploadedSigned'));
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  const onCancel = async () => {
    if (!cancelTarget) return;
    try {
      await cancelMut.mutateAsync({ id: cancelTarget.id, reason: cancelReason });
      toast.success(t('contractsPage.cancelled'));
      setCancelTarget(null);
      setCancelReason('');
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  return (
    <PageShell
      title={t('contractsPage.title')}
      description={t('contractsPage.description')}
      icon={<FileSignature className="h-5 w-5" />}
      stats={stats}
    >
      <Card>
        <CardContent className="flex flex-col gap-4 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('contractsPage.searchPlaceholder')}
              className="max-w-xs"
            />
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('contractsPage.allStatuses')}</SelectItem>
                {STATUS_CODES.map((s) => (
                  <SelectItem key={s} value={s}>{t(`contractsPage.status.${s}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isLoading ? <LoadingRows rows={6} /> : (contracts?.length ?? 0) === 0 ? (
            <EmptyState icon={<FileSignature className="h-5 w-5" />} message={t('contractsPage.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('contractsPage.table.number')}</TableHead>
                  <TableHead>{t('contractsPage.table.deal')}</TableHead>
                  <TableHead>{t('contractsPage.table.total')}</TableHead>
                  <TableHead>{t('contractsPage.table.status')}</TableHead>
                  <TableHead>{t('contractsPage.table.created')}</TableHead>
                  <TableHead className="text-right">{t('contractsPage.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(contracts ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.number}</TableCell>
                    <TableCell>#{c.deal}</TableCell>
                    <TableCell className="tabular-nums">{c.total_amount}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[c.status]}>
                        {t(`contractsPage.status.${c.status}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(c.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setSelected(c)}>
                        <FileText className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.number}</SheetTitle>
              <SheetDescription>
                <Badge variant={STATUS_VARIANT[selected.status]}>
                  {t(`contractsPage.status.${selected.status}`)}
                </Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('contractsPage.table.deal')}</Label><p>#{selected.deal}</p></div>
                <div><Label>{t('contractsPage.table.total')}</Label><p className="tabular-nums">{selected.total_amount}</p></div>
                <div>
                  <Label>{t('contractsPage.signClient')}</Label>
                  <p className="text-muted-foreground">
                    {selected.client_signed_at
                      ? `${selected.client_signer_name} · ${new Date(selected.client_signed_at).toLocaleString()}`
                      : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('contractsPage.signManager')}</Label>
                  <p className="text-muted-foreground">
                    {selected.manager_signed_at
                      ? `${selected.manager_signer_name} · ${new Date(selected.manager_signed_at).toLocaleString()}`
                      : '—'}
                  </p>
                </div>
              </div>
              {selected.notes && (
                <div>
                  <Label>{t('contractsPage.cancelReason')}</Label>
                  <p className="whitespace-pre-wrap text-sm">{selected.notes}</p>
                </div>
              )}
              <div className="flex flex-col gap-2">
                {selected.pdf_url && (
                  <Button variant="outline" asChild>
                    <a href={selected.pdf_url} target="_blank" rel="noreferrer">
                      <Download className="mr-2 h-4 w-4" />
                      {t('contractsPage.downloadPdf')}
                    </a>
                  </Button>
                )}
                {(selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
                  <Button onClick={() => onSignClient(selected)} disabled={signClient.isPending}>
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('contractsPage.signClient')}
                  </Button>
                )}
                {(selected.status === 'PENDING_MANAGER' || selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
                  <Button onClick={() => onSignManager(selected)} disabled={signManager.isPending}>
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('contractsPage.signManager')}
                  </Button>
                )}
                <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm hover:bg-accent">
                  <Upload className="h-4 w-4" />
                  <span>{t('contractsPage.uploadSigned')}</span>
                  <input
                    type="file"
                    className="hidden"
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onUploadFile(selected, f);
                    }}
                  />
                </label>
                {selected.status !== 'CANCELLED' && selected.status !== 'SIGNED' && (
                  <Button variant="destructive" onClick={() => setCancelTarget(selected)}>
                    <Ban className="mr-2 h-4 w-4" />
                    {t('contractsPage.cancel')}
                  </Button>
                )}
              </div>
            </div>
            <SheetFooter />
          </SheetContent>
        </Sheet>
      )}

      <AlertDialog open={!!cancelTarget} onOpenChange={(o) => !o && setCancelTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('contractsPage.confirmCancel')}</AlertDialogTitle>
            <AlertDialogDescription>{cancelTarget?.number}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cancelReason">{t('contractsPage.cancelReason')}</Label>
            <Textarea
              id="cancelReason"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onCancel} disabled={cancelMut.isPending}>
              {t('contractsPage.cancel')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default ContractsPage;
