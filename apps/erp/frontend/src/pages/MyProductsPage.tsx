import { useEffect, useMemo, useState } from 'react'; import { useTranslation } from 'react-i18next'; import { Boxes, Loader2, PackagePlus, Plus, SearchX, Upload } from 'lucide-react'; import { toast } from 'sonner'; import { useQueryClient } from '@tanstack/react-query';  import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'; import { Checkbox } from '@/components/ui/checkbox'; import { Skeleton } from '@/components/ui/skeleton'; import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'; import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable'; import { Pager, Toolbar } from '@/components/DataTable';
import { useListParams } from '@/components/DataTable/listParams';
import { useDraftState } from '@/hooks/useDraftState';
import { ErrorState } from '@/pages/shared/PageShell';
import { getDomainLabelKey } from '@/config/domainConfig';
import { useBulkArchiveProducts, useBulkPublishProducts, useDomainTypes, useProductsPage } from '@/hooks/useCatalog';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import { catalogApi } from '@/api/catalogApi';
import type { Product, ProductListParams } from '@/api/catalogApi';

import { MY_PRODUCTS_TABS, TAB_LIST_PARAMS, type MyProductsTabKey } from './my-products/tabs';
import { useTabCount } from './my-products/useTabCount';
import { useHsClassify } from './my-products/useHsClassify';
import { CompletenessCell } from './my-products/CompletenessCell';
import { ClassifySuggestionsCard } from './my-products/ClassifySuggestionsCard';
import { InsightBanners } from './my-products/InsightBanners';
import { RowActions } from './my-products/RowActions';

/**
 * ЕДИНЫЙ реестр «Мои товары» (волна R2, аудит §5.2) — эволюция очереди «Номенклатуры».
 *
 * До R2 у продавца было ДВА реестра одного каталога (очередь наполнения и «Каталог»), архив
 * был невидим вовсе (D10 «чёрная дыра»), а панели дублей/покрытия уезжали за экран. Эталон —
 * Akeneo/Shopify Products: один список, статус — таб, серверный поиск/пагинация, bulk-действия.
 * Кандидаты из заявок сортируются ПО СПРОСУ (Ariba enablement: сначала то, что окупится).
 */

/** Пустые состояния по табам: тексты кандидатов/опубликованного уже жили в nomenclature.*. */
const EMPTY_KEYS: Record<MyProductsTabKey, { title: string; hint: string }> = {
  CANDIDATES: { title: 'nomenclature.empty.DRAFT', hint: 'nomenclature.emptyHint.DRAFT' },
  DRAFTS: { title: 'myProducts.empty.DRAFTS', hint: 'myProducts.emptyHint.DRAFTS' },
  PUBLISHED: { title: 'nomenclature.empty.PUBLISHED', hint: 'nomenclature.emptyHint.PUBLISHED' },
  ARCHIVED: { title: 'myProducts.empty.ARCHIVED', hint: 'myProducts.emptyHint.ARCHIVED' },
};

