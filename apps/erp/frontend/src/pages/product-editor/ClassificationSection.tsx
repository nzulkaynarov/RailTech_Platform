import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, Landmark } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { HSCodeField } from '@/components/Shared/HSCodeField';
import { CustomsDutiesSheet } from '@/components/Shared/CustomsDutiesSheet';

import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { SECTION_IDS } from './anchors';

/** Код направления → подпись вида карточки (M1-ERP-07); иное направление — своим именем. */
const KIND_LABEL_KEY: Record<string, string> = {
  GENERAL_GOODS: 'productEditor.kind.goods',
  SERVICES: 'productEditor.kind.service',
};

/**
 * Секция «Классификация»: домен → категория → ТН ВЭД.
 *
 * Категория — комбобокс с поиском, ОТФИЛЬТРОВАННЫЙ по выбранному домену (категории без
 * домена видны всегда): закрывает застарелую жалобу «категории не фильтруются по
 * домену» — продавец перебирал весь плоский список руками.
 */
export function ClassificationSection({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const { draft, domainTypes, categories, update } = form;
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [dutiesOpen, setDutiesOpen] = useState(false);

  const domainId = draft.domain_type ? Number(draft.domain_type) : null;
  // Категории чужого домена скрыты; без домена у категории — универсальна и видна всегда.
  const visibleCategories = useMemo(
    () => (categories ?? []).filter(
      (category) => !category.domain_type || !domainId || category.domain_type === domainId,
    ),
    [categories, domainId],
  );
  const selectedCategory = (categories ?? []).find((category) => category.id === Number(draft.category));
  // Выбранная категория из ДРУГОГО домена (домен сменили после выбора) остаётся видимой —
  // молча потерять выбор хуже, чем показать неподходящий.
  const categoryOptions = selectedCategory && !visibleCategories.some((c) => c.id === selectedCategory.id)
    ? [selectedCategory, ...visibleCategories]
    : visibleCategories;

  const hsDigits = (draft.hs_code ?? '').replace(/\D/g, '');

  return (
    <section id={SECTION_IDS.classification} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productEditor.sections.classification')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              {/* M1-ERP-07: вид карточки «товар / услуга» хранится в справочнике направлений. */}
              <Label htmlFor="pe-kind">{t('productEditor.kind.label')}</Label>
              <Select
                value={draft.domain_type ? String(draft.domain_type) : undefined}
                onValueChange={(value) => update({ domain_type: Number(value) })}
              >
                <SelectTrigger id="pe-kind"><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(domainTypes ?? []).map((domain) => (
                    <SelectItem key={domain.id} value={String(domain.id)}>
                      {KIND_LABEL_KEY[domain.code] ? t(KIND_LABEL_KEY[domain.code]) : domain.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.category')}</Label>
              <Popover open={categoryOpen} onOpenChange={setCategoryOpen}>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-expanded={categoryOpen}
                    className="w-full justify-between font-normal"
                  >
                    <span className="truncate">
                      {selectedCategory?.name ?? t('productEditor.categoryNone')}
                    </span>
                    <ChevronsUpDown className="size-4 shrink-0 opacity-50" aria-hidden="true" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
                  <Command>
                    <CommandInput placeholder={t('productEditor.categoryPlaceholder')} />
                    <CommandList>
                      <CommandEmpty>{t('productEditor.categoryEmpty')}</CommandEmpty>
                      <CommandGroup>
                        {categoryOptions.map((category) => (
                          <CommandItem
                            key={category.id}
                            value={`${category.name} #${category.id}`}
                            onSelect={() => {
                              update({ category: category.id });
                              setCategoryOpen(false);
                            }}
                          >
                            <Check
                              className={cn(
                                'size-4',
                                Number(draft.category) === category.id ? 'opacity-100' : 'opacity-0',
                              )}
                              aria-hidden="true"
                            />
                            {category.name}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.hsCode')}</Label>
            <HSCodeField value={draft.hs_code ?? ''} onChange={(hs_code) => update({ hs_code })} />
            {/* Полный код — 10 знаков; у более короткой ветки тарифа нет (как в шторке). */}
            {hsDigits.length === 10 && (
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto gap-1 p-0 text-xs"
                onClick={() => setDutiesOpen(true)}
              >
                <Landmark className="size-3.5" aria-hidden="true" />
                {t('customsDuties.action')}
              </Button>
            )}
            <CustomsDutiesSheet
              hsCode={hsDigits}
              hsName={draft.name ?? ''}
              open={dutiesOpen}
              onOpenChange={setDutiesOpen}
            />
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
