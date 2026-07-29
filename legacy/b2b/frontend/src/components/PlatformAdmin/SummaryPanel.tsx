import { useTranslation } from 'react-i18next';
import { Building2, ClipboardList, CreditCard, Handshake, Receipt, ShieldCheck, Users } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { PlatformDashboard } from '@/api/dashboardApi';

/** Строка сводки: кликабельный переход в соответствующий раздел, подсветка при непустом счётчике. */
function SummaryRow({
  icon: Icon,
  label,
  value,
  highlight,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value?: number;
  highlight?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent',
        highlight && 'bg-warning/10',
      )}
    >
      <span className="flex items-center gap-2 text-xs">
        <Icon className={cn('h-3.5 w-3.5 text-muted-foreground', highlight && 'text-warning')} />
        {label}
      </span>
      <span className={cn('text-xs font-semibold tabular-nums', highlight && 'text-warning')}>
        {value == null ? '—' : value.toLocaleString()}
      </span>
    </button>
  );
}

/**
 * Правая колонка дашборда: счётчики платформы и то, что требует внимания.
 * Каждая строка — вход в свой раздел, поэтому сводка работает как навигация, а не только табло.
 */
export function SummaryPanel({
  dashboard,
  onNavigate,
}: {
  dashboard: PlatformDashboard | undefined;
  onNavigate: (target: string) => void;
}) {
  const { t } = useTranslation();
  const attention = dashboard?.attention;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t('platformAdmin.summary.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        <SummaryRow
          icon={Users}
          label={t('shell.users')}
          value={dashboard?.users.total}
          onClick={() => onNavigate('admin-users')}
        />
        <SummaryRow
          icon={Building2}
          label={t('shell.companies')}
          value={dashboard?.companies.total}
          onClick={() => onNavigate('admin-companies')}
        />
        <SummaryRow
          icon={Handshake}
          label={t('shell.adminDeals')}
          value={dashboard?.deals.total}
          onClick={() => onNavigate('admin-deals')}
        />
        <SummaryRow
          icon={ShieldCheck}
          label={t('shell.kyc')}
          value={attention?.kyc ?? 0}
          highlight={Boolean(attention?.kyc)}
          onClick={() => onNavigate('admin-kyc')}
        />
        <SummaryRow
          icon={ClipboardList}
          label={t('shell.roleApplications')}
          value={attention?.role_applications ?? 0}
          highlight={Boolean(attention?.role_applications)}
          onClick={() => onNavigate('admin-role-apps')}
        />
        <SummaryRow
          icon={CreditCard}
          label={t('platformAdmin.summary.subsExpiring')}
          value={(attention?.subscriptions_expiring_7d ?? 0) + (attention?.subscriptions_past_due ?? 0)}
          highlight={Boolean(attention?.subscriptions_past_due)}
          onClick={() => onNavigate('admin-subscriptions')}
        />
        <SummaryRow
          icon={Receipt}
          label={t('platformAdmin.summary.overdueInvoices')}
          value={attention?.overdue_invoices ?? 0}
          highlight={Boolean(attention?.overdue_invoices)}
          onClick={() => onNavigate('admin-deals')}
        />
      </CardContent>
    </Card>
  );
}
