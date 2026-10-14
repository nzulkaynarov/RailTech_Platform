import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface Attachment {
  id: number;
  file: string | null;
  original_filename: string;
  kind?: 'SOURCE' | 'SUPPORTING';
  uploaded_by: number | null;
  uploaded_by_email: string | null;
  uploaded_at: string;
  deal?: number | null;
  quote?: number | null;
  company?: number | null;
  product?: number | null;
}

export const sourcingApi = {
  listAttachments: async (params: {
    deal?: number; quote?: number; company?: number; product?: number;
  }): Promise<Attachment[]> => {
    const response = await apiClient.get<PaginatedResponse<Attachment>>('sourcing/attachments/', { params });
    return response.data.results;
  },
  // Company-wide file registry (wave D «Файлы»). The endpoint is paginated
  // (PageNumberPagination, PAGE_SIZE=20) and does NOT expose a `page_size` query
  // param, so a single request would silently truncate the registry to 20 rows.
  // We walk every page via the paginator's `next` link to build the COMPLETE list
  // (a bounded loop guards against a misbehaving API), so the UI can be honest
  // about totals instead of showing a partial slice.
  listAllAttachments: async (): Promise<Attachment[]> => {
    const MAX_PAGES = 50; // 50 × 20 = 1000 files ceiling for v1 — plenty, and never unbounded
    const all: Attachment[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const response = await apiClient.get<PaginatedResponse<Attachment>>(
        'sourcing/attachments/',
        { params: { page } },
      );
      all.push(...response.data.results);
      if (!response.data.next) break;
    }
    return all;
  },
  uploadAttachment: async (
    parent: { deal?: number; quote?: number; company?: number; product?: number },
    file: File,
  ): Promise<Attachment> => {
    const formData = new FormData();
    formData.append('file', file);
    Object.entries(parent).forEach(([k, v]) => {
      if (v != null) formData.append(k, String(v));
    });
    const response = await apiClient.post<Attachment>('sourcing/attachments/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },
  deleteAttachment: async (id: number): Promise<void> => {
    await apiClient.delete(`sourcing/attachments/${id}/`);
  },
  importCatalog: async (file: File, dryRun = false): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('dry_run', dryRun ? 'true' : 'false');
    const response = await apiClient.post<{ task_id: string; status: string }>(
      'sourcing/import-catalog/',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },
  /**
   * ИИ-путь массовой загрузки (волна R5b): любой файл (xlsx/pdf/png/jpg/jpeg, до 20 МБ),
   * строки извлекает ИИ. Отвечает 202 {task_id} — результат забирается через
   * `runAiJob` (@/lib/aiJob), НЕ через import-status. Внутри бэкенда xlsx по нашему
   * шаблону идёт бесплатным путём (в отчёте ai_used=false).
   */
  importCatalogAi: async (file: File, dryRun = false): Promise<{ task_id: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('dry_run', dryRun ? 'true' : 'false');
    const response = await apiClient.post<{ task_id: string }>(
      'sourcing/import-catalog-ai/',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },
  downloadCatalogTemplate: async (): Promise<Blob> => {
    const response = await apiClient.get('sourcing/catalog-template/', { responseType: 'blob' });
    return response.data as Blob;
  },
  getImportStatus: async (taskId: string) => {
    const response = await apiClient.get<{
      task_id: string;
      status: string;
      result?: CatalogImportResult | null;
      meta?: { current?: number; total?: number };
    }>(`sourcing/import-status/${taskId}/`);
    return response.data;
  },
};

/** Строка отчёта импорта: номер строки файла + машинный код причины. */
export interface CatalogImportRowMessage {
  row: number;
  message: string;
}

/**
 * Одно невыполненное требование порога публикации: машинный код, УЖЕ переведённое
 * сервером название и число карточек, которым его не хватает.
 */
export interface CatalogImportMissingRequirement {
  code: string;
  label: string;
  count: number;
}

/**
 * Итог импорта каталога.
 *
 * Все поля опциональны намеренно: во время выкатки бандл может оказаться новее
 * бэкенда (или наоборот), и страница обязана деградировать молча, а не падать.
 */
export interface CatalogImportResult {
  status?: string;
  message?: string | null;
  dry_run?: boolean | null;
  created?: number | null;
  updated?: number | null;
  offers_upserted?: number | null;
  skipped?: number | null;
  error_count?: number | null;
  errors?: CatalogImportRowMessage[] | null;
  items_processed?: number | null;
  /** Сколько созданных/обновлённых карточек НЕ пройдут порог публикации. */
  unpublishable?: number | null;
  /** Чего именно не хватает и на скольких карточках (по убыванию count). */
  missing_breakdown?: CatalogImportMissingRequirement[] | null;
  /** Мягкие замечания: строка загружена, но к ней есть вопрос. Список усечён. */
  warnings?: CatalogImportRowMessage[] | null;
  /** Полное число замечаний — может быть больше длины `warnings`. */
  warning_count?: number | null;
  /** Сколько строк файла отброшено лимитом (0 — ничего не отброшено). */
  rows_truncated?: number | null;
  /** true — строки из файла извлекал ИИ (не шаблонный парсер): предпросмотр стоит проверить внимательнее. */
  ai_used?: boolean;
  /** Сколько строк извлёк ИИ (осмысленно только при ai_used=true). */
  ai_rows?: number;
}
