import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  useCreateProduct, useUpdateProduct, useProduct,
  useDomainTypes, useCategories, useEquipmentGroups,
  useStockStatuses, useOffers, useCreateOffer, useUpdateOffer,
  useEnrichProduct,
} from '@/hooks/useCatalog';
import { useUnits, useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import { useCompanies } from '@/hooks/useAccounts';
import { useUserStore } from '@/store/userStore';
import type { Category, Product, ProductEnrichSuggestion } from '@/api/catalogApi';
import type { LookupItem } from '@/api/masterDataApi';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import { emptyDraft, type Draft, type OfferDraft } from './types';

/** Поля карточки, по которым ИИ умеет ПРЕДЛАГАТЬ значение (R4: D4/D5/D6). */
export type EnrichField = 'description' | 'category' | 'hs_code' | 'uom' | 'specifications';

/** Одна характеристика из предложения ИИ — её можно отклонить отдельно от остальных. */
export interface EnrichSpecRow {
  key: string;
  /** Что стоит в карточке сейчас (`''` — такой характеристики не было). */
  current: string;
  next: string;
}

/**
 * Строка панели предложений: «поле → было → предложение». Панель — единственный путь,
 * которым ответ ИИ попадает в форму (Akeneo AI suggestions / Shopify Magic): раньше
 * описание и характеристики перезаписывались молча, без «было» и без отмены.
 */
export interface EnrichProposal {
  field: EnrichField;
  /** Значение в карточке сейчас — колонка «было». */
  current: string;
  /** Значение, предложенное ИИ — колонка «предложение». */
  next: string;
  /** Только у `specifications`: построчная расшифровка (сворачивается в «N строк»). */
  specs?: EnrichSpecRow[];
}

/** Ярлык поля в панели предложений — переиспользуем подписи самой формы. */
export const ENRICH_FIELD_LABEL_KEY: Record<EnrichField, string> = {
  description: 'adminCatalog.fields.description',
  category: 'adminCatalog.fields.category',
  hs_code: 'adminCatalog.fields.hsCode',
  uom: 'adminCatalog.fields.uom',
  specifications: 'productDetail.specifications',
};

const specToText = (value: unknown): string => (value === null || value === undefined ? '' : String(value));

const digitsOnly = (value: string | null | undefined): string => (value ?? '').replace(/\D/g, '');

/**
 * Превращает ответ ИИ в список предложений. Поля, которые ИИ не подобрал (`""`/`null`)
 * или подобрал ровно то, что уже стоит в карточке, в панель НЕ попадают — иначе человек
 * подтверждает пустоту. Категория и единица измерения приходят ВЫБОРОМ из справочника
 * (id / код UN-ECE), поэтому имя берём локально из уже загруженного списка.
 */
function buildEnrichProposals(
  suggestion: ProductEnrichSuggestion,
  draft: Draft,
  categories: Category[],
  units: LookupItem[],
): EnrichProposal[] {
  const proposals: EnrichProposal[] = [];

  const currentDescription = (draft.description ?? '').trim();
  const nextDescription = (suggestion.description ?? '').trim();
  if (nextDescription && nextDescription !== currentDescription) {
    proposals.push({ field: 'description', current: currentDescription, next: nextDescription });
  }

  const nextCategory = suggestion.category_id
    ? categories.find((category) => category.id === suggestion.category_id)
    : undefined;
  if (nextCategory && Number(draft.category) !== nextCategory.id) {
    proposals.push({
      field: 'category',
      current: categories.find((category) => category.id === Number(draft.category))?.name ?? '',
      next: nextCategory.name,
    });
  }

  const nextHsCode = digitsOnly(suggestion.hs_code);
  if (nextHsCode && nextHsCode !== digitsOnly(draft.hs_code)) {
    proposals.push({ field: 'hs_code', current: digitsOnly(draft.hs_code), next: nextHsCode });
  }

  const nextUom = suggestion.uom_code ? units.find((unit) => unit.code === suggestion.uom_code) : undefined;
  if (nextUom && Number(draft.uom) !== nextUom.id) {
    proposals.push({
      field: 'uom',
      current: units.find((unit) => unit.id === Number(draft.uom))?.name ?? '',
      next: nextUom.name,
    });
  }

  const currentSpecs = (draft.specifications ?? {}) as Record<string, unknown>;
  const specs = (suggestion.specifications ?? [])
    .filter((spec) => spec.key && spec.value)
    .map((spec) => ({ key: spec.key, current: specToText(currentSpecs[spec.key]), next: spec.value }))
    .filter((spec) => spec.current !== spec.next);
  if (specs.length > 0) proposals.push({ field: 'specifications', current: '', next: '', specs });

  return proposals;
}

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
  const { data: categories } = useCategories();
  const { data: units } = useUnits();
  const { data: equipmentGroups } = useEquipmentGroups();
  const createMut = useCreateProduct();
  const updateMut = useUpdateProduct();

  // --- Seller pricing (H3) ---
  const sellerMode = Boolean(sellerCompanyId);
  // N3: операторская карточка обязана иметь владельца (иначе она «ничья» и продавец никогда
  // не сможет взять её в работу) — админ-форма выбирает компанию из списка.
  const { data: adminCompanies } = useCompanies({ fetchAll: true }, !sellerMode);
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

  // N2 (B2/B3 аудита): `target` — строка СПИСКА, а ProductListSerializer не отдаёт
  // description и equipment_groups. Форма, сидящая на строке списка, слала PATCH с
  // description:"" и equipment_groups:[] — молча стирая карточку при каждом «Дополнить».
  // Поэтому на редактировании добираем ПОЛНУЮ карточку и пересаживаем черновик на неё;
  // до её прихода сохранение закрыто (fullCardReady в busy).
  const { data: fullCard } = useProduct(target?.id ? String(target.id) : '');
  useEffect(() => {
    setDraft(target ? { ...target } : emptyDraft());
    setGroupIds(target?.equipment_groups?.map((g) => g.id) ?? []);
  }, [target]);
  useEffect(() => {
    if (!fullCard || fullCard.id !== target?.id) return;
    setDraft({ ...fullCard });
    // Полный сериализатор отдаёт M2M PK-списком (number[]), списочный — объектами.
    setGroupIds(
      ((fullCard.equipment_groups ?? []) as Array<number | { id: number }>).map((g) =>
        typeof g === 'number' ? g : g.id,
      ),
    );
  }, [fullCard, target]);
  const fullCardReady = !target?.id || fullCard?.id === target.id;

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
          // R7: поля жили в модели и писались импортом, но продавцу их негде было задать —
          // условия из прайса нельзя было ни поправить, ни завести руками.
          delivery_lead_time: ownOffer.delivery_lead_time ?? '',
          min_order_qty: ownOffer.min_order_qty,
          valid_from: ownOffer.valid_from ?? null,
          valid_until: ownOffer.valid_until ?? null,
          is_active: ownOffer.is_active,
        }
      : {});
  }, [ownOffer]);

  const updateOffer = (patch: Partial<OfferDraft>) => setOfferDraft((d) => ({ ...d, ...patch }));
  const busy =
    createMut.isPending || updateMut.isPending || createOfferMut.isPending || updateOfferMut.isPending ||
    !fullCardReady;
  const isEdit = Boolean(target?.id);

  // Equipment groups are a RAILWAY_MACHINERY taxonomy and are required for that
  // domain (Product.clean()). Resolve the selected domain's code to gate the field.
  const domainCode = (domainTypes ?? []).find((d) => d.id === Number(draft.domain_type))?.code
    ?? (typeof draft.domain_type === 'string' ? draft.domain_type : undefined);
  const isRailway = domainCode === 'RAILWAY_MACHINERY';
  const toggleGroup = (id: number) =>
    setGroupIds((ids) => (ids.includes(id) ? ids.filter((g) => g !== id) : [...ids, id]));

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  // --- AI #2: enrich (ПРЕДЛОЖЕНИЕ по каждому полю, форма меняется только по кнопке) ---
  const enrichMut = useEnrichProduct();
  // Category hint is advisory text — the seller still picks the real category from
  // the DB dropdown (Rule 1: we never resolve/invent a Category id from the hint).
  // Остаётся ЗАПАСНЫМ вариантом на случай, когда сервер не выбрал category_id.
  const [categoryHint, setCategoryHint] = useState<string>('');
  const [suggestion, setSuggestion] = useState<ProductEnrichSuggestion | null>(null);
  // Отклонения, а не согласия: по умолчанию отмечено всё (как в пакетном подборе ТН ВЭД),
  // человек снимает лишнее и жмёт одно явное «Применить».
  const [rejectedFields, setRejectedFields] = useState<Set<EnrichField>>(new Set());
  const [rejectedSpecKeys, setRejectedSpecKeys] = useState<Set<string>>(new Set());

  // Дневной расход ИИ — ИНФОРМАЦИЯ рядом с кнопкой, а не гейт: потолок живёт на сервере
  // (429 AI_DAILY_CAP_REACHED). `null` = безлимит, `undefined` = бэкенд не прислал.
  const aiDailyCap = useUserStore((s) => s.capabilities.ai_daily_cap);
  const aiDailyRemaining = useUserStore((s) => s.capabilities.ai_daily_remaining);

  const enrichProposals = useMemo(
    () => (suggestion ? buildEnrichProposals(suggestion, draft, categories ?? [], units ?? []) : []),
    [suggestion, draft, categories, units],
  );
  const acceptedSpecs = (enrichProposals.find((p) => p.field === 'specifications')?.specs ?? [])
    .filter((spec) => !rejectedSpecKeys.has(spec.key));
  const enrichAcceptedCount = enrichProposals.filter(
    (proposal) => !rejectedFields.has(proposal.field)
      && (proposal.field !== 'specifications' || acceptedSpecs.length > 0),
  ).length;

  const toggleEnrichField = (field: EnrichField) =>
    setRejectedFields((fields) => {
      const next = new Set(fields);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  const toggleEnrichSpec = (key: string) =>
    setRejectedSpecKeys((keys) => {
      const next = new Set(keys);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const dismissEnrich = () => {
    setSuggestion(null);
    setRejectedFields(new Set());
    setRejectedSpecKeys(new Set());
  };

  /** Применяет ТОЛЬКО отмеченные строки — единственное место, где ответ ИИ трогает форму. */
  const applyEnrich = () => {
    if (!suggestion) return;
    const patch: Partial<Draft> = {};
    for (const proposal of enrichProposals) {
      if (rejectedFields.has(proposal.field)) continue;
      if (proposal.field === 'description') patch.description = proposal.next;
      if (proposal.field === 'hs_code') patch.hs_code = proposal.next;
      if (proposal.field === 'category') patch.category = suggestion.category_id ?? null;
      if (proposal.field === 'uom') {
        const unit = (units ?? []).find((u) => u.code === suggestion.uom_code);
        if (unit) patch.uom = unit.id;
      }
      if (proposal.field === 'specifications') {
        if (acceptedSpecs.length === 0) continue;
        // Дописываем к уже введённым характеристикам — прежние строки карточки не теряются.
        const merged: NonNullable<Draft['specifications']> = { ...(draft.specifications ?? {}) };
        for (const spec of acceptedSpecs) merged[spec.key] = spec.next;
        patch.specifications = merged;
      }
    }
    if (Object.keys(patch).length === 0) return;
    update(patch);
    dismissEnrich();
    toast.success(t('adminCatalog.aiEnrich.applied'));
  };

  const runEnrich = async () => {
    const name = draft.name?.trim();
    if (!name) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    try {
      const result = await enrichMut.mutateAsync({
        name,
        domain_code: domainCode,
        mpn: draft.manufacturer_part_number ?? undefined,
        gost: draft.gost_drawing ?? undefined,
      });
      // Empty object → AI disabled or nothing to suggest.
      if (!result || Object.keys(result).length === 0) {
        toast.info(t('adminCatalog.aiEnrich.empty'));
        return;
      }
      const proposals = buildEnrichProposals(result, draft, categories ?? [], units ?? []);
      // Подсказка-текст нужна ровно тогда, когда категорию из справочника выбрать не вышло.
      const hasCategoryProposal = proposals.some((proposal) => proposal.field === 'category');
      setCategoryHint(hasCategoryProposal ? '' : (result.suggested_category_hint ?? ''));
      if (proposals.length === 0) {
        // Честный ответ вместо пустой панели: ИИ ответил, но добавить к карточке нечего.
        setSuggestion(null);
        toast.info(t('adminCatalog.aiEnrich.nothingNew'));
        return;
      }
      setRejectedFields(new Set());
      setRejectedSpecKeys(new Set());
      setSuggestion(result);
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
    // N3: оператор обязан назвать владельца создаваемой карточки (бэкенд ответит
    // OWNER_COMPANY_REQUIRED — но честнее не пускать запрос вовсе).
    if (!sellerMode && !isEdit && !draft.owner_company) {
      toast.error(t('adminCatalog.ownerCompanyRequired'));
      return;
    }
    // Перевёрнутое окно действия цены сервер отвергает (OFFER_VALIDITY_RANGE_INVALID) —
    // но называем причину ДО запроса, тем же приёмом, что и проверка владельца выше.
    if (
      sellerMode
      && offerDraft.valid_from
      && offerDraft.valid_until
      && offerDraft.valid_until < offerDraft.valid_from
    ) {
      toast.error(t('adminCatalog.pricing.validityRangeInvalid'));
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
      // status намеренно НЕ шлём (N2, B4): жизненный цикл меняют только сервисы публикации.
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
      // N3: владелец карточки при создании оператором (у продавца его ставит сервер).
      owner_company: !sellerMode && !isEdit && draft.owner_company ? Number(draft.owner_company) : undefined,
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
          delivery_lead_time: offerDraft.delivery_lead_time ?? '',
          // Пустые поля НЕ шлём: умолчания (`min_order_qty=1`, `is_active=True`) живут в
          // модели, и дублировать их на клиенте значило бы завести вторую точку правды.
          ...(offerDraft.min_order_qty === undefined
            ? {}
            : { min_order_qty: Number(offerDraft.min_order_qty) }),
          ...(offerDraft.is_active === undefined ? {} : { is_active: offerDraft.is_active }),
          // Пустая граница окна — осознанный `null` («бессрочно»), а не «не трогать».
          valid_from: offerDraft.valid_from || null,
          valid_until: offerDraft.valid_until || null,
        };
        if (ownOffer) {
          await updateOfferMut.mutateAsync({ id: ownOffer.id, data: offerPayload });
        } else {
          await createOfferMut.mutateAsync(offerPayload);
        }
      }
      toast.success(isEdit ? t('adminCatalog.updated') : t('adminCatalog.created'));
      onOpenChange(false);
    } catch (err) {
      // Честный тост (N2, M3): показываем код бэкенда, если он есть, — «не удалось» без
      // причины оставляло пользователя гадать.
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('adminCatalog.saveFailed'));
    }
  };

  // Предложения принадлежат ОТКРЫТОЙ карточке: закрыли форму или переключились на другой
  // товар — панель уходит, иначе чужие подсказки применились бы к другой карточке.
  useEffect(() => {
    if (open) return;
    setSuggestion(null);
    setRejectedFields(new Set());
    setRejectedSpecKeys(new Set());
    setCategoryHint('');
  }, [open]);
  useEffect(() => {
    setSuggestion(null);
    setRejectedFields(new Set());
    setRejectedSpecKeys(new Set());
    setCategoryHint('');
  }, [target]);

  return {
    // lookups
    domainTypes, categories, units, equipmentGroups,
    currencies, stockStatuses, deliveryBases, adminCompanies,
    // state
    draft, groupIds, offerDraft, categoryHint,
    // derived
    sellerMode, isEdit, isRailway, busy,
    enrichPending: enrichMut.isPending,
    // AI suggestions (панель «поле → было → предложение»)
    enrichProposals, rejectedFields, rejectedSpecKeys, enrichAcceptedCount,
    aiDailyCap, aiDailyRemaining,
    // actions
    update, updateOffer, toggleGroup, runEnrich, submit,
    toggleEnrichField, toggleEnrichSpec, applyEnrich, dismissEnrich,
  };
}

export type ProductFormState = ReturnType<typeof useProductForm>;
