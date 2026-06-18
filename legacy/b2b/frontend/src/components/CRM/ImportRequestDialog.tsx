import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles, AlertTriangle, Download } from 'lucide-react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ExcelUpload } from '@/components/Sourcing/ExcelUpload';
import { downloadFile } from '@/lib/download';

/**
 * Upload-a-file flow embedded INTO the request page, so the buyer never has to
 * leave to the separate import screen. AI (any file) or template (xlsx, no AI),
 * with a concise external-AI disclaimer (full text behind "details"). On
 * completion the deal query is invalidated so the request grid refreshes.
 */
export function ImportRequestDialog({
  dealId,
  open,
  onOpenChange,
}: {
  dealId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [useAI, setUseAI] = useState(true);
  const [showFull, setShowFull] = useState(false);

  const downloadTemplate = async () => {
    try {
      await downloadFile('catalog/products/export-template/', 'RailTech_Import_Template.xlsx');
    } catch {
      toast.error(t('pages.sourcingImport.templateError'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] gap-4 overflow-y-auto overflow-x-hidden sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('aiImport.dialogTitle')}</DialogTitle>
          <DialogDescription>{useAI ? t('aiImport.optionAiHint') : t('aiImport.optionTemplateHint')}</DialogDescription>
        </DialogHeader>

        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={useAI ? 'ai' : 'tpl'}
          onValueChange={(value) => { if (value) setUseAI(value === 'ai'); }}
          className="grid w-full grid-cols-2"
        >
          <ToggleGroupItem value="ai" className="w-full gap-1.5 text-xs">
            <Sparkles className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t('aiImport.optionAi')}
          </ToggleGroupItem>
          <ToggleGroupItem value="tpl" className="w-full text-xs">{t('aiImport.optionTemplate')}</ToggleGroupItem>
        </ToggleGroup>

        {useAI ? (
          <Alert>
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            <AlertDescription>
              {t('aiImport.disclaimerShort')}{' '}
              <Button variant="link" className="h-auto p-0 text-xs underline" onClick={() => setShowFull((v) => !v)}>
                {showFull ? t('aiImport.less') : t('aiImport.more')}
              </Button>
              {showFull && <span className="mt-1 block text-muted-foreground">{t('aiImport.disclaimer')}</span>}
            </AlertDescription>
          </Alert>
        ) : (
          <Button variant="outline" size="sm" className="w-fit gap-1.5" onClick={downloadTemplate}>
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            {t('pages.sourcingImport.downloadTemplate')}
          </Button>
        )}

        <ExcelUpload
          key={useAI ? 'ai' : 'tpl'}
          dealId={dealId}
          useAI={useAI}
          onUploadSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['deals'] });
            toast.success(t('pages.sourcingImport.importSuccess'));
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
