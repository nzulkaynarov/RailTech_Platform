import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Boxes, CheckCircle2, Loader2, PackagePlus } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { ResponsiveDataTable } from '@/components/ResponsiveDataTable';
import {
  useMyCandidates,
  usePublishProduct,
  useBulkPublishProducts,
  useReclassificationWorklist,
  useCatalogCoverage,
  useDuplicateSuggestions,
  useMergeProducts,
} from '@/hooks/useCatalog';
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
import { useAuthStore } from '@/store/authStore';
import { runAiJob } from '@/lib/aiJob';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import { catalogApi } from '@/api/catalogApi';
import { formatHSCode } from '@/components/Shared/HSCodeField';
import { useQueryClient } from '@tanstack/react-query';
import { ProductFormSheet } from './AdminCatalogPage';
import type { Product } from '@/api/catalogApi';

/**
 * Очередь наполнения номенклатуры продавца (волна A).
 *
 * До неё пункт меню «Номенклатура» открывал витрину ЧУЖОГО каталога с кнопкой «в корзину» —
 * то есть про покупку, а не про ведение своих товаров; завести карточку продавец не мог вовсе
 * (форма жила только в плоскости оператора), а опубликовать — тем более (право было у
 * платформы). При этом 90 из 98 строк КП шли мимо каталога.
 *
 * Эталон — Ariba/Coupa catalog enablement + Akeneo enrichment queue: позиции, которых нет в
 * каталоге, собираются в очередь, сортируются ПО СПРОСУ (сначала то, что окупится быстрее), и
 * карточка публикуется, когда заполнено обязательное — порог считается, а не назначается.
 */

type TabKey = 'DRAFT' | 'PUBLISHED';

/** Полнота словами: процент мотивирует, но действие подсказывает список недостающего. */
function CompletenessCell({ product, t }: { product: Product; t: (k: string, o?: Record<string, unknown>) => string }) {
  const report = product.completeness;
  if (!report) return <span className="text-muted-foreground">—</span>;
  if (report.is_publishable) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-success">
        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
        {t('nomenclature.readyToPublish')}
      </span>
    );
  }
  return (
    <div className="min-w-0">
      <div className="text-sm font-medium tabular-nums">{report.percent}%</div>
      <div className="truncate text-xs text-muted-foreground">
        {/* N4: подпись — по КОДУ требования на языке интерфейса (item.label с сервера был
            только русским: EN-продавец видел «missing: Код ТН ВЭД»). label — фолбэк на случай
            нового серверного требования, ещё не известного словарю. */}
        {t('nomenclature.missing')}:{' '}
        {report.missing.map((item) => t(`nomenclature.requirement.${item.code}`, { defaultValue: item.label })).join(', ')}
      </div>
    </div>
  );
}

