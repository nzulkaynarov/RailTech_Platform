import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { KeyRound, Pencil, Trash2, Check, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useDraftState } from '@/hooks/useDraftState';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

import { useCompanies } from '@/hooks/useAccounts';
import {
  useEntitlements, useEntitlementChoices, useCreateEntitlement, useUpdateEntitlement, useDeleteEntitlement,
} from '@/hooks/useAdmin';
import { translateApiError } from '@/lib/apiError';
import { PageShell, ErrorState } from './shared/PageShell';
import { Skeleton } from '@/components/ui/skeleton';
import { entitlementAccessLabelKey } from '@/lib/codes';
import type { CompanyEntitlement, CompanyEntitlementDraft } from '@/api/adminApi';

const ALL = '__all__';

/** Access-state → Badge variant. Codes come from the backend choices (no enum hard-coded). */
function accessVariant(access: string): 'default' | 'secondary' | 'outline' {
  if (access === 'ENABLED') return 'default';
  if (access === 'DEMO') return 'secondary';
  return 'outline'; // DISABLED / anything else
}

/**
 * Localized label for an access-state CODE. The backend `access_display` field and the
 * `access_states[].label` choices are `get_access_display()` output — Russian-only at the
 * source — so they are kept only as a fallback for a code the localized map does not know.
 */
function useAccessLabel() {
  const { t } = useTranslation();
  return (code?: string | null, fallback?: string | null): string => {
    const key = entitlementAccessLabelKey(code);
    return key ? t(key) : fallback || code || '';
  };
}

