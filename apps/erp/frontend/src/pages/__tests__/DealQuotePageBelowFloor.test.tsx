import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote } from '@/api/crmApi';

/**
 * T1 (spec-quote-ideal §5) — the S7a below-floor justification FRONTEND flow.
 *
 * `send_to_client` demands a written justification when the КП sits under the company
 * margin floor. The frontend has TWO distinct cost-visibility paths into the same
 * SendQuoteDialog, and only the first one is obvious:
 *
 *   (a) sender WITH cost/margin rights — `quote.economics.below_floor` is visible, so the
 *       justification field is shown PROACTIVELY and an empty/whitespace reason must block
 *       Confirm before a request is ever made;
 *   (b) sender WITHOUT cost rights — the serializer cost-gates `economics` to `null`, so the
 *       page cannot know it is below the floor. The first send goes out bare, the backend
 *       answers 400 BELOW_FLOOR_JUSTIFICATION_REQUIRED, and `extractApiErrorCode` flips
 *       `justificationRequired` so the dialog RE-RENDERS with the field for a retry.
 *
 * Path (b) is why a seller without margin visibility is not left stuck on a dead Send button.
 * A third assertion guards the confidentiality invariant: that sender must never see
 * margin/cost figures in the dialog.
 */

const sendMutateAsync = vi.fn();
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useDeal: () => ({ data: serverDeal, isLoading: false, isError: false, refetch: vi.fn() }),
	useSendQuoteToClient: () => ({ mutateAsync: sendMutateAsync, isPending: false }),
	// Wave B2 — the send composer lets the seller adjust the КП validity; not exercised here.
	useUpdateQuoteSettings: () => ({ mutate: vi.fn(), isPending: false }),
	useTakeAndPrepareQuote: () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false }),
}));

// Seller is fully entitled — the send-gate is not what this spec covers.
vi.mock('@/hooks/useQuoteSendGate', () => ({
	useQuoteSendGate: () => ({ isSeller: true, blocked: false, reason: null, errorCode: null }),
}));

