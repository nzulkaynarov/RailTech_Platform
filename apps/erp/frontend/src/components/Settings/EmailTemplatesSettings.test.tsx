import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { EmailTemplatesSettings } from '@/components/Settings/EmailTemplatesSettings';
import { renderWithProviders } from '@/test/renderWithProviders';

const {
  mockTemplates,
  createMutMock,
  updateMutMock,
  deleteMutMock,
  previewMutMock,
  testSendMutMock,
} = vi.hoisted(() => ({
  mockTemplates: [
    {
      id: 1,
      key: 'quote_sent',
      subject: 'Коммерческое предложение {{quote_number}}',
      html_body: '<p>Здравствуйте!</p>',
      text_body: 'Здравствуйте!',
      available_variables: 'quote_number, company_name',
      is_active: true,
      has_db_override: false,
    },
  ],
  createMutMock: vi.fn(),
  updateMutMock: vi.fn(),
  deleteMutMock: vi.fn(),
  previewMutMock: vi.fn(),
  testSendMutMock: vi.fn(),
}));

vi.mock('@/hooks/useEmailTemplates', () => ({
  useEmailTemplates: () => ({ data: mockTemplates, isLoading: false, isError: false }),
  useCreateEmailTemplate: () => ({ mutateAsync: createMutMock, isPending: false }),
  useUpdateEmailTemplate: () => ({ mutateAsync: updateMutMock, isPending: false }),
  useDeleteEmailTemplate: () => ({ mutateAsync: deleteMutMock, isPending: false }),
  usePreviewEmailTemplate: () => ({ mutateAsync: previewMutMock, isPending: false }),
  useTestSendEmailTemplate: () => ({ mutateAsync: testSendMutMock, isPending: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('EmailTemplatesSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('рендерит заголовок и список шаблонов', () => {
    renderWithProviders(<EmailTemplatesSettings />);

    expect(screen.getByText('Шаблоны писем')).toBeInTheDocument();
    expect(screen.getByText('quote_sent')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Новый шаблон/i })).toBeInTheDocument();
  });

  it('позволяет выбрать шаблон для просмотра и редактирования', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EmailTemplatesSettings />);

    const templateCard = screen.getByRole('button', { name: /quote_sent/i });
    await user.click(templateCard);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Коммерческое предложение {{quote_number}}')).toBeInTheDocument();
    });
  });

  it('переключается на форму создания нового шаблона', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EmailTemplatesSettings />);

    await user.click(screen.getByRole('button', { name: /Новый шаблон/i }));

    await waitFor(() => {
      expect(screen.getByText('Например, quote_sent')).toBeInTheDocument();
    });
  });
});
