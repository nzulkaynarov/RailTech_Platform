import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    supportApi,
    SupportTicketListParams,
    CreateTicketPayload,
    SupportTicketStatus,
} from '@/api/supportApi';

export const useSupportTickets = (params?: SupportTicketListParams) =>
    useQuery({
        queryKey: ['support-tickets', params],
        queryFn: () => supportApi.listTickets(params),
    });

export const useSupportTicket = (id: number | null) =>
    useQuery({
        queryKey: ['support-ticket', id],
        queryFn: () => supportApi.getTicket(id as number),
        enabled: !!id,
    });

export const useSupportTicketMessages = (id: number | null) =>
    useQuery({
        queryKey: ['support-ticket-messages', id],
        queryFn: () => supportApi.listMessages(id as number),
        enabled: !!id,
    });

export const useCreateSupportTicket = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload: CreateTicketPayload) =>
            supportApi.createTicket(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['support-tickets'] });
        },
    });
};

export const useAddSupportMessage = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({
            ticketId,
            text,
            isInternal,
        }: {
            ticketId: number;
            text: string;
            isInternal?: boolean;
        }) =>
            supportApi.addMessage(ticketId, {
                text,
                is_internal: isInternal,
            }),
        onSuccess: (_, { ticketId }) => {
            qc.invalidateQueries({ queryKey: ['support-ticket-messages', ticketId] });
            qc.invalidateQueries({ queryKey: ['support-ticket', ticketId] });
            qc.invalidateQueries({ queryKey: ['support-tickets'] });
        },
    });
};

export const useChangeSupportStatus = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({
            ticketId,
            status,
        }: {
            ticketId: number;
            status: SupportTicketStatus;
        }) => supportApi.changeStatus(ticketId, status),
        onSuccess: (_, { ticketId }) => {
            qc.invalidateQueries({ queryKey: ['support-ticket', ticketId] });
            qc.invalidateQueries({ queryKey: ['support-tickets'] });
        },
    });
};

export const useAssignSupportTicket = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({
            ticketId,
            assignedTo,
        }: {
            ticketId: number;
            assignedTo?: number;
        }) => supportApi.assign(ticketId, assignedTo),
        onSuccess: (_, { ticketId }) => {
            qc.invalidateQueries({ queryKey: ['support-ticket', ticketId] });
            qc.invalidateQueries({ queryKey: ['support-tickets'] });
        },
    });
};
