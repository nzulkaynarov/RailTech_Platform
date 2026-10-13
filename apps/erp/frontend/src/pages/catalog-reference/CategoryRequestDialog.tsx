import { type FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useSubmitCategoryRequest } from '@/hooks/useCategoryRequests';
import type { Category } from '@/api/catalogApi';
import { translateApiError } from '@/lib/apiError';

/** Значение «на верхний уровень»: `Select` не принимает пустую строку как value. */
const TOP_LEVEL = 'top';

interface CategoryRequestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Категории верхнего уровня — «куда поместить» новую ветку. */
  parents: Category[];
}

/**
 * «Предложить категорию» (R6, D7) — обращение к платформе вместо тупика.
 *
 * Эталон — Google Merchant Center: таксономия площадки фиксирована (по ней идёт навигация,
 * фасеты и подбор ТН ВЭД), и когда подходящей категории нет, продавец обращается к площадке,
 * а не ломает классификатор. Заявка НЕ гейт: карточка заводится и правится без неё
 * (PRODUCT RULE 2 — трение убираем, не добавляем).
 */
export function CategoryRequestDialog({ open, onOpenChange, parents }: CategoryRequestDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [parent, setParent] = useState<string>(TOP_LEVEL);
  const [justification, setJustification] = useState('');
  const submitMut = useSubmitCategoryRequest();

  const canSubmit = name.trim().length > 0 && !submitMut.isPending;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    try {
      await submitMut.mutateAsync({
        proposed_name: name.trim(),
        parent: parent === TOP_LEVEL ? null : Number(parent),
        justification: justification.trim() || undefined,
      });
      toast.success(t('catalogReference.request.success'));
      onOpenChange(false);
      setName('');
      setParent(TOP_LEVEL);
      setJustification('');
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!submitMut.isPending) onOpenChange(next); }}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{t('catalogReference.request.title')}</DialogTitle>
            <DialogDescription>{t('catalogReference.request.description')}</DialogDescription>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="category-request-name">{t('catalogReference.request.nameLabel')} *</Label>
              <Input
                id="category-request-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('catalogReference.request.namePlaceholder')}
                maxLength={255}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="category-request-parent">{t('catalogReference.request.parentLabel')}</Label>
              <Select value={parent} onValueChange={setParent}>
                <SelectTrigger id="category-request-parent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={TOP_LEVEL}>{t('catalogReference.request.parentTopLevel')}</SelectItem>
                  {parents.map((category) => (
                    <SelectItem key={category.id} value={String(category.id)}>{category.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="category-request-why">{t('catalogReference.request.justificationLabel')}</Label>
              <Textarea
                id="category-request-why"
                value={justification}
                onChange={(event) => setJustification(event.target.value)}
                placeholder={t('catalogReference.request.justificationPlaceholder')}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitMut.isPending}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
              {t('common.send')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default CategoryRequestDialog;
