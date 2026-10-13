# New Hook

Создай новый React Query хук для работы с API.

## Аргумент

$ARGUMENTS — имя домена (например: `Logistics`, `Contracts`, `Analytics`)

## Инструкции

### 1. Создай API модуль

Путь: `src/api/<domain>Api.ts`

```tsx
import { apiClient } from './client';
import type { PaginatedResponse } from './types';

// Определи интерфейсы на основе домена
export interface <Entity> {
  id: number;
  // ... поля
  created_at: string;
  updated_at: string;
}

export interface <Entity>ListParams {
  page?: number;
  page_size?: number;
  search?: string;
  ordering?: string;
}

export const <domain>Api = {
  getAll: (params?: <Entity>ListParams) =>
    apiClient.get<PaginatedResponse<<Entity>>>('/<endpoint>/', { params }).then(r => r.data),

  getById: (id: number) =>
    apiClient.get<<Entity>>(`/<endpoint>/${id}/`).then(r => r.data),

  create: (data: Partial<<Entity>>) =>
    apiClient.post<<Entity>>('/<endpoint>/', data).then(r => r.data),

  update: (id: number, data: Partial<<Entity>>) =>
    apiClient.patch<<Entity>>(`/<endpoint>/${id}/`, data).then(r => r.data),

  delete: (id: number) =>
    apiClient.delete(`/<endpoint>/${id}/`),
};
```

### 2. Создай хук

Путь: `src/hooks/use<Domain>.ts`

```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { <domain>Api } from '@/api/<domain>Api';
import type { <Entity>, <Entity>ListParams } from '@/api/<domain>Api';

const QUERY_KEY = '<entities>';
const STALE_TIME = 3 * 60 * 1000;   // 3 min
const CACHE_TIME = 10 * 60 * 1000;  // 10 min

export function use<Entities>(params?: <Entity>ListParams) {
  return useQuery({
    queryKey: [QUERY_KEY, params],
    queryFn: () => <domain>Api.getAll(params),
    staleTime: STALE_TIME,
    gcTime: CACHE_TIME,
  });
}

export function use<Entity>(id: number) {
  return useQuery({
    queryKey: [QUERY_KEY, id],
    queryFn: () => <domain>Api.getById(id),
    enabled: !!id,
    staleTime: STALE_TIME,
    gcTime: CACHE_TIME,
  });
}

export function useCreate<Entity>() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: <domain>Api.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
  });
}

export function useUpdate<Entity>() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<<Entity>> }) =>
      <domain>Api.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
  });
}

export function useDelete<Entity>() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: <domain>Api.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
  });
}
```

## Конвенции

- API модуль: camelCase + `Api` суффикс
- Хук файл: camelCase с `use` префиксом
- Query keys: kebab-case строки
- staleTime: 3 мин, gcTime: 10 мин (как в useCatalog)
- Мутации инвалидируют queries через `invalidateQueries`
- Axios клиент из `@/api/client`

## После создания

```bash
npm run lint:tsc
```
