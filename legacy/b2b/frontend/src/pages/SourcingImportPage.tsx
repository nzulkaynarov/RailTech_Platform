import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileSpreadsheet, Check, Download } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { useDeals } from '@/hooks/useCRM';
import { ExcelUpload } from '@/components/Sourcing/ExcelUpload';
import { PageShell } from './shared/PageShell';
import { downloadFile } from '@/lib/download';
import { useFlowStore } from '@/store/flowStore';
import type { Deal } from '@/api/crmApi';

/**
 * Parse the current URL hash for `deal=<id>` so that CreateDealDialog can
 * deep-link straight into the import step with the new deal preselected.
 */
function readDealIdFromHash(): string {
  if (typeof window === 'undefined') return '';
  const raw = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash;
  const queryString = raw.includes('?') ? raw.slice(raw.indexOf('?') + 1) : '';
  if (!queryString) return '';
  const params = new URLSearchParams(queryString);
  return params.get('deal') || '';
}

export function SourcingImportPage() {
  const { t } = useTranslation();
  const { data: deals } = useDeals();
  const [selectedDealId, setSelectedDealId] = useState<string>(() => readDealIdFromHash());
  const [importDone, setImportDone] = useState(false);
  const setActiveDeal = useFlowStore((s) => s.setActiveDealId);

  const importableDeals = useMemo(() =>
    (deals ?? []).filter((d: Deal) =>
      ['DRAFT', 'SOURCING', 'CALCULATING'].includes(d.stage_code ?? '')
    ), [deals]);

  // If the hash changes (user uses browser back/forward) keep the selection in sync.
  useEffect(() => {
    const onHashChange = () => {
      const hashDeal = readDealIdFromHash();
      if (hashDeal) {
        setSelectedDealId(hashDeal);
        setImportDone(false);
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Once deals load, if a hash-provided id is missing from the list (happens
  // briefly right after creating a new deal), keep the value — SelectItem
  // still renders correctly because Select just compares strings.

  async function downloadTemplate() {
    // Must go through the authenticated client (blob) — opening the raw URL has no
    // Authorization header, so on prod it 401s ("Учетные данные не предоставлены").
    try {
      await downloadFile('catalog/products/export-template/', 'RailTech_Import_Template.xlsx');
    } catch {
      toast.error(t('pages.sourcingImport.templateError'));
    }
  }

  function openImportedDeal() {
    // After import, the line items are added to this deal's КП — take the user
    // straight to the request so they SEE the result (no more dead-end).
    setActiveDeal(Number(selectedDealId));
    window.location.hash = 'request-detail';
  }

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
            <Select
              value={selectedDealId || undefined}
              onValueChange={(v) => { setSelectedDealId(v); setImportDone(false); }}
            >
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
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold flex items-center gap-2">
                  <Badge variant="outline" className="text-xs">2</Badge>
                  {t('pages.sourcingImport.uploadFile')}
                </h3>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="gap-1.5 text-xs"
                  onClick={downloadTemplate}
                >
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('pages.sourcingImport.downloadTemplate')}
                </Button>
              </div>
              <ExcelUpload
                dealId={Number(selectedDealId)}
                onUploadSuccess={() => setImportDone(true)}
              />
            </CardContent>
          </Card>
        )}

        {/* Step 3: Success + the next step (open the request to see the imported items) */}
        {importDone && (
          <Card className="border-success/30 bg-success/5">
            <CardContent className="p-5 flex items-center gap-3">
              <Check className="h-5 w-5 text-success shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{t('pages.sourcingImport.importSuccess')}</p>
                <p className="text-xs text-muted-foreground">{t('pages.sourcingImport.importSuccessHint')}</p>
              </div>
              <Button size="sm" onClick={openImportedDeal} className="shrink-0">
                {t('pages.sourcingImport.openDeal')}
              </Button>
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
