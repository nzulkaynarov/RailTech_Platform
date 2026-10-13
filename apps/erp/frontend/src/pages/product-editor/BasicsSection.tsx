import { useTranslation } from 'react-i18next';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ManufacturerField } from '@/components/Shared/ManufacturerField';

import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { SECTION_IDS } from './anchors';

/**
 * Секция «Основное»: идентичность товара — имя, описание, бренд, артикул, ГОСТ,
 * единица измерения. Подписи полей — те же ключи `adminCatalog.fields.*`, что и в
 * операторской шторке: одна форма — один словарь.
 */
export function BasicsSection({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const { draft, units, update } = form;

  return (
    <section id={SECTION_IDS.basics} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productEditor.sections.basics')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="pe-name">
              {t('adminCatalog.fields.name')}
              <span className="ml-1 text-destructive">*</span>
            </Label>
            <Input id="pe-name" value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pe-description">{t('adminCatalog.fields.description')}</Label>
            <Textarea
              id="pe-description"
              rows={4}
              value={draft.description ?? ''}
              onChange={(e) => update({ description: e.target.value })}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.manufacturer')}</Label>
              {/* N1: свободный ввод с созданием бренда на лету — как в шторке. */}
              <ManufacturerField
                value={draft.brand_name ?? ''}
                onChange={(brand_name) => update({ brand_name })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pe-mpn">{t('adminCatalog.fields.partNumber')}</Label>
              <Input
                id="pe-mpn"
                value={draft.manufacturer_part_number ?? ''}
                onChange={(e) => update({ manufacturer_part_number: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="pe-gost">{t('adminCatalog.fields.gost')}</Label>
              <Input
                id="pe-gost"
                value={draft.gost_drawing ?? ''}
                onChange={(e) => update({ gost_drawing: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.uom')}</Label>
              <Select
                value={draft.uom ? String(draft.uom) : undefined}
                onValueChange={(value) => update({ uom: Number(value) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(units ?? []).map((unit) => (
                    <SelectItem key={unit.id} value={String(unit.id)}>{unit.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {form.isEdit && draft.sku && (
            <p className="text-xs text-muted-foreground">
              {t('adminCatalog.fields.sku')}: <span className="font-mono">{draft.sku}</span>
            </p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
