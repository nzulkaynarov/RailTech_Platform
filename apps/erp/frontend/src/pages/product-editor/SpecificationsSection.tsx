import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

import type { Draft } from '@/components/Shared/product-form/types';
import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { SECTION_IDS } from './anchors';

interface SpecRow {
  /** Стабильный ключ строки для React — имя характеристики редактируемо и ключом быть не может. */
  rowId: number;
  key: string;
  value: string;
}

let nextRowId = 1;

const toRows = (specifications: Draft['specifications']): SpecRow[] =>
  Object.entries(specifications ?? {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => ({ rowId: nextRowId++, key, value: String(value) }));

/**
 * Секция «Характеристики» — редактор ключ/значение (D4): до R3 specifications писал
 * ТОЛЬКО ИИ, а убрать или поправить строку руками было негде. Эталон — свободные
 * атрибуты карточки в Akeneo/Shopify metafields: таблица строк с добавлением,
 * правкой и удалением.
 *
 * Строки — локальное состояние (иначе правка имени ключа пересобирала бы объект и
 * строка прыгала в конец); каждый ввод немедленно пишется в черновик формы. Внешние
 * изменения (применение панели ИИ, смена карточки) пересеивают строки — свои записи
 * узнаём по ссылке на последний записанный объект.
 */
export function SpecificationsSection({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const { draft, update } = form;
  const [rows, setRows] = useState<SpecRow[]>(() => toRows(draft.specifications));
  const lastWritten = useRef<Draft['specifications']>(null);

  useEffect(() => {
    // Наша же запись вернулась кругом через draft — строки уже актуальны.
    if (draft.specifications === lastWritten.current) return;
    setRows(toRows(draft.specifications));
  }, [draft.specifications]);

  const commit = (nextRows: SpecRow[]) => {
    setRows(nextRows);
    const record: NonNullable<Draft['specifications']> = {};
    for (const row of nextRows) {
      const key = row.key.trim();
      if (key) record[key] = row.value;
    }
    lastWritten.current = record;
    update({ specifications: record });
  };

  const updateRow = (rowId: number, patch: Partial<Pick<SpecRow, 'key' | 'value'>>) =>
    commit(rows.map((row) => (row.rowId === rowId ? { ...row, ...patch } : row)));
  const removeRow = (rowId: number) => commit(rows.filter((row) => row.rowId !== rowId));
  const addRow = () => setRows((prev) => [...prev, { rowId: nextRowId++, key: '', value: '' }]);

  return (
    <section id={SECTION_IDS.specifications} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productDetail.specifications')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {rows.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('productEditor.specs.empty')}</p>
          )}
          {rows.map((row) => (
            <div key={row.rowId} className="flex items-start gap-2">
              <Input
                value={row.key}
                onChange={(e) => updateRow(row.rowId, { key: e.target.value })}
                placeholder={t('productEditor.specs.key')}
                aria-label={t('productEditor.specs.key')}
                className="flex-1"
              />
              <Input
                value={row.value}
                onChange={(e) => updateRow(row.rowId, { value: e.target.value })}
                placeholder={t('productEditor.specs.value')}
                aria-label={t('productEditor.specs.value')}
                className="flex-1"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                onClick={() => removeRow(row.rowId)}
                aria-label={t('productEditor.specs.remove')}
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={addRow}>
            <Plus className="size-4" aria-hidden="true" />
            {t('productEditor.specs.add')}
          </Button>
        </CardContent>
      </Card>
    </section>
  );
}
