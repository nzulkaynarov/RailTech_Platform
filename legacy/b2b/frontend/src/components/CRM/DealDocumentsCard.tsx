import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSignature, FilePlus, Inbox } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { DocumentCreateWizard } from '@/components/Documents/DocumentCreateWizard';
import { useGeneratedDocuments } from '@/hooks/useDocuments';

/**
 * F2 II-3/II-4 — «Документы сделки» block on the deal card.
 *
 * Benchmark (Bitrix24 / Odoo deal cards): documents attached to a deal are listed IN the card,
 * with a one-click «create» that pre-binds the new document to the deal. This mirrors that: the
 * list is scoped to `?deal=<id>` and the «Создать документ» button opens the shared wizard with
 * `defaultDealId` so the deal context is fixed. Received (counterparty) documents show a «Получен»
 * badge and are read-only (download / share only) — the same read-only contract as the registry.
 */
export function DealDocumentsCard({ dealId, isViewer, viewerTip }: {
  dealId: number;
  isViewer: boolean;
  viewerTip: string;
}) {
  const { t } = useTranslation();
  const [createOpen, setCreateOpen] = useState(false);
  const { data: documents, isLoading } = useGeneratedDocuments({ deal: dealId });
  const list = documents ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileSignature className="h-4 w-4" aria-hidden="true" />
          {t('dealDocuments.title')}
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setCreateOpen(true)}
          disabled={isViewer}
          title={isViewer ? viewerTip : undefined}
        >
          <FilePlus className="mr-1.5 h-4 w-4" aria-hidden="true" />
          {t('dealDocuments.create')}
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="py-4 text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-6 text-center">
            <FileSignature className="h-8 w-8 opacity-20" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">{t('dealDocuments.empty')}</p>
            <p className="text-xs text-muted-foreground">{t('dealDocuments.emptyHint')}</p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {list.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 truncate text-sm font-medium">
                    {doc.number}
                    {doc.is_owned === false && (
                      <Badge variant="outline" className="gap-1">
                        <Inbox className="size-3" aria-hidden="true" />
                        {t('otherDocumentsPage.received')}
                      </Badge>
                    )}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {doc.title} · {t(`otherDocumentsPage.status.${doc.status_code}`)}
                  </p>
                </div>
                {/* По статусу, а не по наличию файла: сервер дорисует PDF по запросу (ARCH-03). */}
                {doc.status_code === 'ISSUED' && (
                  <DocumentActions
                    request={() => ({ path: `crm/generated-documents/${doc.id}/download-pdf/` })}
                    filenameBase={`RailTech_Document_${doc.id}`}
                    variant="ghost"
                    iconOnly
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <DocumentCreateWizard open={createOpen} onOpenChange={setCreateOpen} defaultDealId={dealId} />
    </Card>
  );
}

export default DealDocumentsCard;