// Heavy children of the workspace aren't under test — stub them so the page renders
// in isolation and the dialog is the only interactive surface.
vi.mock('@/components/QuoteBuilder/QuoteBuilderGrid', () => ({ QuoteBuilderGrid: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteApprovalChain', () => ({ QuoteApprovalChain: () => null }));
vi.mock('@/components/CRM/QuoteSendGateBanner', () => ({ QuoteSendGateBanner: () => null }));
vi.mock('@/components/Sourcing/DealChatPanel', () => ({ DealChatPanel: () => null }));
vi.mock('@/components/CRM/GenerateContractDialog', () => ({ GenerateContractDialog: () => null }));

vi.mock('sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

// Import AFTER the mocks are registered.
import { DealQuotePage } from '@/pages/DealQuotePage';

/** Axios-shaped rejection — SendQuoteDialog and extractApiErrorCode both read
 *  `response.data.detail`, which is the project's canonical error shape. */
function apiError(code: string) {
	return { response: { status: 400, data: { detail: code } } };
}

/**
 * READY_TO_SEND КП (the only status whose Send button is enabled).
 * `economics: null` models a sender WITHOUT cost/margin rights — that is exactly what
 * the serializer returns when `quote.view_cost_margin` is absent, and it is the state
 * that makes path (b) reachable.
 */
function makeDeal(economics: Quote['economics']): Deal {
	const quote = {
		id: 100,
		deal: 42,
		version: 1,
		status: 1,
		status_code: 'READY_TO_SEND',
		status_name: 'Готово к отправке',
		items: [],
		economics,
	} as unknown as Quote;
	return {
		id: 42,
		title: 'Тестовая заявка',
		stage_code: 'CALCULATING',
		stage_name: 'Расчёт',
		notes: '',
		active_quote: quote,
	} as unknown as Deal;
}

/** Economics payload for a sender WITH cost rights, sitting under the margin floor. */
const BELOW_FLOOR_ECONOMICS = {
	below_floor: true,
	below_cost: false,
	gross_margin_percent: '4.20',
	target_margin_percent: '15.00',
	min_margin_percent: '15',
	total_cost: '960000.00',
} as unknown as Quote['economics'];

/** Open the send-confirm dialog from the toolbar and return the dialog element.
 *  The toolbar button and the dialog's Confirm share the same label, so every
 *  later query MUST be scoped with `within(dialog)` or it matches both. */
async function openSendDialog(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
	await user.click(screen.getByRole('button', { name: /Отправить КП/i }));
	return screen.findByRole('dialog');
}

beforeEach(() => {
	vi.clearAllMocks();
	sendMutateAsync.mockReset();
});

describe('DealQuotePage — S7a below-floor justification (path a: sender WITH cost rights)', () => {
	it('shows the justification field proactively and blocks Confirm until it is non-empty', async () => {
		serverDeal = makeDeal(BELOW_FLOOR_ECONOMICS);
		sendMutateAsync.mockResolvedValue({});
		const user = userEvent.setup();

		renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
		const dialog = await openSendDialog(user);

		// below_floor is visible → the margin-below-floor warning line and a REQUIRED reason field.
		expect(within(dialog).getByText(/ниже порога/i)).toBeInTheDocument();
		const reason = within(dialog).getByLabelText(/Обоснование отправки ниже минимальной маржи/i);
		expect(reason).toBeInTheDocument();

		const confirm = within(dialog).getByRole('button', { name: /Отправить КП/i });
		expect(confirm).toBeDisabled();

		// Whitespace is not a justification — `reason.trim()` must still block the send.
		await user.type(reason, '   ');
		expect(confirm).toBeDisabled();
		expect(sendMutateAsync).not.toHaveBeenCalled();

		// Real text unlocks Confirm and the justification reaches the mutation.
		await user.clear(reason);
		await user.type(reason, 'Стратегическая скидка, согласовано с директором');
		await waitFor(() => expect(confirm).toBeEnabled());
		await user.click(confirm);

		await waitFor(() => expect(sendMutateAsync).toHaveBeenCalledTimes(1));
		expect(sendMutateAsync).toHaveBeenCalledWith({
			id: 100,
			justification: 'Стратегическая скидка, согласовано с директором',
		});
	});
});

describe('DealQuotePage — S7a below-floor justification (path b: sender WITHOUT cost rights)', () => {
	it('re-prompts with the justification field after the backend returns BELOW_FLOOR_JUSTIFICATION_REQUIRED', async () => {
		// economics === null → the page cannot know the КП is below the floor.
		serverDeal = makeDeal(null);
		sendMutateAsync
			.mockRejectedValueOnce(apiError('BELOW_FLOOR_JUSTIFICATION_REQUIRED'))
			.mockResolvedValueOnce({});
		const user = userEvent.setup();

		renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
		const dialog = await openSendDialog(user);

		// First render: no cost visibility (economics null) → margin hidden, NO justification
		// field, and the send button is live.
		expect(
			within(dialog).queryByLabelText(/Обоснование отправки ниже минимальной маржи/i),
		).not.toBeInTheDocument();
		expect(within(dialog).getByText(/Маржа скрыта/i)).toBeInTheDocument();

		const confirm = within(dialog).getByRole('button', { name: /Отправить КП/i });
		expect(confirm).toBeEnabled();

		// Bare send → backend rejects with the below-floor code.
		await user.click(confirm);
		await waitFor(() => expect(sendMutateAsync).toHaveBeenCalledTimes(1));
		expect(sendMutateAsync).toHaveBeenCalledWith({ id: 100, justification: undefined });

		// The dialog STAYS OPEN (the error was re-thrown) and now shows the field — this is
		// the whole point of path (b): the seller is not left stuck, they can retry with text.
		const reason = await within(dialog).findByLabelText(/Обоснование отправки ниже минимальной маржи/i);

		// And it is now REQUIRED — the retry cannot go out bare a second time.
		const retryConfirm = within(dialog).getByRole('button', { name: /Отправить КП/i });
		await waitFor(() => expect(retryConfirm).toBeDisabled());

		await user.type(reason, 'Клиент стратегический, одобрено руководителем');
		await waitFor(() => expect(retryConfirm).toBeEnabled());
		await user.click(retryConfirm);

		await waitFor(() => expect(sendMutateAsync).toHaveBeenCalledTimes(2));
		expect(sendMutateAsync).toHaveBeenNthCalledWith(2, {
			id: 100,
			justification: 'Клиент стратегический, одобрено руководителем',
		});
	});

	it('never leaks margin or cost figures to a sender without cost rights', async () => {
		serverDeal = makeDeal(null);
		sendMutateAsync.mockRejectedValue(apiError('BELOW_FLOOR_JUSTIFICATION_REQUIRED'));
		const user = userEvent.setup();

		renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
		const dialog = await openSendDialog(user);

		// Drive it into the re-prompted state — the state that carries the MOST copy, and
		// therefore the likeliest place for a margin figure to slip through.
		await user.click(within(dialog).getByRole('button', { name: /Отправить КП/i }));
		await within(dialog).findByLabelText(/Обоснование отправки ниже минимальной маржи/i);

		// Confidentiality invariant: the dialog explains WHAT is required, never the numbers.
		// These are the values a cost-entitled sender would see on the economics rail.
		const text = dialog.textContent ?? '';
		expect(text).not.toMatch(/4[.,]20/);
		expect(text).not.toMatch(/15[.,]00/);
		expect(text).not.toMatch(/960\s?000/);
		// No margin/cost vocabulary either — «минимальной маржи» in the prompt is a policy
		// reference, not a figure, so we assert on the numeric leak plus the cost label.
		expect(text).not.toMatch(/Себестоимость/i);
		expect(text).not.toMatch(/Валовая маржа/i);
	});
});
