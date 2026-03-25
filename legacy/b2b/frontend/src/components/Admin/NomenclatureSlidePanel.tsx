import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, Search, Check } from 'lucide-react';

import { Product } from '@/api/catalogApi';
import { useEquipmentGroups, useCategories } from '@/hooks/useCatalog';
import { useCurrencies, useUnits } from '@/hooks/useMasterData';

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet';
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const createNomenclatureSchema = (t: (key: string) => string) => z.object({
  name: z.string().min(1, t('nomenclaturePanel.validation.nameRequired')),
  sku: z.string().optional(),
  domain_type: z.enum(['GENERAL_GOODS', 'RAILWAY_MACHINERY', 'SERVICES']),
  category: z.string().optional(),
  description: z.string().optional(),
  base_price: z.string().min(1, t('nomenclaturePanel.validation.priceRequired')),
  currency: z.string().optional(),
  uom: z.string().optional(),
  gost_drawing: z.string().optional(),
});

type NomenclatureFormValues = z.infer<ReturnType<typeof createNomenclatureSchema>>;

interface NomenclatureSlidePanelProps {
  isOpen: boolean;
  onClose: () => void;
  product: Product | null;
  onSave: (data: Partial<Product> & { equipment_group_ids?: number[] }) => Promise<void>;
}

