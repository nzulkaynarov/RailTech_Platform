import { useTranslation } from 'react-i18next';
import { Download, Loader2 } from 'lucide-react';

import { RowMenuAction } from '@/components/list/RowMenu';
import { Button } from '@/components/ui/button';
import { useDocumentDownload } from '@/hooks/useDocumentDownload';

/** Пункт меню строки «Скачать» (`RowMenu`): тот же запрос, что у кнопки; «готовится» — в подсказке-тосте. */
export function DocumentMenuItem({ documentId, fileName, text }: { documentId: number; fileName: string; text?: string }) {
  const { t } = useTranslation();
  const { download, busy } = useDocumentDownload({ documentId, fileName });
  return (
    <RowMenuAction icon={Download} disabled={busy} onSelect={() => void download()}>
      {text ?? t('documents.download')}
    </RowMenuAction>
  );
}

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
  catalogItemId,
}: {
  documentId: number;
  fileName: string;
  /** Что скачиваем — для `aria-label` («Скачать: Счёт № S-…»). */
  label: string;
  variant?: 'outline' | 'ghost' | 'default';
  /** Подпись кнопки вместо «Скачать» (например, «Скан»). */
  text?: string;
  /** Документ карточки каталога (`GET /catalog/{id}/documents/{doc_id}/file`): `documentId` — id документа, а не выпущенного. */
  catalogItemId?: number;
}) {
  const { t } = useTranslation();
  const { state, busy, download } = useDocumentDownload({ documentId, fileName, catalogItemId });
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
        {busy ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
        {state === 'pending' ? t('documents.preparing') : (text ?? t('documents.download'))}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'pending' ? t('documents.preparingLive', { name: label }) : ''}
      </span>
    </>
  );
}
