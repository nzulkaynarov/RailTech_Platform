import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { catalogApi } from '../api/catalogApi';
import type { ProductListParams } from '../api/catalogApi';

/**
 * Баннеры-подсказки «Мои товары» (переклассификация, дубли, покрытие) — списки ЗАДАЧ,
 * а не витрина: пользователь идёт по ним чинить карточки и обязан видеть результат
 * СРАЗУ, иначе экран обвиняет его в том, что он только что исправил.
 *
 * Глобальные умолчания клиента (`lib/queryClient.ts`: `refetchOnMount: false`,
 * `staleTime: 2m`) им не годятся. `invalidateQueries(['products'])` из мутации
 * сохранения помечает эти ключи устаревшими, но НЕ перезапрашивает: пока открыта
 * карточка товара, список размонтирован, запрос неактивен — а при возврате
 * `refetchOnMount: false` отдаёт устаревший кэш без похода на сервер.
 *
 * Найдено прогоном глазами 14-08 (W4): продавец менял выведенный из обращения код ТН
 * ВЭД, карточка сохранялась (готовность 75% → 100%), но баннер «Need reclassification»
 * продолжал требовать починить её же — со СТАРЫМ кодом; правда возвращалась только
 * после перезагрузки страницы. В эталонах (SAP GTS worklist, Akeneo) очередь работ
 * пустеет по мере закрытия задач — иначе она перестаёт быть очередью.
 */
const WORKLIST_ALWAYS_FRESH = { staleTime: 0, refetchOnMount: 'always' } as const;

export const useDomainTypes = () => useQuery({
  queryKey: ['domain-types'],
  queryFn: catalogApi.getDomainTypes,
  staleTime: 30 * 60_000,    // lookup table — cache 30 min
  gcTime: 60 * 60_000,       // keep in memory 1 hour
});

export const useProduct = (id: string) => useQuery({
  queryKey: ['product', id],
  queryFn: () => catalogApi.getProduct(id),
  staleTime: 3 * 60_000,
  enabled: Boolean(id),
});

export const useProducts = (params?: Parameters<typeof catalogApi.getProducts>[0]) => useQuery({
  queryKey: ['products', params],
  queryFn: () => catalogApi.getProducts(params),
  staleTime: 3 * 60_000,      // кеш 3 минуты — повторный клик на ту же категорию мгновенный
  gcTime: 10 * 60_000,        // держим в памяти 10 минут после размонтирования
  placeholderData: (prev) => prev, // показываем предыдущие данные пока грузятся новые (нет мигания)
});

/**
 * Страница списка товаров с сервера: возвращает `{count, results}` целиком.
 * `count` — единственный честный источник для KPI и пагинатора; клиентская
 * постраничка поверх первых 20 строк показывала «Всего позиций: 20» на любом каталоге.
 * Ключ содержит все параметры, поэтому смена страницы/сортировки перезапрашивает.
 */
export const useProductsPage = (params: ProductListParams = {}) => useQuery({
  queryKey: ['products', 'page', params],
  queryFn: () => catalogApi.getProductsPage(params),
  staleTime: 3 * 60_000,
  gcTime: 10 * 60_000,
  placeholderData: (prev) => prev, // страница не мигает при листании
});

/**
 * Catalog product typeahead search (КП grid name-cell combobox, spec §5 п.13). Reuses the
 * SAME `catalog/products/?search=` endpoint the catalog list uses — no new API. Gated on a
 * ≥2-char (trimmed) term so a single keystroke never fires a request; the caller debounces.
 */
export const useProductSearch = (term: string) => {
  const trimmed = term.trim();
  return useQuery({
    queryKey: ['product-search', trimmed],
    queryFn: () => catalogApi.getProducts({ search: trimmed }),
    enabled: trimmed.length >= 2,
    staleTime: 60_000,
    placeholderData: (prev) => prev, // keep prior matches visible while the next term loads
  });
};

export const useProductsCount = (params?: Parameters<typeof catalogApi.getProductsCount>[0]) => useQuery({
  queryKey: ['products-count', params],
  queryFn: () => catalogApi.getProductsCount(params),
  staleTime: 3 * 60_000,
  gcTime: 10 * 60_000,
});

export const useCategories = (params?: Parameters<typeof catalogApi.getCategories>[0]) => useQuery({
  queryKey: ['categories', params],
  queryFn: () => catalogApi.getCategories(params),
  staleTime: 10 * 60_000,
});

export const useManufacturers = (opts?: { fetchAll?: boolean }) => useQuery({
  queryKey: ['manufacturers', { fetchAll: opts?.fetchAll ?? false }],
  queryFn: () => catalogApi.getManufacturers(opts),
  staleTime: 10 * 60_000,
});

export const useEquipmentGroups = (search?: string, opts?: { fetchAll?: boolean }) => useQuery({
  queryKey: ['equipment-groups', { search, fetchAll: opts?.fetchAll ?? false }],
  queryFn: () => catalogApi.getEquipmentGroups(search, opts),
  staleTime: 5 * 60_000,
});

export const useCreateProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof catalogApi.createProduct>[0]) => catalogApi.createProduct(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useUpdateProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number, data: Parameters<typeof catalogApi.updateProduct>[1] }) => 
      catalogApi.updateProduct(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useDeleteProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.deleteProduct(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useCreateCategory = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof catalogApi.createCategory>[0]) => catalogApi.createCategory(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  });
};

export const useUpdateCategory = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof catalogApi.updateCategory>[1] }) =>
      catalogApi.updateCategory(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  });
};

export const useDeleteCategory = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.deleteCategory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  });
};

