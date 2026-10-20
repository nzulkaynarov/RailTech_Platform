import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { queryClient as appQueryClient } from '@/lib/queryClient';
import { useUserStore } from '@/store/userStore';
import type { Quote } from '@/api/crmApi';

/**
 * FIX-44 (F-7): предпросмотр согласования (`GET crm/quotes/{id}/approval-preview/`) под тем же
 * гейтом `quote.build`, что и отправка на согласование. У роли без права запрос не уходит —
 * раньше он падал 403, и глобальный обработчик ошибок чтения показывал тост «Недостаточно прав»
 * при каждом открытии КП. Хуки настоящие; мок — на уровне API-клиента; QueryClient — общий
 * клиент приложения, поэтому настоящий 403 дал бы тот же тост, что и в продукте.
 */
const { getQuoteApprovalPreview, toastError } = vi.hoisted(() => ({
	getQuoteApprovalPreview: vi.fn(),
	toastError: vi.fn(),
}));

vi.mock('@/api/crmApi', () => ({
	crmApi: { getQuoteApprovalPreview },
}));

vi.mock('sonner', () => ({
	toast: { success: vi.fn(), error: toastError, info: vi.fn(), warning: vi.fn() },
}));

import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';

const draftQuote = { id: 100, status_code: 'DRAFT', approval_steps: [] } as unknown as Quote;
const forbidden = Object.assign(new Error('Request failed with status code 403'), {
	response: { status: 403, data: { detail: 'You do not have permission to perform this action.', code: 'permission_denied' } },
});

const setPermissions = (permissions: string[]) =>
	useUserStore.setState({ capabilities: { permissions } });

describe('QuoteApprovalChain — предпросмотр согласования и право quote.build', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		appQueryClient.clear();
	});
	afterEach(() => {
		setPermissions([]);
		appQueryClient.clear();
	});

	it('роль без quote.build — запроса нет, тоста нет', async () => {
		setPermissions(['deal.manage']);
		// Если бы запрос всё же ушёл, сервер ответил бы 403 → тост из общего обработчика.
		getQuoteApprovalPreview.mockRejectedValue(forbidden);

		renderWithProviders(<QuoteApprovalChain quote={draftQuote} />, { queryClient: appQueryClient });
		// Пилюля статуса есть: смотреть цепочку можно и без права собирать КП.
		fireEvent.click(screen.getByRole('button', { name: /Открыть панель согласования/ }));
		await screen.findByText('Согласование КП');
		await new Promise((resolve) => setTimeout(resolve, 50));

		expect(getQuoteApprovalPreview).not.toHaveBeenCalled();
		expect(toastError).not.toHaveBeenCalled();
	});

	it('пустой список прав («Наблюдатель») — запроса тоже нет', async () => {
		setPermissions([]);
		getQuoteApprovalPreview.mockRejectedValue(forbidden);

		renderWithProviders(<QuoteApprovalChain quote={draftQuote} />, { queryClient: appQueryClient });
		await new Promise((resolve) => setTimeout(resolve, 50));

		expect(getQuoteApprovalPreview).not.toHaveBeenCalled();
		expect(toastError).not.toHaveBeenCalled();
	});

	it('роль с quote.build — предпросмотр запрашивается и показывается', async () => {
		setPermissions(['quote.build']);
		getQuoteApprovalPreview.mockResolvedValue({
			would_auto_approve: false, below_floor: false,
			steps: [{ name: 'Петров', role: 'Руководитель', participation_label: 'Согласующий' }],
		});

		renderWithProviders(<QuoteApprovalChain quote={draftQuote} />, { queryClient: appQueryClient });
		fireEvent.click(screen.getByRole('button', { name: /Открыть панель согласования/ }));

		await waitFor(() => expect(getQuoteApprovalPreview).toHaveBeenCalledWith(100));
		expect(await screen.findByText('Петров')).toBeInTheDocument();
		expect(toastError).not.toHaveBeenCalled();
	});

	it('КП не в черновике — предпросмотр не запрашивается и с правом', async () => {
		setPermissions(['quote.build']);
		const pending = { id: 100, status_code: 'PENDING_APPROVAL', approval_steps: [] } as unknown as Quote;

		renderWithProviders(<QuoteApprovalChain quote={pending} />, { queryClient: appQueryClient });
		await new Promise((resolve) => setTimeout(resolve, 50));

		expect(getQuoteApprovalPreview).not.toHaveBeenCalled();
	});
});
