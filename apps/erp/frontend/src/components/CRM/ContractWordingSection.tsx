import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { contractsApi, wordingVariantsApi, type Contract } from '@/api/contractsApi';
import { translateApiError } from '@/lib/apiError';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

/**
 * E4 (playbook-канон Ironclad/DocuSign): менеджер отвечает на возражение юриста контрагента
 * ВЫБОРОМ заранее согласованной редакции пункта — для ЭТОГО договора, не трогая шаблон всей
 * компании. Свободного ввода нет намеренно (spec-wording-library-e4). Доступно стороне
 * продавца, пока договор не подписан ни одной из сторон.
 */
const CONTRACT_WORDING_FIELDS = [
  { field: 'contract_acceptance_text', labelKey: 'contractsPage.wording.acceptance' },
  { field: 'contract_liability_text', labelKey: 'contractsPage.wording.liability' },
  { field: 'contract_extra_terms_text', labelKey: 'contractsPage.wording.extraTerms' },
] as const;

const STANDARD = 'standard';

export function ContractWordingSection({ contract }: { contract: Contract }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const editable =
    contract.viewer_can_sign_manager && !contract.client_signed_at && !contract.manager_signed_at;

  const { data: variants = [] } = useQuery({
    queryKey: ['wording-variants'],
    queryFn: () => wordingVariantsApi.list(),
    enabled: editable,
    staleTime: 60_000,
  });

  const selectMut = useMutation({
    mutationFn: ({ field, variantId }: { field: string; variantId: number | null }) =>
      contractsApi.selectWording(contract.id, field, variantId),
    onSuccess: () => {
      toast.success(t('contractsPage.wording.changed'));
      void queryClient.invalidateQueries({ queryKey: ['contracts'] });
    },
    onError: (err) => toast.error(translateApiError(err)),
  });

  const byField = useMemo(() => {
    const map = new Map<string, typeof variants>();
    for (const variant of variants) {
      map.set(variant.field, [...(map.get(variant.field) ?? []), variant]);
    }
    return map;
  }, [variants]);

  if (!editable) return null;

  return (
    <div className="space-y-2">
      <Label>{t('contractsPage.wording.title')}</Label>
      <p className="text-xs text-muted-foreground">{t('contractsPage.wording.hint')}</p>
      {CONTRACT_WORDING_FIELDS.map(({ field, labelKey }) => {
        const options = byField.get(field) ?? [];
        const currentText = contract.wording_selections?.[field];
        const matched = options.find((variant) => variant.text === currentText);
        return (
          <div key={field} className="flex items-center justify-between gap-3">
            <span className="text-sm">{t(labelKey)}</span>
            <Select
              value={matched ? String(matched.id) : STANDARD}
              onValueChange={(value) =>
                selectMut.mutate({ field, variantId: value === STANDARD ? null : Number(value) })
              }
              disabled={selectMut.isPending}
            >
              <SelectTrigger className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={STANDARD}>{t('contractsPage.wording.standard')}</SelectItem>
                {options.map((variant) => (
                  <SelectItem key={variant.id} value={String(variant.id)}>
                    {variant.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      })}
    </div>
  );
}
