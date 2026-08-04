import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  useCreateProduct, useUpdateProduct,
  useDomainTypes, useProductStatuses, useCategories, useEquipmentGroups,
  useStockStatuses, useOffers, useCreateOffer, useUpdateOffer,
  useEnrichProduct,
} from '@/hooks/useCatalog';
import { useUnits, useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import type { Product } from '@/api/catalogApi';
import { translateApiError } from '@/lib/apiError';
import { emptyDraft, type Draft, type OfferDraft } from './types';

export function useProductForm({
  open, onOpenChange, target, sellerCompanyId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: Product | null;
  sellerCompanyId?: number;
}) {
  const { t } = useTranslation();
  const { data: domainTypes } = useDomainTypes();
  const { data: statuses } = useProductStatuses();
  const { data: categories } = useCategories();
  const { data: units } = useUnits();
  const { data: equipmentGroups } = useEquipmentGroups();
  const createMut = useCreateProduct();
  const updateMut = useUpdateProduct();

  // --- Seller pricing (H3) ---
  const sellerMode = Boolean(sellerCompanyId);
  const { data: currencies } = useCurrencies();
  const { data: stockStatuses } = useStockStatuses();
  const { data: deliveryBases } = useDeliveryBases();
  const createOfferMut = useCreateOffer();
  const updateOfferMut = useUpdateOffer();
  // On edit, the seller's own offer for this product (C2 scopes /offers/ to them).
  const { data: ownOffers } = useOffers(sellerMode && target?.id ? { product: target.id } : undefined);
  const ownOffer = sellerMode ? (ownOffers ?? []).find((o) => o.supplier === sellerCompanyId) ?? null : null;

  const [draft, setDraft] = useState<Draft>(() => target ?? emptyDraft());
  const [groupIds, setGroupIds] = useState<number[]>(() => target?.equipment_groups?.map((g) => g.id) ?? []);
  const [offerDraft, setOfferDraft] = useState<OfferDraft>({});

  useEffect(() => {
    setDraft(target ? { ...target } : emptyDraft());
    setGroupIds(target?.equipment_groups?.map((g) => g.id) ?? []);
  }, [target]);

  useEffect(() => {
    setOfferDraft(ownOffer
      ? {
          base_price: ownOffer.base_price,
          currency: ownOffer.currency ?? null,
          stock_status: ownOffer.stock_status ?? null,
          delivery_basis: ownOffer.delivery_basis ?? null,
          supplier_sku: ownOffer.supplier_sku ?? '',
          stock_quantity: ownOffer.stock_quantity ?? 0,
          in_stock_lead_time_days: ownOffer.in_stock_lead_time_days ?? 0,
          order_lead_time_days: ownOffer.order_lead_time_days ?? 0,
        }
      : {});
  }, [ownOffer]);

  const updateOffer = (patch: Partial<OfferDraft>) => setOfferDraft((d) => ({ ...d, ...patch }));
  const busy = createMut.isPending || updateMut.isPending || createOfferMut.isPending || updateOfferMut.isPending;
  const isEdit = Boolean(target?.id);

  // Equipment groups are a RAILWAY_MACHINERY taxonomy and are required for that
  // domain (Product.clean()). Resolve the selected domain's code to gate the field.
  const domainCode = (domainTypes ?? []).find((d) => d.id === Number(draft.domain_type))?.code
    ?? (typeof draft.domain_type === 'string' ? draft.domain_type : undefined);
  const isRailway = domainCode === 'RAILWAY_MACHINERY';
  const toggleGroup = (id: number) =>
    setGroupIds((ids) => (ids.includes(id) ? ids.filter((g) => g !== id) : [...ids, id]));

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  // --- AI #2: enrich (suggestion only, seller reviews & edits) ---
  const enrichMut = useEnrichProduct();
  // Category hint is advisory text — the seller still picks the real category from
  // the DB dropdown (Rule 1: we never resolve/invent a Category id from the hint).
  const [categoryHint, setCategoryHint] = useState<string>('');

  const runEnrich = async () => {
    const name = draft.name?.trim();
    if (!name) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    try {
      const suggestion = await enrichMut.mutateAsync({
        name,
        domain_code: domainCode,
        mpn: draft.manufacturer_part_number ?? undefined,
        gost: draft.gost_drawing ?? undefined,
      });
      // Empty object → AI disabled or nothing to suggest.
      if (!suggestion || Object.keys(suggestion).length === 0) {
        toast.info(t('adminCatalog.aiEnrich.empty'));
        return;
      }
      const patch: Partial<Draft> = {};
      if (suggestion.description) patch.description = suggestion.description;
      if (suggestion.specifications?.length) {
        // Map [{key,value}] → the Product.specifications JSON object the form persists.
        const specs: Record<string, string> = {};
        for (const spec of suggestion.specifications) {
          if (spec.key) specs[spec.key] = spec.value;
        }
        // Merge into the existing specs — don't silently drop the product's prior rows (#9).
        patch.specifications = { ...((draft.specifications as Record<string, string>) ?? {}), ...specs };
      }
      update(patch);
      setCategoryHint(suggestion.suggested_category_hint ?? '');
      toast.success(t('adminCatalog.aiEnrich.applied'));
    } catch (err) {
      // AI off → backend 503 {AI_DISABLED}; show the neutral "empty" toast, not a hard error (#8).
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) toast.info(t('adminCatalog.aiEnrich.empty'));
      // Business gates carry a stable {detail: CODE} — surface the localised message
      // (403 AI_FEATURE_NOT_ENTITLED = needs subscription; 429 AI_DAILY_CAP_REACHED).
      else if (status === 403 || status === 429) toast.error(translateApiError(err));
      else toast.error(t('adminCatalog.aiEnrich.failed'));
    }
  };

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    // Пустой справочник групп не блокирует сохранение (канон ТН ВЭД, N1) — требование
    // включается вместе с наполнением; бэкенд проверяет то же условие.
    if (isRailway && (equipmentGroups ?? []).length > 0 && groupIds.length === 0) {
      toast.error(t('adminCatalog.equipmentGroupsRequired'));
      return;
    }
    // brand_name — строка: сервер нормализует (iexact) и создаёт бренд на лету (N1),
    // тем же нормализатором, что Excel-импорт. equipment_groups is an M2M write (list
    // of ids) — the read type is EquipmentGroup[], so the body goes through a
    // write-shaped cast.
    const payload = {
      name: draft.name,
      description: draft.description || '',
      domain_type: draft.domain_type ? Number(draft.domain_type) : undefined,
      status: draft.status ? Number(draft.status) : undefined,
      category: draft.category ? Number(draft.category) : null,
      uom: draft.uom ? Number(draft.uom) : null,
      brand_name: (draft.brand_name || '').trim(),
      manufacturer_part_number: draft.manufacturer_part_number || '',
      equipment_groups: groupIds,
      gost_drawing: draft.gost_drawing || '',
      // T1: код ТН ВЭД теперь редактируется из формы — раньше поля не было вовсе, и очередь
      // номенклатуры требовала то, что негде ввести.
      hs_code: (draft.hs_code || '').replace(/\D/g, ''),
      specifications: draft.specifications ?? undefined,
    } as unknown as Partial<Product>;
    try {
      let productId = target?.id;
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
      } else {
        const created = await createMut.mutateAsync(payload);
        productId = created.id;
      }
      // Seller pricing (H3): upsert the seller's own offer for this product. Skipped
      // when no price is entered so a product can still be saved without an offer.
      if (sellerMode && productId && String(offerDraft.base_price ?? '').trim()) {
        const offerPayload = {
          product: productId,
          supplier: sellerCompanyId,
          base_price: String(offerDraft.base_price),
          currency: offerDraft.currency ? Number(offerDraft.currency) : null,
          stock_status: offerDraft.stock_status ? Number(offerDraft.stock_status) : null,
          delivery_basis: offerDraft.delivery_basis ? Number(offerDraft.delivery_basis) : null,
          supplier_sku: offerDraft.supplier_sku ?? '',
          stock_quantity: Number(offerDraft.stock_quantity ?? 0),
          in_stock_lead_time_days: Number(offerDraft.in_stock_lead_time_days ?? 0),
          order_lead_time_days: Number(offerDraft.order_lead_time_days ?? 0),
        };
        if (ownOffer) {
          await updateOfferMut.mutateAsync({ id: ownOffer.id, data: offerPayload });
        } else {
          await createOfferMut.mutateAsync(offerPayload);
        }
      }
      toast.success(isEdit ? t('adminCatalog.updated') : t('adminCatalog.created'));
      onOpenChange(false);
    } catch {
      toast.error(t('adminCatalog.saveFailed'));
    }
  };

  // `open` is part of the form's public contract (parent toggles visibility); it is
  // not used inside the hook but kept in the signature for API parity.
  void open;

  return {
    // lookups
    domainTypes, statuses, categories, units, equipmentGroups,
    currencies, stockStatuses, deliveryBases,
    // state
    draft, groupIds, offerDraft, categoryHint,
    // derived
    sellerMode, isEdit, isRailway, busy,
    enrichPending: enrichMut.isPending,
    // actions
    update, updateOffer, toggleGroup, runEnrich, submit,
  };
}

export type ProductFormState = ReturnType<typeof useProductForm>;
