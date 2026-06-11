import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Users, Check, Clock } from 'lucide-react';
import { useCompanies } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { VerificationStatus } from '@/lib/codes';
import type { Company } from '@/api/accountsApi';

const VERIFIED_CODES: string[] = [VerificationStatus.L2_VERIFIED, VerificationStatus.L3_CONTRACTED];

const KYC_OPTIONS = [
  { value: 'L1_UNVERIFIED', labelKey: 'kycManager.status.P_PENDING' },
  { value: 'PROFILE_SUBMITTED', labelKey: 'kycManager.status.P_SUBMITTED' },
  { value: 'L2_VERIFIED', labelKey: 'kycManager.status.V_VERIFIED_L2' },
  { value: 'L3_CONTRACTED', labelKey: 'kycManager.status.V_PARTNER_L3' },
];

export function ClientsPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['kyc'] as const, { defaultOrdering: 'name' });
  const { data: companies, isLoading } = useCompanies();

  return (
    <PageShell
      title={t('pages.clients.title')}
      description={t('pages.clients.description')}
      icon={<Users className="h-5 w-5" />}
      stats={[
        { label: t('pages.clients.stats.total'), value: String(companies?.length ?? 0) },
        { label: t('pages.clients.stats.verified'), value: String(companies?.filter(c => VERIFIED_CODES.includes(c.verification_status_code ?? '')).length ?? 0) },
        { label: t('pages.clients.stats.awaitingKyc'), value: String(companies?.filter(c => c.verification_status_code === VerificationStatus.PROFILE_SUBMITTED).length ?? 0) },
        { label: t('pages.clients.stats.guests'), value: String(companies?.filter(c => c.verification_status_code === VerificationStatus.L1_UNVERIFIED).length ?? 0) },
      ]}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.clients.searchPlaceholder')}
        filters={[
          {
            key: 'kyc',
            value: listParams.filters.kyc,
            onChange: (v) => listParams.setFilter('kyc', v),
            allLabel: t('pages.clients.allKyc'),
            options: KYC_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(companies ?? [], listParams, {
              searchFields: (c) => [c.name, c.inn, c.email],
              filterPredicates: {
                kyc: (c, v) => c.verification_status_code === v,
              },
              sortAccessors: {
                name: (c) => c.name,
                inn: (c) => c.inn,
                kyc: (c) => c.verification_status_code ?? '',
                created_at: (c) => c.created_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (!pageItems.length) return <EmptyState icon={<Users className="h-5 w-5" />} message={t('pages.common.noData')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.clients.table.company')}</SortableHead>
                  <SortableHead sortKey="inn" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.clients.table.inn')}</SortableHead>
                  <SortableHead sortKey="kyc" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.clients.table.kyc')}</SortableHead>
                  <TableHead className="text-center">{t('pages.clients.table.deals')}</TableHead>
                  <SortableHead sortKey="created_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.clients.table.lastActivity')}</SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((company: Company) => (
                  <TableRow key={company.id}>
                    <TableCell className="font-medium">{company.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{company.inn}</TableCell>
                    <TableCell>
                      <Badge variant={VERIFIED_CODES.includes(company.verification_status_code ?? '') ? 'default' : 'secondary'} className="gap-1">
                        {VERIFIED_CODES.includes(company.verification_status_code ?? '')
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
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
            </>
            );
          })()}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default ClientsPage;
