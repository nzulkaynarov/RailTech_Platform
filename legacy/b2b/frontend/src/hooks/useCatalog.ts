import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { catalogApi } from '../api/catalogApi';

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