/* ─── Grant / edit form ──────────────────────────────────────────────────── */
function EntitlementForm({
  entitlement, open, onOpenChange,
}: {
  entitlement: CompanyEntitlement | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const accessLabel = useAccessLabel();
  // Оператор выдаёт права и заводит подписки КОНКРЕТНОЙ компании, поэтому список должен быть
  // полным: без fetchAll сюда приходила только первая страница (20 из 42), и боевых компаний
  // в выборе просто не было — путь монетизации упирался в невидимый предел страницы.
  const { data: companiesRaw } = useCompanies({ fetchAll: true });
  const { data: choices } = useEntitlementChoices();
  const createMut = useCreateEntitlement();
  const updateMut = useUpdateEntitlement();
  const isEdit = Boolean(entitlement?.id);

  const companies = useMemo(() => (companiesRaw ?? []) as { id: number; name: string }[], [companiesRaw]);

  function blank(): CompanyEntitlementDraft {
    return { company: 0, feature_key: '', access: 'ENABLED', limit: null, credits: null, expires_at: null, note: '' };
  }
  // Источник черновика — пара «открытие диалога + редактируемая запись»: каждое новое открытие
  // начинается с чистого листа, а правки внутри одного открытия переживают рефетч списка.
  const [draft, setDraft] = useDraftState(
    open ? entitlement ?? null : null,
    (source) => (source
      ? {
          company: source.company, feature_key: source.feature_key, access: source.access,
          limit: source.limit, credits: source.credits, expires_at: source.expires_at, note: source.note,
        }
      : blank()),
  );

  const busy = createMut.isPending || updateMut.isPending;
  const patch = (p: Partial<CompanyEntitlementDraft>) => setDraft((d) => ({ ...d, ...p }));

  const submit = async () => {
    if (!draft.company || !draft.feature_key || !draft.access) {
      toast.error(t('adminEntitlements.requiredFields'));
      return;
    }
    const payload: CompanyEntitlementDraft = {
      company: Number(draft.company),
      feature_key: draft.feature_key,
      access: draft.access,
      limit: draft.limit === null || draft.limit === undefined ? null : Number(draft.limit),
      credits: draft.credits === null || draft.credits === undefined ? null : Number(draft.credits),
      expires_at: draft.expires_at || null,
      note: draft.note ?? '',
    };
    try {
      if (isEdit && entitlement) {
        await updateMut.mutateAsync({ id: entitlement.id, data: payload });
        toast.success(t('adminEntitlements.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminEntitlements.grantedToast'));
      }
      onOpenChange(false);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminEntitlements.edit') : t('adminEntitlements.grant')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('adminEntitlements.company')}</Label>
            <Select value={draft.company ? String(draft.company) : ''} onValueChange={(v) => patch({ company: Number(v) })} disabled={isEdit}>
              <SelectTrigger><SelectValue placeholder={t('adminEntitlements.companyPlaceholder')} /></SelectTrigger>
              <SelectContent>
                {companies.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t('adminEntitlements.feature')}</Label>
            <Select value={draft.feature_key} onValueChange={(v) => patch({ feature_key: v })} disabled={isEdit}>
              <SelectTrigger><SelectValue placeholder={t('adminEntitlements.featurePlaceholder')} /></SelectTrigger>
              <SelectContent>
                {(choices?.feature_keys ?? []).map((f) => (
                  <SelectItem key={f.value} value={f.value}>{f.label} <span className="text-muted-foreground">({f.value})</span></SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t('adminEntitlements.access')}</Label>
            <Select value={draft.access} onValueChange={(v) => patch({ access: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {(choices?.access_states ?? []).map((accessState) => (
                  <SelectItem key={accessState.value} value={accessState.value}>
                    {accessLabel(accessState.value, accessState.label)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('adminEntitlements.accessHint')}</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminEntitlements.credits')}</Label>
              <Input type="number" min={0} value={draft.credits ?? ''} onChange={(e) => patch({ credits: e.target.value === '' ? null : Number(e.target.value) })} placeholder="—" />
            </div>
            <div className="space-y-2">
              <Label>{t('adminEntitlements.limit')}</Label>
              <Input type="number" min={0} value={draft.limit ?? ''} onChange={(e) => patch({ limit: e.target.value === '' ? null : Number(e.target.value) })} placeholder="—" />
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t('adminEntitlements.expiresAt')}</Label>
            <Input type="date" value={draft.expires_at ? draft.expires_at.slice(0, 10) : ''} onChange={(e) => patch({ expires_at: e.target.value || null })} />
          </div>

          <div className="space-y-2">
            <Label>{t('adminEntitlements.note')}</Label>
            <Textarea value={draft.note ?? ''} onChange={(e) => patch({ note: e.target.value })} placeholder={t('adminEntitlements.notePlaceholder')} rows={2} />
          </div>
        </div>

        <SheetFooter className="mt-4 px-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={busy}>{isEdit ? t('common.save') : t('adminEntitlements.grant')}</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Page ────────────────────────────────────────────────────────────────── */
export function AdminEntitlementsPage() {
  const { t } = useTranslation();
  const accessLabel = useAccessLabel();
  const [companyFilter, setCompanyFilter] = useState<string>(ALL);
  const params = companyFilter !== ALL ? { company: Number(companyFilter) } : undefined;
  // Пока состояние загрузки не читалось, во время запроса страница утверждала «прав нет»
  // — оператор видел готовый ответ там, где ответа ещё не было (аудит UI, U2).
  const { data: rows = [], isLoading, isError, refetch } = useEntitlements(params);
  const { data: companiesRaw } = useCompanies({ fetchAll: true });
  const del = useDeleteEntitlement();

  const [editing, setEditing] = useState<CompanyEntitlement | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const companies = useMemo(() => (companiesRaw ?? []) as { id: number; name: string }[], [companiesRaw]);

  const openGrant = () => { setEditing(null); setFormOpen(true); };
  const openEdit = (e: CompanyEntitlement) => { setEditing(e); setFormOpen(true); };
  const remove = async (id: number) => {
    try { await del.mutateAsync(id); toast.success(t('adminEntitlements.removed')); }
    catch (e) { toast.error(translateApiError(e)); }
  };

  if (isError) return <ErrorState onRetry={() => refetch()} />;

  return (
    <PageShell
      title={t('adminEntitlements.title')}
      description={t('adminEntitlements.subtitle')}
      icon={<KeyRound className="h-5 w-5" />}
      actions={[{ label: t('adminEntitlements.grant'), onClick: openGrant }]}
    >
      <div className="mb-4 w-64">
        <Select value={companyFilter} onValueChange={setCompanyFilter}>
          <SelectTrigger><SelectValue placeholder={t('adminEntitlements.allCompanies')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('adminEntitlements.allCompanies')}</SelectItem>
            {companies.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('adminEntitlements.company')}</TableHead>
              <TableHead>{t('adminEntitlements.feature')}</TableHead>
              <TableHead>{t('adminEntitlements.access')}</TableHead>
              <TableHead className="text-right">{t('adminEntitlements.credits')}</TableHead>
              <TableHead>{t('adminEntitlements.expiresAt')}</TableHead>
              <TableHead className="text-center">{t('adminEntitlements.granted')}</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 3 }).map((_, index) => (
                <TableRow key={`skeleton-${index}`}>
                  <TableCell colSpan={7} className="py-3"><Skeleton className="h-4 w-full" /></TableCell>
                </TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">{t('adminEntitlements.empty')}</TableCell></TableRow>
            ) : rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="text-sm font-medium">{e.company_name}</TableCell>
                <TableCell className="font-mono text-xs">{e.feature_key}</TableCell>
                <TableCell><Badge variant={accessVariant(e.access)}>{accessLabel(e.access, e.access_display)}</Badge></TableCell>
                <TableCell className="text-right text-sm tabular-nums">{e.credits ?? '—'}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{e.expires_at ? e.expires_at.slice(0, 10) : '—'}</TableCell>
                <TableCell className="text-center">
                  {e.is_granted
                    ? <Check className="mx-auto h-4 w-4 text-primary" aria-label={t('adminEntitlements.granted')} />
                    : <X className="mx-auto h-4 w-4 text-muted-foreground" aria-label={t('adminEntitlements.notGranted')} />}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <Button variant="ghost" size="icon-xs" onClick={() => openEdit(e)} title={t('common.edit')}><Pencil className="size-3" /></Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon-xs" className="text-muted-foreground hover:text-destructive" title={t('common.delete')}><Trash2 className="size-3" /></Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>{t('adminEntitlements.confirmRemoveTitle')}</AlertDialogTitle>
                          <AlertDialogDescription>{t('adminEntitlements.confirmRemoveDesc', { feature: e.feature_key, company: e.company_name })}</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                          <AlertDialogAction onClick={() => remove(e.id)} disabled={del.isPending}>{t('common.delete')}</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <EntitlementForm entitlement={editing} open={formOpen} onOpenChange={setFormOpen} />
    </PageShell>
  );
}

export default AdminEntitlementsPage;
