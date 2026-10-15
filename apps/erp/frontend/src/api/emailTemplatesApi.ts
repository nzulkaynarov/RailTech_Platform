import { apiClient } from './client';

export type EmailTemplateKey =
  | 'setup_password'
  | 'invite_member'
  | 'kyc_verified'
  | 'quote_sent'
  | 'reset_password'
  | 'role_application_approved'
  | 'role_application_rejected';

export interface EmailTemplate {
  id: number;
  key: string;
  subject: string;
  html_body: string;
  text_body: string;
  available_variables: string;
  is_active: boolean;
  updated_by: number | null;
  updated_by_email: string | null;
  updated_at: string | null;
}

export interface EmailTemplateDraft {
  key: string;
  subject: string;
  html_body: string;
  text_body: string;
  available_variables?: string;
  is_active?: boolean;
}

export interface EmailTemplatePreview {
  key: string;
  subject: string;
  text_body: string;
  html_body: string;
  context_used?: Record<string, unknown>;
}

export interface EmailTemplateTestSendResult {
  status: 'SENT' | 'FAILED' | 'UNKNOWN';
  email_log_id: number | null;
  to_email: string;
}

export const emailTemplatesApi = {
  list: async (): Promise<EmailTemplate[]> => {
    const res = await apiClient.get<EmailTemplate[] | { results: EmailTemplate[] }>('settings/email-templates/');
    return Array.isArray(res.data) ? res.data : res.data.results;
  },
  create: async (data: EmailTemplateDraft): Promise<EmailTemplate> => {
    const res = await apiClient.post<EmailTemplate>('settings/email-templates/', data);
    return res.data;
  },
  update: async (id: number, data: Partial<EmailTemplateDraft>): Promise<EmailTemplate> => {
    const res = await apiClient.patch<EmailTemplate>(`settings/email-templates/${id}/`, data);
    return res.data;
  },
  remove: async (id: number): Promise<void> => {
    await apiClient.delete(`settings/email-templates/${id}/`);
  },
  preview: async (id: number, context?: Record<string, unknown>): Promise<EmailTemplatePreview> => {
    const res = await apiClient.post<EmailTemplatePreview>(
      `settings/email-templates/${id}/preview/`,
      { context },
    );
    return res.data;
  },
  testSend: async (
    id: number,
    toEmail: string,
    context?: Record<string, unknown>,
  ): Promise<EmailTemplateTestSendResult> => {
    const res = await apiClient.post<EmailTemplateTestSendResult>(
      `settings/email-templates/${id}/test-send/`,
      { to_email: toEmail, context },
    );
    return res.data;
  },
};
