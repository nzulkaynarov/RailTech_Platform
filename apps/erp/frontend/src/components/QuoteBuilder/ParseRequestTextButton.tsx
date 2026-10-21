import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Loader2, Sparkles } from 'lucide-react';
import { crmApi } from '@/api/crmApi';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';

/**
 * FIX-67 — «Разобрать текст в строки (ИИ)» для заявки словами (без списка позиций).
 *
 * Текст заявки сервер берёт со сделки сам; результат — строки в КП, которые продавец проверяет в сетке.
 * Без ИИ / LiteLLM кнопка не ломается: понятный текст «ИИ недоступен, наберите строки вручную», а не 500
 * и не «Неизвестная ошибка» — ручной набор строк по тексту рядом работает всегда.
 */
const AI_UNAVAILABLE_CODES = new Set(['AI_DISABLED', 'AI_EXTRACT_FAILED', 'AI_BUDGET_EXCEEDED', 'AI_JOB_TIMEOUT']);

export function ParseRequestTextButton({ quoteId }: { quoteId: number }) {
	const { t } = useTranslation();
	const queryClient = useQueryClient();
	const [busy, setBusy] = useState(false);

	const parse = async () => {
		setBusy(true);
		try {
			const result = await crmApi.parseRequestText(quoteId);
			await queryClient.invalidateQueries({ queryKey: ['quote-items'] });
			await queryClient.invalidateQueries({ queryKey: ['deals'] });
			if (result.added > 0) {
				toast.success(t('requestText.added', { count: result.added }));
				if (result.truncated) toast.warning(t('requestText.truncated'));
			} else {
				toast.warning(t('requestText.none'));
			}
		} catch (e) {
			const code = extractApiErrorCode(e);
			toast.error(code && AI_UNAVAILABLE_CODES.has(code) ? t('requestText.aiUnavailable') : translateApiError(e));
		} finally {
			setBusy(false);
		}
	};

	return (
		<Button type="button" size="sm" variant="outline" onClick={parse} disabled={busy}>
			{busy
				? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />
				: <Sparkles className="mr-1.5 h-4 w-4" aria-hidden="true" />}
			{busy ? t('requestText.parsing') : t('requestText.parse')}
		</Button>
	);
}