export const NomenclatureSlidePanel: React.FC<NomenclatureSlidePanelProps> = ({
  isOpen,
  onClose,
  product,
  onSave,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [groupSearch, setGroupSearch] = useState('');
  const [selectedGroupIds, setSelectedGroupIds] = useState<number[]>([]);

  const nomenclatureSchema = createNomenclatureSchema(t);

  const form = useForm<NomenclatureFormValues>({
    resolver: zodResolver(nomenclatureSchema),
    defaultValues: {
      name: '',
      sku: '',
      domain_type: 'GENERAL_GOODS',
      category: '',
      description: '',
      base_price: '0',
      currency: '',
      uom: '',
      gost_drawing: '',
    },
  });

  const watchedDomainType = form.watch('domain_type');

  const { data: groups = [], isLoading: groupsLoading } = useEquipmentGroups(groupSearch || undefined);
  const { data: categories = [] } = useCategories({
    domain_type: watchedDomainType || undefined,
  });
  const { data: currencies = [] } = useCurrencies();
  const { data: units = [] } = useUnits();

  const isEdit = !!product;

  // Reset form when product changes or panel opens
  useEffect(() => {
    if (!isOpen) return;

    if (product) {
      const currencyVal = product.currency && typeof product.currency === 'object'
        ? String((product.currency as { id: number }).id)
        : product.currency != null ? String(product.currency) : '';

      const uomVal = product.uom && typeof product.uom === 'object'
        ? String((product.uom as { id: number }).id)
        : product.uom != null ? String(product.uom) : '';

      form.reset({
        name: product.name || '',
        sku: product.sku || '',
        domain_type: (product.domain_type as 'GENERAL_GOODS' | 'RAILWAY_MACHINERY' | 'SERVICES') || 'GENERAL_GOODS',
        category: product.category != null ? String(product.category) : '',
        description: product.description || '',
        base_price: product.base_price || '0',
        currency: currencyVal,
        uom: uomVal,
        gost_drawing: product.gost_drawing || '',
      });
      setSelectedGroupIds(product.equipment_groups?.map(g => g.id) || []);
    } else {
      form.reset({
        name: '',
        sku: '',
        domain_type: 'GENERAL_GOODS',
        category: '',
        description: '',
        base_price: '0',
        currency: currencies.length > 0 ? String(currencies[0]?.id) : '',
        uom: units.length > 0 ? String(units[0]?.id) : '',
        gost_drawing: '',
      });
      setSelectedGroupIds([]);
    }
  }, [product, isOpen, currencies, units, form]);

  const toggleGroup = (id: number) => {
    setSelectedGroupIds(prev =>
      prev.includes(id) ? prev.filter(gid => gid !== id) : [...prev, id]
    );
  };

  const onSubmit = async (values: NomenclatureFormValues) => {
    if (values.domain_type === 'RAILWAY_MACHINERY' && selectedGroupIds.length === 0) {
      form.setError('domain_type', {
        message: t('nomenclaturePanel.railwayGroupRequired'),
      });
      return;
    }

    setLoading(true);
    try {
      await onSave({
        name: values.name,
        sku: values.sku || null,
        domain_type: values.domain_type,
        category: values.category ? Number(values.category) : null,
        description: values.description || '',
        base_price: values.base_price,
        currency: values.currency ? Number(values.currency) : undefined,
        uom: values.uom ? Number(values.uom) : undefined,
        gost_drawing: values.gost_drawing || '',
        equipment_group_ids: selectedGroupIds,
      });
      onClose();
    } catch (error) {
      console.error('Save failed', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Sheet open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" className="w-full sm:max-w-[600px] flex flex-col p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle>
            {isEdit ? t('nomenclaturePanel.editTitle') : t('nomenclaturePanel.createTitle')}
          </SheetTitle>
          <SheetDescription>
            {isEdit
              ? t('nomenclaturePanel.editDescription', { sku: product?.sku || t('nomenclaturePanel.editDescriptionNoSku') })
              : t('nomenclaturePanel.createDescription')}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <Form {...form}>
            <form
              id="nomenclature-form"
              onSubmit={form.handleSubmit(onSubmit)}
              className="space-y-6"
            >
              {/* Name */}
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nomenclaturePanel.productName')}</FormLabel>
                    <FormControl>
                      <Input placeholder={t('nomenclaturePanel.productNamePlaceholder')} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* SKU + Domain Type */}
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="sku"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t('nomenclaturePanel.sku')}</FormLabel>
                      <FormControl>
                        <Input placeholder="RT-SKU-000000" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="domain_type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t('nomenclaturePanel.domainType')}</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder={t('nomenclaturePanel.domainPlaceholder')} />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="GENERAL_GOODS">{t('domains.GENERAL_GOODS')}</SelectItem>
                          <SelectItem value="RAILWAY_MACHINERY">{t('domains.RAILWAY_MACHINERY')}</SelectItem>
                          <SelectItem value="SERVICES">{t('domains.SERVICES')}</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Category */}
              <FormField
                control={form.control}
                name="category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nomenclaturePanel.category')}</FormLabel>
                    <Select
                      value={field.value || ''}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder={t('nomenclaturePanel.categoryPlaceholder')} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="none">{t('nomenclaturePanel.noCategory')}</SelectItem>
                        {categories.map(cat => (
                          <SelectItem key={cat.id} value={String(cat.id)}>
                            {cat.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Description */}
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nomenclaturePanel.description')}</FormLabel>
                    <FormControl>
                      <Textarea
                        rows={4}
                        placeholder={t('nomenclaturePanel.descriptionPlaceholder')}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Base Price + Currency */}
              <div className="grid grid-cols-3 gap-4">
                <FormField
                  control={form.control}
                  name="base_price"
                  render={({ field }) => (
                    <FormItem className="col-span-2">
                      <FormLabel>{t('nomenclaturePanel.basePrice')}</FormLabel>
                      <FormControl>
                        <Input type="number" step="0.01" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="currency"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t('nomenclaturePanel.currency')}</FormLabel>
                      <Select
                        value={field.value || ''}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder={t('nomenclaturePanel.currencyPlaceholder')} />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {currencies.map(c => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {c.code}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* UOM */}
              <FormField
                control={form.control}
                name="uom"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nomenclaturePanel.uom')}</FormLabel>
                    <Select
                      value={field.value || ''}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder={t('nomenclaturePanel.uomPlaceholder')} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {units.map(u => (
                          <SelectItem key={u.id} value={String(u.id)}>
                            {u.name} ({u.code})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* GOST / Drawing */}
              <FormField
                control={form.control}
                name="gost_drawing"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nomenclaturePanel.gostDrawing')}</FormLabel>
                    <FormControl>
                      <Input placeholder={t('nomenclaturePanel.gostPlaceholder')} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Equipment Groups (for Railway domain) */}
              <div className="space-y-3">
                <p className="text-sm font-medium leading-none">
                  {t('nomenclaturePanel.equipmentSeries')}
                </p>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                  <Input
                    placeholder={t('nomenclaturePanel.searchSeries')}
                    value={groupSearch}
                    onChange={e => setGroupSearch(e.target.value)}
                    className="pl-9"
                  />
                </div>

                <div className="max-h-[240px] overflow-y-auto rounded-md border p-1 space-y-0.5">
                  {groupsLoading ? (
                    <div className="flex justify-center py-6">
                      <Loader2 className="size-5 animate-spin text-muted-foreground" />
                    </div>
                  ) : groups.length > 0 ? (
                    groups.map(group => {
                      const isSelected = selectedGroupIds.includes(group.id);
                      return (
                        <Button
                          key={group.id}
                          type="button"
                          variant="ghost"
                          onClick={() => toggleGroup(group.id)}
                          className={cn(
                            'flex w-full items-center justify-between rounded-sm px-3 py-2 h-auto text-sm transition-colors text-left',
                            isSelected
                              ? 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground'
                              : 'hover:bg-accent hover:text-accent-foreground'
                          )}
                        >
                          <div className="min-w-0">
                            <div className="truncate font-medium">{group.name}</div>
                            <div className={cn(
                              'text-xs',
                              isSelected ? 'text-primary-foreground/70' : 'text-muted-foreground'
                            )}>
                              {group.equipment_type} &bull; {group.series}
                            </div>
                          </div>
                          {isSelected && <Check className="size-4 shrink-0" />}
                        </Button>
                      );
                    })
                  ) : (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      {t('nomenclaturePanel.noGroups')}
                    </p>
                  )}
                </div>

                {watchedDomainType === 'RAILWAY_MACHINERY' && selectedGroupIds.length === 0 && (
                  <p className="text-sm text-destructive">
                    {t('nomenclaturePanel.railwayGroupRequired')}
                  </p>
                )}
              </div>
            </form>
          </Form>
        </div>

        <SheetFooter className="flex-row justify-end gap-2 border-t px-6 py-4">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            form="nomenclature-form"
            disabled={loading || !form.formState.isValid}
          >
            {loading && <Loader2 className="size-4 animate-spin" />}
            {isEdit ? t('nomenclaturePanel.saveChanges') : t('nomenclaturePanel.createProduct')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
};
