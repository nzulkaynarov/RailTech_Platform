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
    markAsRead: async (id: number) => {
        await apiClient.patch(`notifications/${id}/mark_read/`);
    },
    markAllAsRead: async () => {
        await apiClient.patch('notifications/mark_all_read/');
    }
};