// N2 (B1 аудита): «Открыть» ходит через onProductClick (параметризованный переход);
// onNavigate — только для валидных id реестра (CTA импорта в пустой очереди, N4).
export function NomenclatureQueuePage({
  onProductClick,
  onNavigate,
}: {
  onProductClick: (productId: string) => void;
  onNavigate: (target: string) => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>('DRAFT');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // «Дополнить» открывает ФОРМУ карточки прямо здесь, а не read-only витрину: тупик волны T1 —
  // очередь требовала «не хватает: Код ТН ВЭД», а вести пользователя было некуда. Тот же
  // ProductFormSheet, что у страницы каталога (одна форма — один опыт).
  const [editTarget, setEditTarget] = useState<Product | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const sellerCompanyId = useAuthStore((s) => s.user?.company?.id);
  const { data: rows, isLoading } = useMyCandidates(tab);
  const { data: retiredCards } = useReclassificationWorklist();
  // N4: метрика направления (Ariba catalog spend) + подсказки дублей (система предлагает,
  // человек решает — Akeneo/Salesforce dedupe).
  const { data: coverage } = useCatalogCoverage();
  const { data: duplicateData } = useDuplicateSuggestions();
  const mergeMut = useMergeProducts();
  const duplicateGroups = duplicateData?.groups ?? [];
  const publishOne = usePublishProduct();
  const publishMany = useBulkPublishProducts();
  const queryClient = useQueryClient();
  // T4 (Avalara bulk classification): ИИ подбирает коды пакетом, человек ПОДТВЕРЖДАЕТ.
  const [classifyBusy, setClassifyBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<
    { product_id: number; name: string; suggested_code: string; suggested_name: string; explanation: string }[] | null
  >(null);

  const classifySelected = async () => {
    setClassifyBusy(true);
    setSuggestions(null);
    try {
      const outcome = await runAiJob<{ results: typeof suggestions }>(() =>
        catalogApi.classifyHSCodes([...selected]),
      );
      const withCodes = (outcome.results ?? []).filter((row) => row.suggested_code);
      setSuggestions(withCodes);
      if (withCodes.length === 0) toast.info(t('nomenclature.classify.nothing'));
    } catch (err) {
      // Честный тост (N2, M3): 429 AI_DAILY_CAP_REACHED и прочие коды доходили сюда как
      // безликое «не удалось» — показываем причину, когда бэкенд её назвал.
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.classify.failed'));
    } finally {
      setClassifyBusy(false);
    }
  };

  const applySuggestions = async () => {
    if (!suggestions?.length) return;
    try {
      const result = await catalogApi.applyHSCodes(
        suggestions.map((row) => ({ product_id: row.product_id, code: row.suggested_code })),
      );
      toast.success(t('nomenclature.classify.applied', { count: result.applied.length }));
      setSuggestions(null);
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ['products'] });
    } catch (err) {
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.classify.failed'));
    }
  };

  const items = useMemo(() => rows ?? [], [rows]);
  // Кнопка публикации осмысленна только на табе черновиков (N2, M4): без фильтра по табу
  // она предлагала «опубликовать» уже опубликованные строки.
  const publishableSelected = useMemo(
    () => (tab === 'DRAFT' ? items.filter((p) => selected.has(p.id) && p.completeness?.is_publishable) : []),
    [items, selected, tab],
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const columns = [
    {
      id: 'select',
      header: '',
      cell: (p: Product) => (
        <Checkbox
          checked={selected.has(p.id)}
          onCheckedChange={() => toggle(p.id)}
          aria-label={t('nomenclature.selectRow', { name: p.name })}
        />
      ),
    },
    {
      id: 'name',
      header: t('nomenclature.columns.product'),
      cell: (p: Product) => (
        <div className="min-w-0">
          <div className="truncate font-medium">{p.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {p.source_deal ? t('nomenclature.fromRequest', { id: p.source_deal }) : p.sku}
          </div>
        </div>
      ),
    },
    {
      id: 'demand',
      header: t('nomenclature.columns.demand'),
      cell: (p: Product) => (
        <span className="tabular-nums">
          {p.demand_count ? t('nomenclature.askedTimes', { count: p.demand_count }) : '—'}
        </span>
      ),
    },
    {
      id: 'completeness',
      header: t('nomenclature.columns.completeness'),
      cell: (p: Product) => <CompletenessCell product={p} t={t} />,
    },
    {
      id: 'actions',
      header: '',
      cell: (p: Product) =>
        tab === 'DRAFT' ? (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditTarget(p);
                setEditOpen(true);
              }}
            >
              {t('nomenclature.enrich')}
            </Button>
            <Button
              size="sm"
              disabled={!p.completeness?.is_publishable || publishOne.isPending}
              onClick={() =>
                publishOne.mutate(p.id, {
                  onSuccess: () => toast.success(t('nomenclature.published', { name: p.name })),
                  onError: (err) =>
                    toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.publishFailed')),
                })
              }
            >
              {t('nomenclature.publish')}
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onProductClick(String(p.id))}>
            {t('nomenclature.open')}
          </Button>
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <Boxes className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">{t('nomenclature.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('nomenclature.subtitle')}</p>
        </div>
        {/* N4: «северная звезда» направления — доля строк КП по каталогу (Ariba catalog
            spend). Меряем строки, не число карточек: тысяча невостребованных ничего не стоит. */}
        {coverage && coverage.lines_total > 0 && (
          <div className="ml-auto rounded-lg border px-4 py-2 text-right">
            <div className="text-lg font-bold tabular-nums">{coverage.percent}%</div>
            <div className="text-xs text-muted-foreground">
              {t('nomenclature.coverage', {
                with_product: coverage.lines_with_product,
                total: coverage.lines_total,
              })}
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(['DRAFT', 'PUBLISHED'] as TabKey[]).map((key) => (
          <Button
            key={key}
            variant={tab === key ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setTab(key);
              setSelected(new Set());
            }}
          >
            {t(`nomenclature.tabs.${key}`)}
          </Button>
        ))}
        {selected.size > 0 && tab === 'DRAFT' && (
          <Button variant="outline" size="sm" className="ml-auto" disabled={classifyBusy} onClick={classifySelected}>
            {classifyBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {t('nomenclature.classify.run', { count: selected.size })}
          </Button>
        )}
        {publishableSelected.length > 0 && (
          <Button
            size="sm"
            disabled={publishMany.isPending}
            onClick={() =>
              publishMany.mutate(
                publishableSelected.map((p) => p.id),
                {
                  onSuccess: () => {
                    toast.success(t('nomenclature.publishedMany', { count: publishableSelected.length }));
                    setSelected(new Set());
                  },
                  onError: (err) =>
                    toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.publishFailed')),
                },
              )
            }
          >
            {publishMany.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {t('nomenclature.publishSelected', { count: publishableSelected.length })}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t(`nomenclature.tabs.${tab}`)}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            // Пустой экран объясняет, ОТКУДА здесь берутся строки, а не просто молчит:
            // кандидаты появляются сами после отправки КП с позициями вне каталога.
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <PackagePlus className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">{t(`nomenclature.empty.${tab}`)}</p>
              <p className="max-w-md text-xs text-muted-foreground">{t(`nomenclature.emptyHint.${tab}`)}</p>
              {/* N4: пустой экран ведёт к следующему шагу (Ariba: enablement-очередь всегда
                  предлагает действие), а не только объясняет, откуда берутся строки. */}
              {tab === 'DRAFT' && (
                <div className="flex gap-2 pt-1">
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditTarget(null);
                      setEditOpen(true);
                    }}
                  >
                    {t('nomenclature.emptyCta.create')}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => onNavigate('catalog-import')}>
                    {t('nomenclature.emptyCta.import')}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <ResponsiveDataTable
              columns={columns}
              rows={items}
              getRowId={(p: Product) => p.id}
              onRowClick={(p: Product) => {
                if (tab === 'DRAFT') {
                  setEditTarget(p);
                  setEditOpen(true);
                } else {
                  onProductClick(String(p.id));
                }
              }}
            />
          )}
        </CardContent>
      </Card>

      {suggestions && suggestions.length > 0 && (
        <Card className="border-info/40 bg-info/5">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('nomenclature.classify.title', { count: suggestions.length })}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">{t('nomenclature.classify.hint')}</p>
            {suggestions.map((row) => (
              <div key={row.product_id} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{row.name}</div>
                  <div className="text-xs text-muted-foreground">
                    <span className="font-mono font-semibold">{formatHSCode(row.suggested_code)}</span>
                    {row.explanation ? ` — ${row.explanation}` : ''}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSuggestions((rows) => rows?.filter((r) => r.product_id !== row.product_id) ?? null)}
                >
                  {t('nomenclature.classify.reject')}
                </Button>
              </div>
            ))}
            <div className="flex gap-2 pt-1">
              <Button size="sm" onClick={applySuggestions}>{t('nomenclature.classify.applyAll', { count: suggestions.length })}</Button>
              <Button variant="outline" size="sm" onClick={() => setSuggestions(null)}>{t('nomenclature.classify.cancel')}</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* N4: вероятные дубли (точные ключи — бренд+артикул, ГОСТ, имя). Система ПРЕДЛАГАЕТ,
          человек решает (Akeneo/Salesforce dedupe): дубль уходит в архив, спрос и ссылки
          переезжают в выжившую — старейшую, на неё уже могут ссылаться строки КП. */}
      {duplicateGroups.length > 0 && (
        <Card className="border-warning/40 bg-warning/5">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('nomenclature.duplicates.title', { count: duplicateGroups.length })}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
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
          </CardContent>
        </Card>
      )}

      {/* T2, паттерн SAP-переклассификации: автосинк закрыл код → карточка попадает СЮДА с
          конкретным действием, а не тихо наследует мёртвый код в новые КП. */}
      {(retiredCards?.length ?? 0) > 0 && (
        <Card className="border-warning/40 bg-warning/5">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('nomenclature.reclass.title', { count: retiredCards!.length })}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">{t('nomenclature.reclass.hint')}</p>
            {retiredCards!.map((card) => (
              <div key={card.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{card.name}</div>
                  <div className="text-xs text-muted-foreground">{t('nomenclature.reclass.code', { code: card.hs_code })}</div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setEditTarget(card);
                    setEditOpen(true);
                  }}
                >
                  {t('nomenclature.reclass.fix')}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <ProductFormSheet open={editOpen} onOpenChange={setEditOpen} target={editTarget} sellerCompanyId={sellerCompanyId} />

      {tab === 'DRAFT' && items.length > 0 && (
        <p className="text-xs text-muted-foreground">
          <Badge variant="secondary" className="mr-2">
            {t('nomenclature.whyTitle')}
          </Badge>
          {t('nomenclature.whyBody')}
        </p>
      )}
    </div>
  );
}

export default NomenclatureQueuePage;
