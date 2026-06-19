import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { ClipboardList, ArrowRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { useLeads, useConvertLead } from '@/hooks/useCRM';
import type { Lead } from '@/api/crmApi';

export function LeadsPage() {
  const { t } = useTranslation();
  const { data: leads, isLoading, isError, refetch } = useLeads();
  const convert = useConvertLead();
  // Converting a lead creates a real deal — confirm before the one-way action.
  const [convertTarget, setConvertTarget] = useState<Lead | null>(null);

  const runConvert = async () => {
    if (!convertTarget?.id) return;
    const res = await convert.mutateAsync({ leadId: convertTarget.id });
    toast.success(`${t('leadsPage.converted')} #${res.deal_id}`);
    // Jump to the deals section so the freshly created deal is visible.
    window.location.hash = 'crm-deals';
  };

  return (
    <PageShell
      title={t('leadsPage.title')}
      description={t('leadsPage.description')}
      icon={<ClipboardList className="h-5 w-5" />}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={6} /> : isError ? (
            <ErrorState onRetry={refetch} />
          ) : (leads?.length ?? 0) === 0 ? (
            <EmptyState icon={<ClipboardList className="h-5 w-5" />} message={t('leadsPage.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('leadsPage.table.name')}</TableHead>
                  <TableHead>{t('leadsPage.table.company')}</TableHead>
                  <TableHead>{t('leadsPage.table.phone')}</TableHead>
                  <TableHead>{t('leadsPage.table.email')}</TableHead>
                  <TableHead>{t('leadsPage.table.message')}</TableHead>
                  <TableHead>{t('leadsPage.table.processed')}</TableHead>
                  <TableHead>{t('leadsPage.table.created')}</TableHead>
                  <TableHead className="text-right">{t('leadsPage.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(leads ?? []).map((lead) => (
                  <TableRow key={lead.id}>
                    <TableCell className="font-medium">{lead.name}</TableCell>
                    <TableCell>{lead.company || '—'}</TableCell>
                    <TableCell>{lead.phone}</TableCell>
                    <TableCell>{lead.email}</TableCell>
                    <TableCell className="max-w-xs truncate">{lead.message || '—'}</TableCell>
                    <TableCell>
                      {lead.is_processed
                        ? <Badge variant="default">✓</Badge>
                        : <Badge variant="secondary">—</Badge>}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {lead.created_at ? new Date(lead.created_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      {!lead.is_processed && (
                        <Button
                          variant="ghost" size="sm"
                          onClick={() => setConvertTarget(lead)}
                          disabled={convert.isPending}
                        >
                          <ArrowRight className="mr-2 h-4 w-4" />
                          {t('leadsPage.convert')}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ConfirmActionDialog
        open={convertTarget != null}
        onOpenChange={(o) => { if (!o) setConvertTarget(null); }}
        title={t('confirmActions.convertLead.title')}
        description={t('confirmActions.convertLead.description', { name: convertTarget?.name ?? '' })}
        variant="primary"
        confirmLabel={t('leadsPage.convert')}
        onConfirm={runConvert}
        translateError={(code) => translateApiError(code)}
      />
    </PageShell>
  );
}

export default LeadsPage;
