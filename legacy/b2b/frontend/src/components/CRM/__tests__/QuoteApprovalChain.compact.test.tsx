import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Quote } from '@/api/crmApi';
import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';
import { useSubmitQuoteForReview, useActOnApprovalStep, useRecallQuote } from '@/hooks/useCRM';

vi.mock('@/hooks/useCRM', () => ({
	useSubmitQuoteForReview: vi.fn(),
	useActOnApprovalStep: vi.fn(),
	useRecallQuote: vi.fn(),
}));

const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });

// A КП mid-approval: two steps, the first already approved, the second pending and actionable.
const pendingQuote = {
	id: 100,
	status_code: 'PENDING_APPROVAL',
	approval_steps: [
		{ id: 1, order: 0, participation: 'APPROVER', status: 'APPROVED', is_mandatory: false, can_act: false, approver_name: 'Иванов' },
		{ id: 2, order: 1, participation: 'HEAD', status: 'PENDING', is_mandatory: true, can_act: true, approver_name: 'Петров' },
	],
} as unknown as Quote;

describe('QuoteApprovalChain — compact variant', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		(useSubmitQuoteForReview as unknown as ReturnType<typeof vi.fn>).mockReturnValue(mkMutation());
		(useActOnApprovalStep as unknown as ReturnType<typeof vi.fn>).mockReturnValue(mkMutation());
		(useRecallQuote as unknown as ReturnType<typeof vi.fn>).mockReturnValue(mkMutation());
	});

	it('renders a status pill with the step progress and opens the Popover on click', async () => {
		renderWithProviders(<QuoteApprovalChain quote={pendingQuote} variant="compact" />);

		// Pill: status label + «шаг 1/2» (one of two steps decided).
		expect(screen.getByText('На согласовании')).toBeInTheDocument();
		expect(screen.getByText('шаг 1/2')).toBeInTheDocument();

		// The popover content (the step group + approvers) is not mounted until the pill is opened.
		expect(screen.queryByText('Руководитель')).toBeNull();

		fireEvent.click(screen.getByRole('button', { name: 'Открыть панель согласования' }));

		await waitFor(() => {
			expect(screen.getByText('Руководитель')).toBeInTheDocument();
		});
	});

	it('duplicates the actionable approve button next to the pill', () => {
		renderWithProviders(<QuoteApprovalChain quote={pendingQuote} variant="compact" />);

		// The current user can act on step 2 → an approve button is surfaced beside the pill.
		expect(screen.getByRole('button', { name: /Согласовать/ })).toBeInTheDocument();
	});

	it('renders nothing once the КП leaves the approval chain (e.g. SENT)', () => {
		const sent = { ...pendingQuote, status_code: 'SENT' } as unknown as Quote;
		const { container } = renderWithProviders(<QuoteApprovalChain quote={sent} variant="compact" />);
		expect(container).toBeEmptyDOMElement();
	});
});
