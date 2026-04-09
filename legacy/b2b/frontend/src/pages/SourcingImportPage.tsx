import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Upload } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function SourcingImportPage() {
  const { t } = useTranslation();
  return (
    <PageShell
      title={t('pages.sourcingImport.title')}
      description={t('pages.sourcingImport.description')}
      icon={<Upload className="h-5 w-5" />}
      actions={[{ label: t('pages.sourcingImport.uploadFile') }]}
    >
      <div className="space-y-6">
        {/* Upload Area */}
        <Card className="border-2 border-dashed border-muted-foreground/25 bg-muted/50">
          <CardContent className="flex flex-col items-center justify-center gap-3 py-12">
            <Upload className="h-10 w-10 text-muted-foreground/50" />
            <div className="text-center">
              <p className="font-medium">{t('pages.sourcingImport.dragDrop')}</p>
              <p className="text-sm text-muted-foreground">{t('pages.sourcingImport.orClick')}</p>
            </div>
          </CardContent>
        </Card>

        {/* Simulated Upload Result */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('pages.sourcingImport.lastImport')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">{t('pages.sourcingImport.sampleFileName')}</p>
                <p className="text-sm text-muted-foreground">{t('pages.sourcingImport.uploadedAgo')}</p>
              </div>
              <Badge>{t('pages.sourcingImport.status.completed')}</Badge>
            </div>

            {/* Import results will be displayed here after actual file upload */}
            <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
              <Upload className="h-8 w-8 mb-3 opacity-50" />
              <p className="text-sm font-medium">{t('pages.sourcingImport.noImportsYet')}</p>
              <p className="text-xs mt-1">{t('pages.sourcingImport.uploadToSee')}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

export default SourcingImportPage;
