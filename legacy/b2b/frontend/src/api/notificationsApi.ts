import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface Notification {
    id: number;
    title: string;
    message: string;
    type?: number | null;
    type_code?: string;
    type_name?: string;
    user?: number | null;
    deal?: number | null;
    is_read: boolean;
    link?: string;
    created_at: string;
}

export const notificationsApi = {
    getNotifications: async () => {
        const response = await apiClient.get<PaginatedResponse<Notification>>('notifications/');
        return response.data.results;
    },
    /**
     * Страница уведомлений вместе с признаком «есть ещё» — для кнопки «Показать ещё» в центре
     * уведомлений. Панель показывала только первую страницу, а кнопка под списком не делала
     * ничего: дальше первой страницы истории было не добраться.
     */
    getNotificationsPage: async (page: number) => {
        const response = await apiClient.get<PaginatedResponse<Notification>>('notifications/', {
            params: { page },
        });
        return { items: response.data.results, hasMore: Boolean(response.data.next) };
    },
    markAsRead: async (id: number) => {
        await apiClient.patch(`notifications/${id}/mark_read/`);
    },
    markAllAsRead: async () => {
        await apiClient.patch('notifications/mark_all_read/');
    }
};
