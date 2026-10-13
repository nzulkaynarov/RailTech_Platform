import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { catalogApi } from '@/api/catalogApi';
import { runAiJob } from '@/lib/aiJob';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';

export interface HSSuggestion {
  product_id: number;
  name: string;
  suggested_code: string;
  suggested_name: string;
  explanation: string;
}

/**
 * T4 (Avalara bulk classification): ИИ подбирает коды ТН ВЭД пакетом, человек ПОДТВЕРЖДАЕТ.
 * Механика перенесена из очереди «Номенклатуры» без изменений (R2 — единый реестр).
 */
export function useHsClassify(onApplied: () => void) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<HSSuggestion[] | null>(null);

  const run = async (productIds: number[]) => {
    setBusy(true);
    setSuggestions(null);
    try {
      const outcome = await runAiJob<{ results: HSSuggestion[] }>(() => catalogApi.classifyHSCodes(productIds));
      const withCodes = (outcome.results ?? []).filter((row) => row.suggested_code);
      setSuggestions(withCodes);
      if (withCodes.length === 0) toast.info(t('nomenclature.classify.nothing'));
    } catch (err) {
      // Честный тост (N2, M3): 429 AI_DAILY_CAP_REACHED и прочие коды доходили сюда как
      // безликое «не удалось» — показываем причину, когда бэкенд её назвал.
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.classify.failed'));
    } finally {
      setBusy(false);
    }
  };

  const applyAll = async () => {
    if (!suggestions?.length) return;
    try {
      const result = await catalogApi.applyHSCodes(
        suggestions.map((row) => ({ product_id: row.product_id, code: row.suggested_code })),
      );
      toast.success(t('nomenclature.classify.applied', { count: result.applied.length }));
      setSuggestions(null);
      onApplied();
      queryClient.invalidateQueries({ queryKey: ['products'] });
    } catch (err) {
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.classify.failed'));
    }
  };

  const reject = (productId: number) => {
    setSuggestions((rows) => rows?.filter((row) => row.product_id !== productId) ?? null);
  };

  return { busy, suggestions, run, applyAll, reject, cancel: () => setSuggestions(null) };
}
