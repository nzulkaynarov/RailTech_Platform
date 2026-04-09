import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { CalendarDays, Calendar } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { PageShell } from './shared/PageShell';

export function ProductionSchedulePage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Production orders are loaded from the backend API
  // TODO: Replace with useEffect + API call when production endpoints are ready
  const orders: { name: string; progress: number; deadline: string; status: string }[] = [];

  return (
    <PageShell
      title={t('pages.productionSchedule.title')}
      description={t('pages.productionSchedule.description')}
      icon={<CalendarDays className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionSchedule.stats.activeOrders'), value: String(ps?.production_schedule?.active_orders ?? '0') },
        { label: t('pages.productionSchedule.stats.completed'), value: String(ps?.production_schedule?.completed ?? '0') },
        { label: t('pages.productionSchedule.stats.delayed'), value: String(ps?.production_schedule?.delayed ?? '0') },
        { label: t('pages.productionSchedule.stats.nextWeek'), value: String(ps?.production_schedule?.next_week ?? '0') },
      ]}
    >
      <div className="space-y-4">
        {orders.map((order, idx) => (
          <Card key={idx}>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium">{order.name}</p>
                  <p className="text-xs text-muted-foreground mt-1 flex items-center gap-2">
                    <Calendar className="h-3 w-3" />
                    {t('pages.productionSchedule.deadline')}: {order.deadline}
                  </p>
                </div>
                <Badge>{order.status}</Badge>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{t('pages.productionSchedule.progress')}</span>
                  <span className="font-medium tabular-nums">{order.progress}%</span>
                </div>
                <Progress value={order.progress} className="h-2" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

export default ProductionSchedulePage;
