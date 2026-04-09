import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Shield, Check, Pause, ChevronRight } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { useUsers } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { User } from '@/api/accountsApi';

export function AdminUsersPage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  const { data: users, isLoading } = useUsers();

  return (
    <PageShell
      title={t('pages.adminUsers.title')}
      description={t('pages.adminUsers.description')}
      icon={<Shield className="h-5 w-5" />}
      stats={[
        { label: t('pages.adminUsers.stats.total'), value: String(ps?.admin_users?.total ?? '—') },
        { label: t('pages.adminUsers.stats.admins'), value: String(ps?.admin_users?.admins ?? '—') },
        { label: t('pages.adminUsers.stats.managers'), value: String(ps?.admin_users?.managers ?? '—') },
        { label: t('pages.adminUsers.stats.employees'), value: String(ps?.admin_users?.employees ?? '—') },
      ]}
      actions={[{ label: t('pages.adminUsers.inviteUser') }]}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !users?.length ? (
            <EmptyState icon={<Shield className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('pages.adminUsers.table.name')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.email')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.role')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.status')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.lastLogin')}</TableHead>
                  <TableHead className="text-center">{t('pages.adminUsers.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user: User) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">{user.first_name} {user.last_name}</TableCell>
                    <TableCell className="text-muted-foreground">{user.email}</TableCell>
                    <TableCell>
                      <Badge variant={
                        user.role_code === 'ADMIN' ? 'default' :
                        user.role_code === 'MANAGER' ? 'secondary' :
                        'outline'
                      }>
                        {user.role_data?.name ?? user.role_code ?? '—'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? 'default' : 'secondary'} className="gap-1">
                        {user.is_active
                          ? <><Check className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.active')}</>
                          : <><Pause className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.inactive')}</>}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">{user.last_login ? new Date(user.last_login).toLocaleDateString() : '—'}</TableCell>
                    <TableCell className="text-center">
                      <Button variant="ghost" size="sm" className="h-8 w-8">
                        <ChevronRight className="h-4 w-4" />
                      </Button>
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

export default AdminUsersPage;
