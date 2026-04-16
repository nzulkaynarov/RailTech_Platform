import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Users, Check, Clock } from 'lucide-react';
import { useCompanies } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { Company } from '@/api/accountsApi';

export function ClientsPage() {
  const { t } = useTranslation();
  const { data: companies, isLoading } = useCompanies();

  return (
    <PageShell
      title={t('pages.clients.title')}
      description={t('pages.clients.description')}
      icon={<Users className="h-5 w-5" />}
      stats={[
        { label: t('pages.clients.stats.total'), value: String(companies?.length ?? 0) },
        { label: t('pages.clients.stats.verified'), value: String(companies?.filter(c => c.verification_status_code === 'L2_VERIFIED' || c.verification_status_code === 'L3_CONTRACTED').length ?? 0) },
        { label: t('pages.clients.stats.awaitingKyc'), value: String(companies?.filter(c => c.verification_status_code === 'PROFILE_SUBMITTED').length ?? 0) },
        { label: t('pages.clients.stats.guests'), value: String(companies?.filter(c => c.verification_status_code === 'L1_UNVERIFIED').length ?? 0) },
      ]}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !companies?.length ? (
            <EmptyState icon={<Users className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('pages.clients.table.company')}</TableHead>
                  <TableHead>{t('pages.clients.table.inn')}</TableHead>
                  <TableHead>{t('pages.clients.table.kyc')}</TableHead>
                  <TableHead className="text-center">{t('pages.clients.table.deals')}</TableHead>
                  <TableHead>{t('pages.clients.table.lastActivity')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {companies.map((company: Company) => (
                  <TableRow key={company.id}>
                    <TableCell className="font-medium">{company.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{company.inn}</TableCell>
                    <TableCell>
                      <Badge variant={company.verification_status === 'VERIFIED' ? 'default' : 'secondary'} className="gap-1">
                        {company.verification_status === 'VERIFIED'
                          ? <><Check className="h-3 w-3" /> {t('pages.clients.kycStatus.verified')}</>
                          : <><Clock className="h-3 w-3" /> {t('pages.clients.kycStatus.pending')}</>}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-center tabular-nums">{company.user_count ?? 0}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{company.created_at ? new Date(company.created_at).toLocaleDateString() : ''}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default ClientsPage;
