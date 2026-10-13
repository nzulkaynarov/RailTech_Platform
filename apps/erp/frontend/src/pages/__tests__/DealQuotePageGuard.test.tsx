import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal } from '@/api/crmApi';
import { DealQuotePage } from '@/pages/DealQuotePage';
import { useDeal, useSendQuoteToClient } from '@/hooks/useCRM';

/**
 * WP-D — in-app navigation guard. When the builder reports unsaved edits, the Back
 * button must open a confirm dialog instead of leaving immediately; with no unsaved
 * edits it navigates straight back.
 */
vi.mock('@/hooks/useCRM', () => ({
	useDeal: vi.fn(),
	useSendQuoteToClient: vi.fn(),
	useTakeAndPrepareQuote: () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false }),
}));

// The builder is stubbed to a button that flips the dirty signal on demand.
vi.mock('@/components/QuoteBuilder/QuoteBuilderGrid', () => ({
	QuoteBuilderGrid: ({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) => (
		<button type="button" onClick={() => onDirtyChange?.(true)}>make-dirty</button>
	),
}));
vi.mock('@/components/CRM/QuoteApprovalChain', () => ({ QuoteApprovalChain: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/Sourcing/DealChatPanel', () => ({ DealChatPanel: () => null }));
vi.mock('@/components/CRM/GenerateContractDialog', () => ({ GenerateContractDialog: () => null }));
// Wave B2 — the unified send composer + post-send panel are stubbed; this spec is only the nav guard.
vi.mock('@/components/CRM/SendQuoteDialog', () => ({ SendQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteSentPanel', () => ({ QuoteSentPanel: () => null }));

const setHook = (hook: unknown, value: unknown) => { (hook as Mock).mockReturnValue(value); };
const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });

const deal = {
	id: 7,
	title: 'Заявка на рельсы',
	stage_code: 'CALCULATING',
	stage_name: 'Расчёт',
	notes: '',
	active_quote: { id: 200, status_code: 'DRAFT' },
} as unknown as Deal;

describe('DealQuotePage — unsaved-changes navigation guard', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		setHook(useDeal, { data: deal, isLoading: false, isError: false, refetch: vi.fn() });
		setHook(useSendQuoteToClient, mkMutation());
	});

	it('navigates back immediately when there are no unsaved changes', async () => {
		const user = userEvent.setup();
		const onBack = vi.fn();
		renderWithProviders(<DealQuotePage dealId={7} onBack={onBack} />);

		await user.click(screen.getByRole('button', { name: 'Назад' }));

		expect(onBack).toHaveBeenCalledTimes(1);
		expect(screen.queryByText('Есть несохранённые изменения')).toBeNull();
	});

	it('opens a confirm dialog (and defers onBack) when there are unsaved changes', async () => {
		const user = userEvent.setup();
		const onBack = vi.fn();
		renderWithProviders(<DealQuotePage dealId={7} onBack={onBack} />);

		// Flip the dirty signal via the stubbed builder, then try to leave.
		await user.click(screen.getByRole('button', { name: 'make-dirty' }));
		await user.click(screen.getByRole('button', { name: 'Назад' }));

		await waitFor(() => {
			expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
		});
		// onBack is deferred until the seller confirms.
		expect(onBack).not.toHaveBeenCalled();

		// Confirming leaves for real.
		await user.click(screen.getByRole('button', { name: 'Уйти без сохранения' }));
		expect(onBack).toHaveBeenCalledTimes(1);
	});
});
