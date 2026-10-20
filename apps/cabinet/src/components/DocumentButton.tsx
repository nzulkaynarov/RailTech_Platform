import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Loader2 } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import { Button } from '@/components/ui/button';
import { DocumentNotReadyError, downloadDocument } from '@/lib/download';

/**
 * «Скачать» документ из ERP: `GET /documents/{id}/file`. Пока PDF рендерится (202), кнопка говорит
 * «Документ готовится…» и повторяет запрос через `Retry-After`; не дождались — понятный тост с
 * предложением повторить позже. Подпись кнопки включает имя документа (`aria-label`) — в списке
 * из нескольких «Скачать» каждая кнопка различима для диктора.
 */
export function DocumentButton({
  documentId,
  fileName,
  label,
  variant = 'outline',
  text,
}: {
  documentId: number;
  fileName: string;
  /** Что скачиваем — для `aria-label` («Скачать: Счёт № S-…»). */
  label: string;
  variant?: 'outline' | 'ghost' | 'default';
  /** Подпись кнопки вместо «Скачать» (например, «Скан»). */
  text?: string;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<'idle' | 'loading' | 'pending'>('idle');

  const download = async () => {
    setState('loading');
    try {
      await downloadDocument(documentId, fileName, { onPending: () => setState('pending') });
    } catch (error) {
      if (error instanceof DocumentNotReadyError) toast.info(t('documents.stillPreparing'));
      else toast.error(t(apiErrorKey(error)));
    } finally {
      setState('idle');
    }
  };

  const busy = state !== 'idle';
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant={variant}
        onClick={() => void download()}
        disabled={busy}
        aria-label={t('documents.downloadNamed', { name: label })}
      >
        {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
        {state === 'pending' ? t('documents.preparing') : (text ?? t('documents.download'))}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'pending' ? t('documents.preparingLive', { name: label }) : ''}
      </span>
    </>
  );
}
