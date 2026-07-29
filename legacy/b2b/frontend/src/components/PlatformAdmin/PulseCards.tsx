import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { CreditCard, Handshake, TrendingUp } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { useCurrencyStore } from '@/store/currencyStore';
import type { AdminPulseResponse } from '@/api/adminApi';
import { PulseChart, type PulseTone } from './PulseChart';

// Классы перечислены ЛИТЕРАЛАМИ: Tailwind извлекает их статическим сканированием исходника,
// поэтому шаблонная строка вида `text-${tone}` скомпилировалась бы в ничто и иконка потеряла
// бы цвет. Карта дороже на вид, но она — единственная работающая форма.
const TONE_TEXT: Record<PulseTone, string> = {
  primary: 'text-primary',
  success: 'text-success',
  info: 'text-info',
  warning: 'text-warning',
};

function formatInt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

/** Одна KPI-плитка пульса: иконка, заголовок, крупное число и спарклайн под ним. */
function PulseCard({
  icon: Icon,
  tone,
  label,
  value,
  isLoading,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: PulseTone;
  label: string;
  value: string;
  isLoading: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2">
          <Icon className={cn('h-3.5 w-3.5', TONE_TEXT[tone])} />
          <span className="text-xs font-medium">{label}</span>
        </div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">
          {isLoading ? <Skeleton className="h-7 w-16" /> : value}
        </div>
        <div className="mt-2">{children}</div>
      </CardContent>
    </Card>
  );
}

/**
 * Верхний ряд дашборда оператора: новые компании, новые сделки, сумма подписанных КП и MRR.
 * Три плитки несут спарклайн за период, четвёртая (MRR) — счётчик активных подписок.
 */
export function PulseCards({ pulse, isLoading }: { pulse: AdminPulseResponse | undefined; isLoading: boolean }) {
  const { t } = useTranslation();
  const format = useCurrencyStore((s) => s.format);

  const companiesTotal = useMemo(
    () => (pulse?.companies ?? []).reduce((s, d) => s + d.count, 0),
    [pulse],
  );
  const dealsTotal = useMemo(
    () => (pulse?.deals ?? []).reduce((s, d) => s + d.count, 0),
    [pulse],
  );
  const signedValue = useMemo(
    () => (pulse?.quotes_signed_value ?? []).reduce((s, d) => s + Number(d.value || 0), 0),
    [pulse],
  );

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
      <PulseCard
        icon={TrendingUp}
        tone="primary"
        label={t('platformAdmin.pulse.newCompanies')}
        value={formatInt(companiesTotal)}
        isLoading={isLoading}
      >
        <PulseChart
          series={pulse?.companies ?? []}
          tone="primary"
          ariaLabel={t('platformAdmin.pulse.newCompanies')}
        />
      </PulseCard>

      <PulseCard
        icon={Handshake}
        tone="success"
        label={t('platformAdmin.pulse.newDeals')}
        value={formatInt(dealsTotal)}
        isLoading={isLoading}
      >
        <PulseChart
          series={pulse?.deals ?? []}
          tone="success"
          ariaLabel={t('platformAdmin.pulse.newDeals')}
        />
      </PulseCard>

      <PulseCard
        icon={TrendingUp}
        tone="info"
        label={t('platformAdmin.pulse.signedValue')}
        value={format(signedValue)}
        isLoading={isLoading}
      >
        <PulseChart
          series={pulse?.quotes_signed_value ?? []}
          tone="info"
          valueKey="value"
          valueFormatter={format}
          ariaLabel={t('platformAdmin.pulse.signedValue')}
        />
      </PulseCard>

      <PulseCard
        icon={CreditCard}
        tone="warning"
        label={t('platformAdmin.pulse.mrr')}
        value={format(Number(pulse?.mrr ?? 0))}
        isLoading={isLoading}
      >
        <div className="text-xs text-muted-foreground">
          {t('platformAdmin.pulse.activeSubscriptions', { count: pulse?.active_subscriptions ?? 0 })}
        </div>
      </PulseCard>
    </div>
  );
}
