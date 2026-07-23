import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, Loader2 } from 'lucide-react';

import { usePreviewTemplate } from '@/hooks/useDocuments';
import type { DocumentTemplate } from '@/api/documentsApi';
import { DocumentLetterheadPreview } from '@/components/Documents/DocumentLetterheadPreview';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

/**
 * D3: preview a PLATFORM SAMPLE template as the full branded document WITHOUT copying it first
 * («Скопировать к себе» was a blind pick before). Renders the sample's body through the same
 * server preview endpoint the editor uses (letterhead + resolved placeholders + footer), so the
 * seller sees exactly what they'd start from.
 */
export function SampleTemplatePreviewDialog({ template }: { template: DocumentTemplate }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const previewMut = usePreviewTemplate();

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) previewMut.mutate(template.body_html ?? '');
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <Eye className="size-3.5" />
          {t('docTemplatesSettings.previewSample')}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{template.name}</DialogTitle>
        </DialogHeader>
        {previewMut.isPending && (
          <div className="flex justify-center p-10" role="status">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
            <span className="sr-only">{t('common.loading')}</span>
          </div>
        )}
        {previewMut.data && (
          <DocumentLetterheadPreview
            brand={previewMut.data.brand}
            bodyHtml={previewMut.data.rendered_html}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

export default SampleTemplatePreviewDialog;
