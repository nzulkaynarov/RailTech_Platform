import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ScrollText, Download, PenLine } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { useActs, useSignAct } from '@/hooks/useBilling';
import type { ActStatus } from '@/api/billingApi';

const STATUS_VARIANT: Record<ActStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'outline',
  SIGNED: 'default',
  CANCELLED: 'destructive',
};
const STATUS_CODES: ActStatus[] = ['DRAFT', 'ISSUED', 'SIGNED', 'CANCELLED'];

export function ActsPage() {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const queryParams = statusFilter !== 'all' ? { status: statusFilter } : undefined;
  const { data: acts, isLoading } = useActs(queryParams);
  const signAct = useSignAct();

  const stats = useMemo(() => {
    const list = acts ?? [];
    return [
      { label: t('actsPage.stats.total'), value: String(list.length) },
      { label: t('actsPage.stats.issued'), value: String(list.filter((a) => a.status === 'ISSUED').length) },
      { label: t('actsPage.stats.signed'), value: String(list.filter((a) => a.status === 'SIGNED').length) },
    ];
  }, [acts, t]);

  const onSign = async (id: number, file?: File) => {
    try {
      await signAct.mutateAsync({ id, signedFile: file });
      toast.success(t('actsPage.signed'));
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  return (
    <PageShell
      title={t('actsPage.title')}
      description={t('actsPage.description')}
      icon={<ScrollText className="h-5 w-5" />}
      stats={stats}
    >
      <Card>
        <CardContent className="flex flex-col gap-4 p-4">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('actsPage.allStatuses')}</SelectItem>
              {STATUS_CODES.map((s) => (
                <SelectItem key={s} value={s}>{t(`actsPage.status.${s}`)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {isLoading ? <LoadingRows rows={6} /> : (acts?.length ?? 0) === 0 ? (
            <EmptyState icon={<ScrollText className="h-5 w-5" />} message={t('actsPage.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('actsPage.table.number')}</TableHead>
                  <TableHead>{t('actsPage.table.deal')}</TableHead>
                  <TableHead>{t('actsPage.table.total')}</TableHead>
                  <TableHead>{t('actsPage.table.status')}</TableHead>
                  <TableHead>{t('actsPage.table.issued')}</TableHead>
                  <TableHead className="text-right">{t('actsPage.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(acts ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">{a.number}</TableCell>
                    <TableCell>#{a.deal}</TableCell>
                    <TableCell className="tabular-nums">{a.total_amount}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[a.status]}>
                        {t(`actsPage.status.${a.status}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {a.issued_at ? new Date(a.issued_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {a.pdf_url && (
                          <Button variant="ghost" size="sm" asChild>
                            <a href={a.pdf_url} target="_blank" rel="noreferrer">
                              <Download className="h-4 w-4" />
                            </a>
                          </Button>
                        )}
                        {a.status === 'ISSUED' && (
                          <label className="inline-flex cursor-pointer items-center rounded-md px-2 py-1 text-xs hover:bg-accent">
                            <PenLine className="h-4 w-4" />
                            <input
                              type="file"
                              className="hidden"
                              accept=".pdf,.jpg,.png"
                              onChange={(e) => {
                                const f = e.target.files?.[0];
                                onSign(a.id, f);
                              }}
                            />
                          </label>
                        )}
                      </div>
                    </TableCell>
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

export default ActsPage;
