/**
 * Заявки на категорию (R6, D7) — escape-hatch платформенной таксономии.
 *
 * Продавец не заводит своё дерево (эталон Google Merchant Center: таксономия площадки
 * фиксирована), но и не упирается в стену: он ПРОСИТ категорию, а решает оператор.
 * Компания-автор считается сервером — в теле её нет намеренно.
 */

import { apiClient } from './client';
import type { PaginatedResponse } from './types';

/** Статус заявки — сравнивается по КОДУ (Rule 2), подпись подбирает витрина. */
export type CategoryRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface CategoryRequest {
    id: number;
    company: number;
    company_name: string;
    requested_by_email: string;
    proposed_name: string;
    parent: number | null;
    parent_name: string;
    domain_type: number | null;
    domain_type_code: string;
    justification: string;
    status: CategoryRequestStatus;
    resulting_category: number | null;
    resulting_category_name: string;
    review_notes: string;
    reviewed_at: string | null;
    created_at: string;
}

export interface CategoryRequestPayload {
    proposed_name: string;
    parent?: number | null;
    domain_type?: number | null;
    justification?: string;
}

export const categoryRequestsApi = {
    /** Обращения СВОЕЙ компании (сервер сужает выдачу — чужие не приходят). */
    list: async (): Promise<CategoryRequest[]> => {
        const response = await apiClient.get<PaginatedResponse<CategoryRequest> | CategoryRequest[]>(
            'catalog/category-requests/',
        );
        return Array.isArray(response.data) ? response.data : response.data.results;
    },

    create: async (payload: CategoryRequestPayload): Promise<CategoryRequest> => {
        const response = await apiClient.post<CategoryRequest>('catalog/category-requests/', payload);
        return response.data;
    },
};