export function MyProductsPage({
  onProductClick,
  onNavigate,
}: {
  onProductClick?: (productId: string) => void;
  onNavigate?: (page: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState<MyProductsTabKey>('CANDIDATES');
  const queryClient = useQueryClient();

  // R1 («правда в списках»): серверная постраничка + поиск + фильтр направления — тот же
  // useListParams/Toolbar/Pager, что у остальных реестров.
  const {
    searchInput, setSearchInput, search,
    filters, setFilter,
    ordering, toggleOrdering,
    page, setPage, pageSize,
  } = useListParams(['domain'] as const, { urlKey: 'my-products' });
  const { data: domainTypes = [] } = useDomainTypes();
  const domainFilter = filters.domain !== 'all' ? filters.domain : undefined;
  const isDraftLike = tab === 'CANDIDATES' || tab === 'DRAFTS';

  const queryParams: ProductListParams = {
    mine: true,
    ...TAB_LIST_PARAMS[tab],
    search: search || undefined,
    domain_type: domainFilter,
    // Кандидаты по умолчанию идут СОСТАВНЫМ порядком (спрос → дата запроса → имя): одним
    // полем `ordering` тай-брейкеры не выразить. Как только продавец сам ткнул в заголовок
    // колонки — порядок его, и составной уступает.
    ordering: ordering || undefined,
    order: !ordering && tab === 'CANDIDATES' ? 'demand' : undefined,
    page,
    page_size: pageSize,
  };
  const { data: pageData, isLoading, isError, refetch } = useProductsPage(queryParams);
  const total = pageData?.count ?? 0;

  // Бейджи табов — серверный `count` дешёвым запросом page_size=1 (без поиска/фильтров:
  // бейдж отвечает «сколько всего в состоянии», как счётчики статусов Shopify).
  const tabCounts: Record<MyProductsTabKey, number | undefined> = {
    CANDIDATES: useTabCount(TAB_LIST_PARAMS.CANDIDATES),
    DRAFTS: useTabCount(TAB_LIST_PARAMS.DRAFTS),
    PUBLISHED: useTabCount(TAB_LIST_PARAMS.PUBLISHED),
    ARCHIVED: useTabCount(TAB_LIST_PARAMS.ARCHIVED),
  };

  // Наполнять можно до верификации, публиковать — нет. Предупреждаем ЗАРАНЕЕ (Amazon Seller
  // Central); на снятие с публикации / архив / восстановление гейт НЕ распространяется.
  const publishMany = useBulkPublishProducts();
  const archiveMany = useBulkArchiveProducts();
  const classify = useHsClassify(() => setSelected(new Set()));
  const [bulkUnpublishBusy, setBulkUnpublishBusy] = useState(false);

  const items = useMemo(() => pageData?.results ?? [], [pageData]);
  const isFiltered = Boolean(search) || Boolean(domainFilter);
  // Выбор живёт РОВНО на показанной выборке и обнуляется, как только она сменилась (страница,
  // таб, поиск, фильтр, порядок) — как в Gmail/GitHub/Odoo: массовое действие применяется к
  // тому, что человек видит. Источник — ключ выборки, поэтому обнуление происходит в рендере,
  // а не кадром позже (иначе панель массовых действий мигала бы старым числом).
  const selectionKey = `${page}|${tab}|${search}|${ordering}|${domainFilter}`;
  const [selected, setSelected] = useDraftState(selectionKey, () => new Set<number>());

  const publishableSelected = useMemo(
    () => (isDraftLike ? items.filter((p) => selected.has(p.id) && p.completeness?.is_publishable) : []),
    [items, selected, isDraftLike],
  );

  // Опубликовали/заархивировали последние строки последней страницы — не оставляем человека
  // на странице, которой больше нет: она выглядела бы как «пусто».
  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(total / pageSize));
    if (page > lastPage) setPage(lastPage);
  }, [total, pageSize, page, setPage]);

  const goEnrich = (p: Product) => onNavigate?.(`product-edit/${p.id}`);
  const goOpen = (p: Product) => onProductClick?.(String(p.id));

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const bulkArchive = () => {
    archiveMany.mutate([...selected], {
      onSuccess: (result) => {
        // Построчный отчёт: сервер возвращает archived + skipped с причиной по каждой строке.
        if (result.archived.length > 0) toast.success(t('myProducts.bulkArchived', { count: result.archived.length }));
        if (result.skipped.length > 0) {
          const reasons = [...new Set(result.skipped.map((row) => translateApiError(row.error)))].join(', ');
          toast.error(t('myProducts.bulkArchiveSkipped', { count: result.skipped.length, reasons }));
        }
        setSelected(new Set());
      },
      onError: (err) => toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('myProducts.actionFailed')),
    });
  };

  // Отдельного bulk-эндпоинта снятия с публикации нет — клиентский цикл с ЧЕСТНЫМ отчётом
  // сколько получилось и сколько нет (никаких «всё ок» поверх частичного успеха).
  const bulkUnpublish = async () => {
    setBulkUnpublishBusy(true);
    const results = await Promise.allSettled([...selected].map((id) => catalogApi.unpublishProduct(id)));
    const okCount = results.filter((r) => r.status === 'fulfilled').length;
    const firstFailure = results.find((r): r is PromiseRejectedResult => r.status === 'rejected');
    if (okCount > 0) toast.success(t('myProducts.bulkUnpublished', { count: okCount }));
    if (firstFailure) {
      toast.error(
        t('myProducts.bulkUnpublishFailed', {
          count: results.length - okCount,
          reason: translateApiError(firstFailure.reason),
        }),
      );
    }
    setSelected(new Set());
    queryClient.invalidateQueries({ queryKey: ['products'] });
    setBulkUnpublishBusy(false);
  };

  const columns: ResponsiveColumn<Product>[] = [
    {
      id: 'select',
      // «Выбрать всё» — это всё НА ЭТОЙ СТРАНИЦЕ, ничего сверх показанного.
      header: (
        <Checkbox
          checked={items.length > 0 && items.every((p) => selected.has(p.id))}
          onCheckedChange={(value) => setSelected(value ? new Set(items.map((p) => p.id)) : new Set())}
          aria-label={t('nomenclature.selectAllOnPage')}
        />
      ),
      mobileLabel: t('adminTable.selectRow'),
      className: 'w-10',
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
      sortKey: 'name',
      mobileTitle: true,
      cell: (p: Product) => (
        <div className="min-w-0">
          <div className="truncate font-medium">{p.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {p.source_deal ? t('nomenclature.fromRequest', { id: p.source_deal }) : p.sku}
          </div>
        </div>
      ),
    },
    ...(tab === 'CANDIDATES'
      ? [{
          id: 'demand',
          header: t('nomenclature.columns.demand'),
          sortKey: 'demand_count',
          cell: (p: Product) => (
            <span className="tabular-nums">
              {p.demand_count ? t('nomenclature.askedTimes', { count: p.demand_count }) : '—'}
            </span>
          ),
        } satisfies ResponsiveColumn<Product>]
      : []),
    ...(isDraftLike
      ? [{
          id: 'completeness',
          header: t('nomenclature.columns.completeness'),
          cell: (p: Product) => <CompletenessCell product={p} />,
        } satisfies ResponsiveColumn<Product>]
      : []),
    ...(tab === 'PUBLISHED'
      ? [{
          id: 'price',
          header: t('myProducts.columns.price'),
          cell: (p: Product) =>
            p.base_price ? (
              <span className="tabular-nums">
                {Number(p.base_price).toLocaleString(i18n.language)} {p.base_price_currency ?? ''}
              </span>
            ) : (
              <span className="text-muted-foreground">—</span>
            ),
        } satisfies ResponsiveColumn<Product>]
      : []),
    {
      id: 'actions',
      header: '',
      mobileActions: true,
      cell: (p: Product) => <RowActions product={p} tab={tab} onEnrich={goEnrich} onOpen={goOpen} />,
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <Boxes className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">{t('myProducts.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('myProducts.subtitle')}</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => onNavigate?.('catalog-import')}>
            <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
            {t('myProducts.importPrice')}
          </Button>
          <Button onClick={() => onNavigate?.('product-new')}>
            <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
            {t('myProducts.addProduct')}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Tabs
          value={tab}
          onValueChange={(value) => {
            setTab(value as MyProductsTabKey);
            setPage(1);
            setSelected(new Set());
          }}
        >
          <TabsList className="h-auto flex-wrap">
            {MY_PRODUCTS_TABS.map((key) => (
              <TabsTrigger key={key} value={key}>
                {t(`myProducts.tabs.${key}`)}
                {tabCounts[key] !== undefined && (
                  <Badge variant="secondary" className="ml-1.5 tabular-nums">{tabCounts[key]}</Badge>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {/* Честная подпись к массовым действиям: галочки собраны на показанной странице. */}
        {selected.size > 0 && total > pageSize && (
          <span className="ml-auto text-xs text-muted-foreground">{t('nomenclature.selectionScope')}</span>
        )}
        {selected.size > 0 && isDraftLike && (
          <>
            <Button
              variant="outline"
              size="sm"
              className={total > pageSize ? undefined : 'ml-auto'}
              disabled={classify.busy}
              onClick={() => classify.run([...selected])}
            >
              {classify.busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              {t('nomenclature.classify.run', { count: selected.size })}
            </Button>
            <Button variant="outline" size="sm" disabled={archiveMany.isPending} onClick={bulkArchive}>
              {archiveMany.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              {t('myProducts.archiveSelected', { count: selected.size })}
            </Button>
          </>
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
        {selected.size > 0 && tab === 'PUBLISHED' && (
          <Button
            variant="outline"
            size="sm"
            className={total > pageSize ? undefined : 'ml-auto'}
            disabled={bulkUnpublishBusy}
            onClick={bulkUnpublish}
          >
            {bulkUnpublishBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {t('myProducts.unpublishSelected', { count: selected.size })}
          </Button>
        )}
      </div>

      {/* Панели-баннеры НАД таблицей и только там, где идёт наполнение (аудит §5.2). */}
      {isDraftLike && <InsightBanners onFixReclass={goEnrich} />}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            {t(`myProducts.tabs.${tab}`)}
            {/* Число — с сервера (`count`), а не длина показанного куска. */}
            {total > 0 && <Badge variant="secondary" className="tabular-nums">{total}</Badge>}
          </CardTitle>
          {/* D10: архив ОБРАТИМ — сюда попадают и слитые дубли; «Восстановить» возвращает в черновики. */}
          {tab === 'ARCHIVED' && <p className="text-xs text-muted-foreground">{t('myProducts.archiveHint')}</p>}
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Toolbar
            searchValue={searchInput}
            onSearchChange={setSearchInput}
            searchPlaceholder={t('nomenclature.searchPlaceholder')}
            filters={[
              {
                key: 'domain',
                value: filters.domain,
                onChange: (value) => setFilter('domain', value),
                allLabel: t('nomenclature.filters.allDomains'),
                options: domainTypes.map((domain) => ({
                  value: domain.code,
                  label: t(getDomainLabelKey(domain.code), domain.name),
                })),
              },
            ]}
          />

          {isError ? (
            <ErrorState onRetry={() => refetch()} />
          ) : isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : items.length === 0 && isFiltered ? (
            // Пустой поиск — это НЕ пустой реестр: предлагать «создать карточку» там, где
            // человек просто не нашёл строку по запросу, значит врать о состоянии данных.
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">{t('nomenclature.noMatches')}</p>
              <p className="max-w-md text-xs text-muted-foreground">{t('nomenclature.noMatchesHint')}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSearchInput('');
                  setFilter('domain', 'all');
                }}
              >
                {t('nomenclature.resetFilters')}
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <PackagePlus className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">{t(EMPTY_KEYS[tab].title)}</p>
              <p className="max-w-md text-xs text-muted-foreground">{t(EMPTY_KEYS[tab].hint)}</p>
              {/* Пустой экран ведёт к следующему шагу (Ariba enablement), а не молчит. */}
              {isDraftLike && (
                <div className="flex gap-2 pt-1">
                  <Button size="sm" onClick={() => onNavigate?.('product-new')}>
                    {t('nomenclature.emptyCta.create')}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => onNavigate?.('catalog-import')}>
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
              // Клик по строке: черновики — в редактор, опубликованное — в карточку. У архива
              // клика НЕТ намеренно: единственное действие — явное «Восстановить».
              onRowClick={
                tab === 'ARCHIVED' ? undefined : (p: Product) => (isDraftLike ? goEnrich(p) : goOpen(p))
              }
              // Сортировка только по тем полям, которые умеет сервер (имя, спрос). У «Готовности»
              // заголовка-сортировки НЕТ намеренно: полнота считается на лету в Python.
              sorting={{ ordering, onToggle: toggleOrdering }}
            />
          )}

          <Pager page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      {classify.suggestions && classify.suggestions.length > 0 && (
        <ClassifySuggestionsCard
          suggestions={classify.suggestions}
          onReject={classify.reject}
          onApplyAll={classify.applyAll}
          onCancel={classify.cancel}
        />
      )}

      {tab === 'CANDIDATES' && items.length > 0 && (
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

export default MyProductsPage;
