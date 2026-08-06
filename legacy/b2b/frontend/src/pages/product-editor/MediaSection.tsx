import { useTranslation } from 'react-i18next';
import { ImagePlus } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { ProductMediaSection } from '../admin-catalog/ProductMediaSection';
import { SECTION_IDS } from './anchors';

/**
 * Секция «Медиа» — с ПЕРВОГО шага (D17): раньше «фото после сохранения» было двухшаговым
 * тупиком (сохранил → шторка закрылась → ищи карточку заново). Теперь первый «Сохранить
 * черновик» создаёт id, страница остаётся на месте и загрузка открывается здесь же.
 */
export function MediaSection({ productId }: { productId: number | null }) {
  const { t } = useTranslation();

  return (
    <section id={SECTION_IDS.media} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productEditor.sections.media')}</CardTitle>
        </CardHeader>
        <CardContent>
          {productId ? (
            <ProductMediaSection productId={productId} />
          ) : (
            <div className="flex items-center gap-3 rounded-md border border-dashed p-4">
              <ImagePlus className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">{t('productEditor.mediaNeedsDraft')}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
