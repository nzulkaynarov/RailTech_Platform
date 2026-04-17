import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileSpreadsheet, Check } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { useDeals } from '@/hooks/useCRM';
import { ExcelUpload } from '@/components/Sourcing/ExcelUpload';
import { PageShell } from './shared/PageShell';
import type { Deal } from '@/api/crmApi';

export function SourcingImportPage() {
  const { t } = useTranslation();
  const { data: deals } = useDeals();
  const [selectedDealId, setSelectedDealId] = useState<string>('');
  const [importDone, setImportDone] = useState(false);

  // Only show deals in stages where import makes sense
  const importableDeals = useMemo(() =>
    (deals ?? []).filter((d: Deal) =>
      ['DRAFT', 'SOURCING', 'CALCULATING'].includes(d.stage_code ?? '')
    ), [deals]);

  return (
    <PageShell
      title={t('pages.sourcingImport.title')}
      description={t('pages.sourcingImport.description')}
      icon={<Upload className="h-5 w-5" />}
    >
      <div className="space-y-6 max-w-2xl">
        {/* Step 1: Select deal */}
        <Card>
          <CardContent className="p-5 space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Badge variant="outline" className="text-xs">1</Badge>
              {t('pages.sourcingImport.selectDeal')}
            </h3>
            <Select value={selectedDealId} onValueChange={(v) => { setSelectedDealId(v); setImportDone(false); }}>
              <SelectTrigger>
                <SelectValue placeholder={t('pages.sourcingImport.selectDealPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {importableDeals.map((deal) => (
                  <SelectItem key={deal.id} value={String(deal.id)}>
                    {deal.title || `#${deal.id}`} — {deal.company_name || deal.client_name || ''}
                    {deal.stage_name && ` (${deal.stage_name})`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {importableDeals.length === 0 && (
              <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.noDeals')}</p>
            )}
          </CardContent>
        </Card>

        {/* Step 2: Upload file */}
        {selectedDealId && (
          <Card>
            <CardContent className="p-5 space-y-3">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <Badge variant="outline" className="text-xs">2</Badge>
                {t('pages.sourcingImport.uploadFile')}
              </h3>
              <ExcelUpload
                dealId={Number(selectedDealId)}
                onUploadSuccess={() => setImportDone(true)}
              />
            </CardContent>
          </Card>
        )}

        {/* Step 3: Success */}
        {importDone && (
          <Card className="border-success/30 bg-success/5">
            <CardContent className="p-5 flex items-center gap-3">
              <Check className="h-5 w-5 text-success shrink-0" />
              <div>
                <p className="text-sm font-semibold">{t('pages.sourcingImport.importSuccess')}</p>
                <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.importSuccessHint')}</p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Hints */}
        <Card className="border-dashed">
          <CardContent className="p-5">
            <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
              {t('pages.sourcingImport.requirements')}
            </h3>
            <ul className="space-y-1 text-xs text-muted-foreground">
              <li>• {t('pages.sourcingImport.req1')}</li>
              <li>• {t('pages.sourcingImport.req2')}</li>
              <li>• {t('pages.sourcingImport.req3')}</li>
              <li>• {t('pages.sourcingImport.req4')}</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

export default SourcingImportPage;
