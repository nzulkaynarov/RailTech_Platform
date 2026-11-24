import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { apiErrorKey } from '@/api/errors';
import { DocumentNotReadyError, downloadCatalogDocument, downloadDocument } from '@/lib/download';
import { toast } from '@/lib/toast';

/**
 * Скачивания в работе (ключ — документ): пока файл готовится, повторный запрос на тот же документ не уходит —
 * ни из кнопки, ни из пункта меню строки. Хранится вне компонента: меню закрывается, а скачивание идёт дальше.
 */
const inFlight = new Set<string>();

/** Скачивание документа: состояние и обработчик — общие для кнопки и пункта меню строки. */
export function useDocumentDownload({
  documentId,
  fileName,
  catalogItemId,
  toastOnPending = false,
}: {
  documentId: number;
  fileName: string;
  catalogItemId?: number;
  /** Пункт меню закрывается и не может показать «готовится» сам: сообщение — тостом, один раз за скачивание. */
  toastOnPending?: boolean;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<'idle' | 'loading' | 'pending'>('idle');

  const key = catalogItemId !== undefined ? `catalog:${catalogItemId}:${documentId}` : `document:${documentId}`;

  const download = async () => {
    if (inFlight.has(key)) return;
    inFlight.add(key);
    setState('loading');
    try {
      if (catalogItemId !== undefined) await downloadCatalogDocument(catalogItemId, documentId, fileName);
      else {
        let announced = false;
        await downloadDocument(documentId, fileName, {
          onPending: () => {
            setState('pending');
            if (toastOnPending && !announced) toast.info(t('documents.preparing'));
            announced = true;
          },
        });
      }
    } catch (error) {
      if (error instanceof DocumentNotReadyError) toast.info(t('documents.stillPreparing'));
      else toast.error(t(apiErrorKey(error)));
    } finally {
      inFlight.delete(key);
      setState('idle');
    }
  };
  return { state, busy: state !== 'idle', download };
}
