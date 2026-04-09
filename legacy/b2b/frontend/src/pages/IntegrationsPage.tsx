import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Plug } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { PageShell } from './shared/PageShell';

export function IntegrationsPage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  // Integrations are loaded from the backend API
  // TODO: Replace with useEffect + API call when integrations endpoint is ready
  const integrations: { name: string; description: string; status: string; lastSync: string; records: string }[] = [];

  return (
    <PageShell
      title={t('pages.integrations.title')}
      description={t('pages.integrations.description')}
      icon={<Plug className="h-5 w-5" />}
      stats={[
        { label: t('pages.integrations.stats.connected'), value: String(ps?.integrations?.connected ?? '0') },
        { label: t('pages.integrations.stats.pending'), value: String(ps?.integrations?.pending ?? '0') },
        { label: t('pages.integrations.stats.availableApis'), value: String(ps?.integrations?.available_apis ?? '0') },
        { label: t('pages.integrations.stats.syncedRecords'), value: String(ps?.integrations?.synced_records ?? '0') },
      ]}
      actions={[{ label: t('pages.integrations.apiDocs'), variant: 'outline' }, { label: t('pages.integrations.addIntegration') }]}
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {integrations.map((int, idx) => (
          <Card key={idx} className="border">
            <CardContent className="p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg flex items-center justify-center bg-muted">
                    <Plug className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{int.name}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">{int.description}</p>
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between mb-3">
                <Badge variant={
                  int.status === 'connected' ? 'default' :
                  int.status === 'pending' ? 'secondary' :
                  'outline'
                }>
                  {int.status === 'connected' ? t('pages.integrations.statusLabel.connected') : int.status === 'pending' ? t('pages.integrations.statusLabel.configuring') : t('pages.integrations.statusLabel.disconnected')}
                </Badge>
                {int.status === 'connected' && (
                  <span className="text-xs text-muted-foreground">{int.lastSync}</span>
                )}
              </div>
              {int.status === 'connected' && (
                <div className="text-xs text-muted-foreground mb-3">
                  {t('pages.integrations.processed')}: <span className="font-medium text-foreground">{int.records}</span>
                </div>
              )}
              <Button size="sm" variant={int.status === 'connected' ? 'outline' : 'default'} className="w-full">
                {int.status === 'connected' ? t('pages.integrations.settings') : int.status === 'pending' ? t('pages.integrations.finishSetup') : t('pages.integrations.connect')}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

export default IntegrationsPage;
