import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Truck, FileText, CheckCircle2, MapPin, ChevronRight } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { PageShell } from './shared/PageShell';

export function LogisticsPage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Shipments are loaded from the backend API
  // TODO: Replace with useEffect + API call when logistics endpoint is ready
  const shipments: { number: string; route: string; status: string; etd: string; eta: string; carrier: string }[] = [];

  const statusBadges: Record<string, 'default' | 'secondary' | 'outline'> = {
    'in_transit': 'secondary',
    'customs': 'outline',
    'delivered': 'default',
  };

  return (
    <PageShell
      title={t('pages.logistics.title')}
      description={t('pages.logistics.description')}
      icon={<Truck className="h-5 w-5" />}
      stats={[
        { label: t('pages.logistics.stats.inTransit'), value: String(ps?.logistics?.in_transit ?? '0') },
        { label: t('pages.logistics.stats.customs'), value: String(ps?.logistics?.customs ?? '0') },
        { label: t('pages.logistics.stats.delivered'), value: String(ps?.logistics?.delivered ?? '0') },
        { label: t('pages.logistics.stats.delays'), value: String(ps?.logistics?.delays ?? '0') },
      ]}
      actions={[{ label: t('pages.logistics.newShipment') }]}
    >
      <div className="space-y-3">
        {shipments.map((ship, idx) => (
          <Card key={idx}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <p className="font-semibold">{ship.number}</p>
                    <Badge variant={statusBadges[ship.status]} className="gap-1">
                      {ship.status === 'in_transit' && <><Truck className="h-3 w-3" /> {t('pages.logistics.statusLabel.inTransit')}</>}
                      {ship.status === 'customs' && <><FileText className="h-3 w-3" /> {t('pages.logistics.statusLabel.customs')}</>}
                      {ship.status === 'delivered' && <><CheckCircle2 className="h-3 w-3" /> {t('pages.logistics.statusLabel.delivered')}</>}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mb-3 flex items-center gap-2">
                    <MapPin className="h-4 w-4" />
                    {ship.route}
                  </p>
                  <div className="grid grid-cols-3 gap-4 text-xs">
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.departure')}</p>
                      <p className="font-medium">{ship.etd}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.arrival')}</p>
                      <p className="font-medium">{ship.eta}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">{t('pages.logistics.carrier')}</p>
                      <p className="font-medium">{ship.carrier}</p>
                    </div>
                  </div>
                </div>
                <Button variant="ghost" size="sm">
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

export default LogisticsPage;
