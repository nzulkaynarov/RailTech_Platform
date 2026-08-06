import { Card, CardContent } from '@/components/ui/card';

import { OfferSection } from '../admin-catalog/OfferSection';
import type { ProductFormState } from '../admin-catalog/useProductForm';
import { SECTION_IDS } from './anchors';

/**
 * Секция «Коммерция» — предложение продавца (цена/валюта/наличие/сроки/MOQ/окно
 * действия/активность). Содержимое целиком переиспользует `OfferSection` шторки:
 * одна запись прайса — один компонент, страница лишь даёт ей карточку и якорь.
 */
export function CommerceSection({ form }: { form: ProductFormState }) {
  return (
    <section id={SECTION_IDS.commerce} className="scroll-mt-20">
      <Card>
        <CardContent className="space-y-4 p-5">
          <OfferSection form={form} />
        </CardContent>
      </Card>
    </section>
  );
}
