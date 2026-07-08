import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Inbox, Mail, Phone, Building2, ArrowRightLeft } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { useLeads, useConvertLead } from '@/hooks/useCRM';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import { PageShell } from './shared/PageShell';
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
  const { data: leads = [], isLoading } = useLeads();
  const convertLead = useConvertLead();
  const { tab } = useAdminTableQueryState(STORAGE_KEY);
  const [selected, setSelected] = useState<Lead | null>(null);

  const filtered = useMemo(() => {
    if (tab === 'new') return leads.filter((lead) => !lead.is_processed);
    if (tab === 'processed') return leads.filter((lead) => lead.is_processed);
    return leads;
  }, [leads, tab]);

  const newCount = useMemo(() => leads.filter((lead) => !lead.is_processed).length, [leads]);

  const handleConvert = async (lead: Lead) => {
    if (lead.id == null) return;
    try {
      const result = await convertLead.mutateAsync({ leadId: lead.id });
      toast.success(t('admin.leads.toast.converted', { id: result.deal_id }));
    } catch (err) {
      // The service returns LEAD_NO_CLIENT_COMPANY when the lead email matches no
      // registered company yet — surface it so the operator knows the prospect
      // must register (or be created as an offline client) first.
      toast.error(translateApiError(err));
    }
  };

  return (
    <PageShell
      icon={<Inbox className="h-5 w-5" />}
      title={t('admin.leads.title')}
      description={t('admin.leads.subtitle')}
    >
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
            id: 'convert',
            label: t('admin.leads.actions.convert'),
            icon: <ArrowRightLeft className="h-4 w-4" />,
            onRun: handleConvert,
          },
        ]}
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
