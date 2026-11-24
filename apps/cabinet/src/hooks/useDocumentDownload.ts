import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { apiErrorKey } from '@/api/errors';
import { DocumentNotReadyError, downloadCatalogDocument, downloadDocument } from '@/lib/download';
import { toast } from '@/lib/toast';

/** Скачивание документа: состояние и обработчик — общие для кнопки и пункта меню строки. */
export function useDocumentDownload({
  documentId,
  fileName,
  catalogItemId,
}: {
  documentId: number;
  fileName: string;
  catalogItemId?: number;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<'idle' | 'loading' | 'pending'>('idle');

  const download = async () => {
    setState('loading');
    try {
      if (catalogItemId !== undefined) await downloadCatalogDocument(catalogItemId, documentId, fileName);
      else await downloadDocument(documentId, fileName, { onPending: () => setState('pending') });
    } catch (error) {
      if (error instanceof DocumentNotReadyError) toast.info(t('documents.stillPreparing'));
      else toast.error(t(apiErrorKey(error)));
    } finally {
      setState('idle');
    }
  };
  return { state, busy: state !== 'idle', download };
}
