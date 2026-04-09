import { useTranslation } from 'react-i18next';
import { Factory } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { PageShell } from './shared/PageShell';
import { DemoRequestCard } from './shared/DemoRequestCard';

export function ProductionOrdersPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.productionOrders.title')}
      description={t('pages.productionOrders.description')}
      icon={<Factory className="h-5 w-5" />}
      stats={[
        { label: t('pages.productionOrders.stats.active'), value: String(ps?.production?.active ?? '0') },
        { label: t('pages.productionOrders.stats.awaitingResponse'), value: String(ps?.production?.awaiting_response ?? '0') },
        { label: t('pages.productionOrders.stats.responded'), value: String(ps?.production?.responded ?? '0') },
        { label: t('pages.productionOrders.stats.overdue'), value: String(ps?.production?.overdue ?? '0') },
      ]}
    >
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">{t('pages.productionOrders.partnerRequests')}</p>
        <DemoRequestCard onOpen={() => onNavigate?.('request-detail')} />
      </div>
    </PageShell>
  );
}

export default ProductionOrdersPage;
