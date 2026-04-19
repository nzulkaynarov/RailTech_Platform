import { apiClient } from './client';
import { PaginatedResponse } from './types';

export type SupportTicketStatus = 'OPEN' | 'IN_PROGRESS' | 'RESOLVED' | 'CLOSED';
export type SupportTicketPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT';
export type SupportTicketCategory =
    | 'BUG'
    | 'QUESTION'
    | 'BILLING'
    | 'FEATURE'
    | 'OTHER';

export interface SupportTicket {
    id: number;
    subject: string;
    description: string;
    category: SupportTicketCategory;
    priority: SupportTicketPriority;
    status: SupportTicketStatus;
    created_by: number | null;
    created_by_email: string;
    created_by_full_name: string;
    company: number | null;
    company_name: string;
    assigned_to: number | null;
    assigned_to_email: string;
    messages_count: number;
    created_at: string;
    updated_at: string;
    resolved_at: string | null;
}

export interface SupportTicketMessage {
    id: number;
    ticket: number;
    text: string;
    is_internal: boolean;
    author: number | null;
    author_email: string;
    author_full_name: string;
    author_is_admin: boolean;
    created_at: string;
}

export interface SupportTicketListParams {
    search?: string;
    status?: SupportTicketStatus | '';
    priority?: SupportTicketPriority | '';
    category?: SupportTicketCategory | '';
    ordering?: string;
    page?: number;
    page_size?: number;
}

export interface CreateTicketPayload {
    subject: string;
    description: string;
    category: SupportTicketCategory;
    priority: SupportTicketPriority;
}

const RESOURCE = 'support/tickets/';

export const supportApi = {
    listTickets: async (params?: SupportTicketListParams) => {
        const response = await apiClient.get<PaginatedResponse<SupportTicket>>(
            RESOURCE,
            { params },
        );
        return response.data;
    },
    getTicket: async (id: number) => {
        const response = await apiClient.get<SupportTicket>(`${RESOURCE}${id}/`);
        return response.data;
    },
    createTicket: async (payload: CreateTicketPayload) => {
        const response = await apiClient.post<SupportTicket>(RESOURCE, payload);
        return response.data;
    },
    deleteTicket: async (id: number) => {
        await apiClient.delete(`${RESOURCE}${id}/`);
    },
    listMessages: async (ticketId: number) => {
        const response = await apiClient.get<SupportTicketMessage[]>(
            `${RESOURCE}${ticketId}/messages/`,
        );
        return response.data;
    },
    addMessage: async (
        ticketId: number,
        payload: { text: string; is_internal?: boolean },
    ) => {
        const response = await apiClient.post<SupportTicketMessage>(
            `${RESOURCE}${ticketId}/add-message/`,
            payload,
        );
        return response.data;
    },
    changeStatus: async (ticketId: number, status: SupportTicketStatus) => {
        const response = await apiClient.post<SupportTicket>(
            `${RESOURCE}${ticketId}/change-status/`,
            { status },
        );
        return response.data;
    },
    assign: async (ticketId: number, assignedTo?: number) => {
        const response = await apiClient.post<SupportTicket>(
            `${RESOURCE}${ticketId}/assign/`,
            assignedTo !== undefined ? { assigned_to: assignedTo } : {},
        );
        return response.data;
    },
};
