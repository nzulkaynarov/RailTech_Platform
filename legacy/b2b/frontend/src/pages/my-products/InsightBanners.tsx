import { type ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { cn } from '@/lib/utils';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import {
  useCatalogCoverage,
  useDuplicateSuggestions,
  useMergeProducts,
  useReclassificationWorklist,
} from '@/hooks/useCatalog';
import type { Product } from '@/api/catalogApi';

/**
 * R2 (аудит §5.2): панели «покрытие» / «дубли» / «переклассификация» были тремя карточками
 * ПОД таблицей и уезжали за экран при непустом списке. Теперь это компактные сворачиваемые
 * баннеры НАД таблицей: одна строка-заголовок с числом, детали — по клику.
 */

function Banner({
  tone,
  title,
  children,
}: {
  tone: 'info' | 'warning';
  title: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className={cn(
          'rounded-lg border',
          tone === 'warning' ? 'border-warning/40 bg-warning/5' : 'border-info/40 bg-info/5',
        )}
      >
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm font-medium"
          >
            <span className="min-w-0 truncate">{title}</span>
            <ChevronDown
              className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')}
              aria-hidden="true"
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="flex flex-col gap-2 px-4 pb-3">{children}</div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

export function InsightBanners({ onFixReclass }: { onFixReclass: (product: Product) => void }) {
  const { t } = useTranslation();
  // N4: метрика направления (Ariba catalog spend) + подсказки дублей (система предлагает,
  // человек решает — Akeneo/Salesforce dedupe) + worklist переклассификации (SAP GTS).
  const { data: coverage } = useCatalogCoverage();
  const { data: duplicateData } = useDuplicateSuggestions();
  const { data: retiredCards } = useReclassificationWorklist();
  const mergeMut = useMergeProducts();
  const duplicateGroups = duplicateData?.groups ?? [];
  const retired = retiredCards ?? [];

  const showCoverage = Boolean(coverage && coverage.lines_total > 0);
  if (!showCoverage && duplicateGroups.length === 0 && retired.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {/* «Северная звезда» направления — доля строк КП по каталогу. Меряем строки, не число
          карточек: тысяча невостребованных ничего не стоит. */}
      {showCoverage && (
        <Banner tone="info" title={t('myProducts.coverageTitle', { percent: coverage!.percent })}>
          <p className="text-xs text-muted-foreground">
            {t('nomenclature.coverage', {
              with_product: coverage!.lines_with_product,
              total: coverage!.lines_total,
            })}
          </p>
        </Banner>
      )}

      {/* N4: вероятные дубли (точные ключи — бренд+артикул, ГОСТ, имя). Дубль уходит в архив,
          спрос и ссылки переезжают в выжившую — старейшую, на неё уже могут ссылаться строки КП. */}
      {duplicateGroups.length > 0 && (
        <Banner tone="warning" title={t('nomenclature.duplicates.title', { count: duplicateGroups.length })}>
          <p className="text-xs text-muted-foreground">{t('nomenclature.duplicates.hint')}</p>
          {duplicateGroups.map((group) =>
            group.duplicates.map((dup) => (
              <div key={`${group.survivor.id}-${dup.id}`} className="flex items-center justify-between gap-3">
                <div className="min-w-0 text-sm">
                  <span className="font-medium">{group.survivor.name}</span>
                  <span className="text-muted-foreground"> ← {dup.name}</span>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" size="sm" disabled={mergeMut.isPending}>
                      {t('nomenclature.duplicates.merge')}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t('nomenclature.duplicates.confirmTitle')}</AlertDialogTitle>
                      <AlertDialogDescription>
                        {t('nomenclature.duplicates.confirmBody', {
                          survivor: group.survivor.name,
                          duplicate: dup.name,
                        })}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{t('nomenclature.classify.cancel')}</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() =>
                          mergeMut.mutate(
                            { survivorId: group.survivor.id, duplicateId: dup.id },
                            {
                              onSuccess: () => toast.success(t('nomenclature.duplicates.merged')),
                              onError: (err) =>
                                toast.error(
                                  extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.publishFailed'),
                                ),
                            },
                          )
                        }
                      >
                        {t('nomenclature.duplicates.merge')}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            )),
          )}
        </Banner>
      )}

      {/* T2, паттерн SAP-переклассификации: автосинк закрыл код → карточка попадает СЮДА с
          конкретным действием, а не тихо наследует мёртвый код в новые КП. */}
      {retired.length > 0 && (
        <Banner tone="warning" title={t('nomenclature.reclass.title', { count: retired.length })}>
          <p className="text-xs text-muted-foreground">{t('nomenclature.reclass.hint')}</p>
          {retired.map((card) => (
            <div key={card.id} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{card.name}</div>
                <div className="text-xs text-muted-foreground">{t('nomenclature.reclass.code', { code: card.hs_code })}</div>
              </div>
              <Button variant="outline" size="sm" onClick={() => onFixReclass(card)}>
                {t('nomenclature.reclass.fix')}
              </Button>
            </div>
          ))}
        </Banner>
      )}
    </div>
  );
}
