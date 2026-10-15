import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi, PurchaseActualPayload } from '@/api/financeApi';

/** M1-ERP-08 — отклонение маржи сделки (только с `quote.view_cost_margin`: без права запрос не идёт). */
export const marginDeviationKey = (dealId: number) => ['margin-deviation', dealId] as const;

export const useMarginDeviation = (dealId: number, enabled: boolean) => useQuery({
	queryKey: marginDeviationKey(dealId),
	queryFn: () => financeApi.getMarginDeviation(dealId),
	enabled: enabled && !!dealId,
});

export const useRecordPurchaseActual = (dealId: number) => {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (data: PurchaseActualPayload) => financeApi.recordPurchaseActual(dealId, data),
		onSuccess: (data) => {
			queryClient.setQueryData(marginDeviationKey(dealId), data);
			queryClient.invalidateQueries({ queryKey: ['timeline'] });
		},
	});
};

export const useRemovePurchaseActual = (dealId: number) => {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (currency: string) => financeApi.removePurchaseActual(dealId, currency),
		onSuccess: (data) => {
			queryClient.setQueryData(marginDeviationKey(dealId), data);
			queryClient.invalidateQueries({ queryKey: ['timeline'] });
		},
	});
};