export const useCreateEquipmentGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof catalogApi.createEquipmentGroup>[0]) => catalogApi.createEquipmentGroup(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['equipment-groups'] }),
  });
};

export const useUpdateEquipmentGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof catalogApi.updateEquipmentGroup>[1] }) =>
      catalogApi.updateEquipmentGroup(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['equipment-groups'] }),
  });
};

export const useDeleteEquipmentGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.deleteEquipmentGroup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['equipment-groups'] }),
  });
};

export const useOffers = (params?: Parameters<typeof catalogApi.getOffers>[0]) => useQuery({
  queryKey: ['offers', params],
  queryFn: () => catalogApi.getOffers(params),
  staleTime: 2 * 60_000,
});

export const useCreateOffer = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof catalogApi.createOffer>[0]) => catalogApi.createOffer(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['offers'] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useUpdateOffer = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof catalogApi.updateOffer>[1] }) =>
      catalogApi.updateOffer(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['offers'] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useDeleteOffer = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.deleteOffer(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['offers'] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

/**
 * Очередь наполнения номенклатуры продавца.
 *
 * Ключ включает статус: «Кандидаты» и «Опубликовано» — разные выборки одного каталога, и один
 * ключ на двоих затирал бы их друг другом.
 */
export const useMyCandidates = (statusCode = 'DRAFT') => useQuery({
  queryKey: ['products', 'mine', statusCode],
  queryFn: () => catalogApi.getMyCandidates(statusCode),
});

/** Автокомплит кода ТН ВЭД: пустой запрос — пустой список без похода в сеть. */
export const useHSCodeSuggest = (q: string) => useQuery({
  queryKey: ['hs-suggest', q],
  queryFn: () => catalogApi.suggestHSCodes(q),
  enabled: q.length > 0,
  staleTime: 5 * 60_000,
});

/** Мягкая валидация кода ТН ВЭД (после ввода, не на каждое нажатие). */
export const useHSCodeValidation = (code: string) => useQuery({
  queryKey: ['hs-validate', code],
  queryFn: () => catalogApi.validateHSCode(code),
  enabled: code.length >= 4,
  staleTime: 5 * 60_000,
});

/** Worklist переклассификации (SAP GTS): карточки, чей код ТН ВЭД выведен из редакции. */
export const useReclassificationWorklist = () => useQuery({
  queryKey: ['products', 'reclassification'],
  queryFn: catalogApi.getReclassificationWorklist,
  // Баннер-подсказка ОБЯЗАН быть свежим на монтировании — см. WORKLIST_ALWAYS_FRESH.
  ...WORKLIST_ALWAYS_FRESH,
});

/** Публикация карточки её владельцем; сервер откажет, если полнота не достигнута. */
/** R2: снятие с витрины / архив / восстановление. Все сбрасывают списки товаров. */
export const useUnpublishProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.unpublishProduct(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const useArchiveProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.archiveProduct(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const useRestoreProduct = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.restoreProduct(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const useBulkArchiveProducts = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => catalogApi.bulkArchiveProducts(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const usePublishProduct = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => catalogApi.publishProduct(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const useBulkPublishProducts = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => catalogApi.bulkPublishProducts(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['products'] }),
  });
};

export const useProductStatuses = () => useQuery({
  queryKey: ['product-statuses'],
  queryFn: catalogApi.getProductStatuses,
  staleTime: 30 * 60_000,
});

export const useStockStatuses = () => useQuery({
  queryKey: ['stock-statuses'],
  queryFn: catalogApi.getStockStatuses,
  staleTime: 30 * 60_000,
});

export const useUploadProductImage = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, file, isMain, altText }: {
      productId: number; file: File; isMain?: boolean; altText?: string;
    }) => catalogApi.uploadProductImage(productId, file, { is_main: isMain, alt_text: altText }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['product', String(vars.productId)] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useDeleteProductImage = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, imageId }: { productId: number; imageId: number }) =>
      catalogApi.deleteProductImage(productId, imageId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['product', String(vars.productId)] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
  });
};

export const useUploadProductDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, file, name }: { productId: number; file: File; name?: string }) =>
      catalogApi.uploadProductDocument(productId, file, name),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['product', String(vars.productId)] });
    },
  });
};

export const useDeleteProductDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, docId }: { productId: number; docId: number }) =>
      catalogApi.deleteProductDocument(productId, docId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['product', String(vars.productId)] });
    },
  });
};

// AI #2: draft product fields (description / specs / category hint) from the name.
// SUGGESTION ONLY — caller applies the result into the form draft for the seller to edit.
export const useEnrichProduct = () =>
  useMutation({
    mutationFn: (params: Parameters<typeof catalogApi.enrichProduct>[0]) =>
      catalogApi.enrichProduct(params),
  });

/** N4: покрытие каталога — «северная звезда» направления (Ariba catalog spend). */
export const useCatalogCoverage = () => useQuery({
  queryKey: ['products', 'coverage'],
  queryFn: catalogApi.getCatalogCoverage,
  ...WORKLIST_ALWAYS_FRESH,
});

/** N4: группы вероятных дублей своих карточек (точные ключи: бренд+артикул, ГОСТ, имя). */
export const useDuplicateSuggestions = () => useQuery({
  queryKey: ['products', 'duplicate-suggestions'],
  queryFn: catalogApi.getDuplicateSuggestions,
  ...WORKLIST_ALWAYS_FRESH,
});

/** N4: слияние дубля — дубль уходит в архив, спрос и ссылки переезжают в выжившую. */
export const useMergeProducts = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ survivorId, duplicateId }: { survivorId: number; duplicateId: number }) =>
      catalogApi.mergeProducts(survivorId, duplicateId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['products'] }),
  });
};
