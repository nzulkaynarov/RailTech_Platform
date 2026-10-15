import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  emailTemplatesApi,
  type EmailTemplateDraft,
} from '@/api/emailTemplatesApi';

const EMAIL_TEMPLATES_KEY = ['settings-email-templates'];

export const useEmailTemplates = () =>
  useQuery({
    queryKey: EMAIL_TEMPLATES_KEY,
    queryFn: () => emailTemplatesApi.list(),
    staleTime: 30_000,
  });

export const useCreateEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EmailTemplateDraft) => emailTemplatesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const useUpdateEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<EmailTemplateDraft> }) =>
      emailTemplatesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const useDeleteEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => emailTemplatesApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const usePreviewEmailTemplate = () =>
  useMutation({
    mutationFn: ({ id, context }: { id: number; context?: Record<string, unknown> }) =>
      emailTemplatesApi.preview(id, context),
  });

export const useTestSendEmailTemplate = () =>
  useMutation({
    mutationFn: ({
      id,
      toEmail,
      context,
    }: {
      id: number;
      toEmail: string;
      context?: Record<string, unknown>;
    }) => emailTemplatesApi.testSend(id, toEmail, context),
  });
