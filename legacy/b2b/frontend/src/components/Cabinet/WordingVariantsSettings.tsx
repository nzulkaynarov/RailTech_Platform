import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Plus, Trash2 } from 'lucide-react';

import { wordingVariantsApi } from '@/api/contractsApi';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

/**
 * E4 — библиотека согласованных редакций формулировок (playbook-канон): юрист заранее готовит
 * именованные варианты пункта, менеджер в договоре выбирает из них. Управляется тем же правом,
 * что формулировки D1 (settings.edit) — секция живёт рядом с ними.
 */
const FIELDS = [
  { code: 'contract_acceptance_text', labelKey: 'documentProfile.wording.contractAcceptance' },
  { code: 'contract_liability_text', labelKey: 'documentProfile.wording.contractLiability' },
  { code: 'contract_extra_terms_text', labelKey: 'documentProfile.wording.contractExtra' },
] as const;

export function WordingVariantsSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [field, setField] = useState<string>(FIELDS[0].code);
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');

  const { data: variants = [] } = useQuery({
    queryKey: ['wording-variants'],
    queryFn: () => wordingVariantsApi.list(),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['wording-variants'] });

  const createMut = useMutation({
    mutationFn: () => wordingVariantsApi.create({ field, title, text }),
    onSuccess: () => {
      toast.success(t('wordingVariants.created'));
      setTitle('');
      setText('');
      invalidate();
    },
    onError: (err) => toast.error(translateApiError(err)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => wordingVariantsApi.remove(id),
    onSuccess: invalidate,
    onError: (err) => toast.error(translateApiError(err)),
  });

  const fieldLabel = (code: string) =>
    t(FIELDS.find((entry) => entry.code === code)?.labelKey ?? code);

  return (
    <div className="space-y-3 border-t pt-4">
      <div>
        <h4 className="text-sm font-semibold text-foreground">{t('wordingVariants.title')}</h4>
        <p className="mt-0.5 text-xs text-muted-foreground">{t('wordingVariants.hint')}</p>
      </div>

      {variants.length > 0 && (
        <ul className="space-y-1.5">
          {variants.map((variant) => (
            <li key={variant.id} className="flex items-start justify-between gap-3 rounded-md border p-2">
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {variant.title}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {fieldLabel(variant.field)}
                  </span>
                </p>
                <p className="truncate text-xs text-muted-foreground">{variant.text}</p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t('common.delete')}
                onClick={() => deleteMut.mutate(variant.id)}
                disabled={deleteMut.isPending}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>{t('wordingVariants.field')}</Label>
          <Select value={field} onValueChange={setField}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {FIELDS.map((entry) => (
                <SelectItem key={entry.code} value={entry.code}>{t(entry.labelKey)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wv-title">{t('wordingVariants.name')}</Label>
          <Input
            id="wv-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t('wordingVariants.namePlaceholder')}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="wv-text">{t('wordingVariants.text')}</Label>
        <Textarea
          id="wv-text"
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={3}
        />
      </div>
      <Button
        size="sm"
        onClick={() => createMut.mutate()}
        disabled={createMut.isPending || !title.trim() || !text.trim()}
      >
        <Plus className="mr-2 h-4 w-4" />
        {t('wordingVariants.add')}
      </Button>
    </div>
  );
}
