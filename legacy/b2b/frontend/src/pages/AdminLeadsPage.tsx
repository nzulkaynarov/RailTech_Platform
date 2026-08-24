import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Inbox, Mail, Phone, Building2, ArrowRightLeft, Ban } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useLeads, useRouteLead, useRejectLead } from '@/hooks/useCRM';
import { useCompanies } from '@/hooks/useAccounts';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { AdminDataTable } from '@/components/Admin/AdminDataTable';
import { useAdminTableQueryState } from '@/components/Admin/useAdminTableQueryState';
import { ErrorState, PageShell } from './shared/PageShell';
import { translateApiError } from '@/lib/apiError';
import type { Lead } from '@/api/crmApi';

const STORAGE_KEY = 'adminLeads';

function formatDate(iso?: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function AdminLeadsPage() {
  const { t } = useTranslation();
  // Сбой загрузки раньше выглядел как «Лидов нет» — оператор читал недоступный API как
  // отсутствие работы (аудит UI, U2). Так же, как на остальных операторских списках.
  const { data: leads = [], isLoading, isError, refetch } = useLeads();
  const routeLead = useRouteLead();
  const rejectLead = useRejectLead();
  // Компании для назначения: активные (архивная работу получать не должна — её сервер отобьёт).
  const { data: companies = [] } = useCompanies({ is_active: 'true', fetchAll: true });
  const { tab } = useAdminTableQueryState(STORAGE_KEY);
  const [selected, setSelected] = useState<Lead | null>(null);
  const [routeTarget, setRouteTarget] = useState<Lead | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Lead | null>(null);
  const [routeCompanyId, setRouteCompanyId] = useState<string>('');

  const filtered = useMemo(() => {
    if (tab === 'new') return leads.filter((lead) => !lead.is_processed);
    if (tab === 'processed') return leads.filter((lead) => lead.is_processed);
    return leads;
  }, [leads, tab]);

  const newCount = useMemo(() => leads.filter((lead) => !lead.is_processed).length, [leads]);

  // Похожие лиды показываем ДО назначения: публичная форма открыта без аутентификации, и
  // дубли ожидаемы по построению — иначе одна заявка уедет в две компании (Odoo «Similar Leads»).
  const similarToRouteTarget = useMemo(() => {
    if (!routeTarget) return [];
    return leads.filter(
      (lead) =>
        lead.id !== routeTarget.id &&
        ((routeTarget.email && lead.email === routeTarget.email) ||
          (routeTarget.phone && lead.phone === routeTarget.phone)),
    );
  }, [leads, routeTarget]);

  const handleRoute = async (reason: string) => {
    if (routeTarget?.id == null || !routeCompanyId) return;
    await routeLead.mutateAsync({ leadId: routeTarget.id, companyId: Number(routeCompanyId), reason });
    toast.success(t('admin.leads.toast.routed'));
    setRouteTarget(null);
    setRouteCompanyId('');
  };

  const handleReject = async (reason: string) => {
    if (rejectTarget?.id == null) return;
    await rejectLead.mutateAsync({ leadId: rejectTarget.id, reason });
    toast.success(t('admin.leads.toast.rejected'));
    setRejectTarget(null);
  };

  return (
    <PageShell
      icon={<Inbox className="h-5 w-5" />}
      title={t('admin.leads.title')}
      description={t('admin.leads.subtitle')}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
      <AdminDataTable<Lead>
        storageKey={STORAGE_KEY}
        rows={filtered}
        getRowId={(lead) => lead.id ?? lead.email}
        isLoading={isLoading}
        searchPlaceholder={t('admin.leads.searchPlaceholder')}
        emptyIcon={<Inbox className="h-8 w-8" />}
        emptyTitle={t('admin.leads.empty.title')}
        emptyDescription={t('admin.leads.empty.description')}
        tabs={[
          { id: 'all', label: t('admin.leads.tabs.all'), count: leads.length },
          { id: 'new', label: t('admin.leads.tabs.new'), count: newCount },
          { id: 'processed', label: t('admin.leads.tabs.processed') },
        ]}
        onRowClick={(lead) => setSelected(lead)}
        columns={[
          {
            id: 'name',
            header: t('admin.leads.col.name'),
            alwaysVisible: true,
            cell: (lead) => <span className="font-medium">{lead.name || '—'}</span>,
          },
          {
            id: 'company',
            header: t('admin.leads.col.company'),
            cell: (lead) => lead.company || '—',
          },
          {
            id: 'email',
            header: t('admin.leads.col.email'),
            cell: (lead) => lead.email || '—',
          },
          {
            id: 'phone',
            header: t('admin.leads.col.phone'),
            cell: (lead) => lead.phone || '—',
          },
          {
            id: 'created_at',
            header: t('admin.leads.col.created'),
            sortKey: 'created_at',
            cell: (lead) => formatDate(lead.created_at),
          },
          {
            id: 'owner',
            header: t('admin.leads.col.owner'),
            cell: (lead) =>
              lead.owner_company_name ? (
                <span>{lead.owner_company_name}</span>
              ) : (
                <span className="text-muted-foreground">{t('admin.leads.queue')}</span>
              ),
          },
          {
            id: 'status',
            header: t('admin.leads.col.status'),
            cell: (lead) => (
              <Badge variant={lead.is_processed ? 'outline' : 'secondary'}>
                {lead.is_processed ? t('admin.leads.status.processed') : t('admin.leads.status.new')}
              </Badge>
            ),
          },
        ]}
        rowActions={[
          {
            id: 'route',
            label: t('admin.leads.actions.route'),
            icon: <ArrowRightLeft className="h-4 w-4" />,
            // Площадка НАЗНАЧАЕТ лид компании; сделку создаёт принимающая сторона своим
            // действием «Взять в работу» (Salesforce Lead Queue + Take Ownership).
            disabled: (lead) => Boolean(lead.is_processed),
            onRun: (lead) => setRouteTarget(lead),
          },
          {
            id: 'reject',
            label: t('admin.leads.actions.reject'),
            icon: <Ban className="h-4 w-4" />,
            variant: 'destructive',
            disabled: (lead) => Boolean(lead.is_processed),
            onRun: (lead) => setRejectTarget(lead),
          },
        ]}
      />
      )}

      <ConfirmActionDialog
        open={routeTarget !== null}
        onOpenChange={(open) => { if (!open) { setRouteTarget(null); setRouteCompanyId(''); } }}
        title={t('admin.leads.route.title')}
        description={
          <>
            {t('admin.leads.route.description', { name: routeTarget?.name ?? '' })}
            {similarToRouteTarget.length > 0 && (
              <span className="mt-2 block font-medium text-warning">
                {t('admin.leads.route.similar', { count: similarToRouteTarget.length })}
              </span>
            )}
            <span className="mt-3 block space-y-1">
              <Label className="text-xs">{t('admin.leads.route.company')}</Label>
              <Select value={routeCompanyId} onValueChange={setRouteCompanyId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('admin.leads.route.companyPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {companies.map((company) => (
                    <SelectItem key={company.id} value={String(company.id)}>
                      {company.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </span>
          </>
        }
        requireReason
        confirmLabel={t('admin.leads.route.confirm')}
        variant="primary"
        translateError={(code) => translateApiError(code)}
        onConfirm={(payload) => handleRoute(payload.reason)}
      />

      <ConfirmActionDialog
        open={rejectTarget !== null}
        onOpenChange={(open) => !open && setRejectTarget(null)}
        title={t('admin.leads.reject.title')}
        description={t('admin.leads.reject.description', { name: rejectTarget?.name ?? '' })}
        requireReason
        confirmLabel={t('admin.leads.reject.confirm')}
        variant="destructive"
        translateError={(code) => translateApiError(code)}
        onConfirm={(payload) => handleReject(payload.reason)}
      />

      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent className="w-full sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{selected?.name || t('admin.leads.detail.title')}</SheetTitle>
          </SheetHeader>
          {selected && (
            <div className="mt-6 space-y-4 text-sm">
              <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-muted-foreground" />
                <span>{selected.company || t('admin.leads.detail.noCompany')}</span>
              </div>
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-muted-foreground" />
                <a href={`mailto:${selected.email}`} className="text-primary hover:underline">{selected.email}</a>
              </div>
              <div className="flex items-center gap-2">
                <Phone className="h-4 w-4 text-muted-foreground" />
                <span>{selected.phone || '—'}</span>
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">{t('admin.leads.detail.message')}</div>
                <p className="whitespace-pre-wrap rounded-md border p-3 text-foreground">
                  {selected.message || t('admin.leads.detail.noMessage')}
                </p>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </PageShell>
  );
}
