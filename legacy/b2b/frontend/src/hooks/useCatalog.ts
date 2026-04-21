import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { catalogApi } from '../api/catalogApi';

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
});

export const useProducts = (params?: Parameters<typeof catalogApi.getProducts>[0]) => useQuery({
  queryKey: ['products', params],
  queryFn: () => catalogApi.getProducts(params),
  staleTime: 3 * 60_000,      // кеш 3 минуты — повторный клик на ту же категорию мгновенный
  gcTime: 10 * 60_000,        // держим в памяти 10 минут после размонтирования
  placeholderData: (prev) => prev, // показываем предыдущие данные пока грузятся новые (нет мигания)
});

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

export const useManufacturers = () => useQuery({
  queryKey: ['manufacturers'],
  queryFn: catalogApi.getManufacturers,
  staleTime: 10 * 60_000,
});

export const useEquipmentGroups = (search?: string) => useQuery({
  queryKey: ['equipment-groups', { search }],
  queryFn: () => catalogApi.getEquipmentGroups(search),
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
