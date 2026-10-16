import { useId, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Check, ChevronLeft, ChevronRight, FilePlus2, Package, Plus, Search, SearchX, X } from 'lucide-react';

import { isPortalApiError, type CatalogItem } from '@/api/portal';
import { useCatalog, useCatalogCategories, useCatalogItem } from '@/api/queries';
import { SectionTitle } from '@/components/Details';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { DetailSkeleton, ErrorState, ListSkeleton } from '@/components/QueryStates';
import { StatusBadge, ToneBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { CATALOG_MAX_PAGE_SIZE, CATALOG_PAGE_SIZE, distinctCategories, pageCount, parsePage } from '@/lib/catalog';
import { formatMoney } from '@/lib/format';
import type { NewRequestPrefill } from '@/lib/requests';
import { cn } from '@/lib/utils';
import { CanAct } from '@/session/CanAct';

/**
 * Каталог — опубликованный слой (BUSINESS §10.1): название, описание, характеристики, единица, фото;
 * цена-витрина или «цена по запросу» (`price = null`); наличие — статусом и сроком, без количеств,
 * поставщиков и себестоимости (их нет в контракте). Поиск, категории, пагинация — в URL (`?q=&category=&page=`),
 * чтобы «Назад» возвращал к той же выдаче. Карточка ведёт в «Новый запрос» с позицией в первой строке.
 */
export function CatalogPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const category = params.get('category') ?? '';
  const page = parsePage(params.get('page'));
  const [selectedItems, setSelectedItems] = useState<CatalogItem[]>([]);

  const toggleSelect = (item: CatalogItem) => {
    setSelectedItems((current) =>
      current.some((x) => x.id === item.id) ? current.filter((x) => x.id !== item.id) : [...current, item],
    );
  };

  const update = (patch: Record<string, string | null>) =>
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        for (const [key, value] of Object.entries(patch)) {
          if (value) copy.set(key, value);
          else copy.delete(key);
        }
        return copy;
      },
      { replace: true },
    );

  const categoriesQuery = useCatalogCategories();
  const all = useCatalog({ page: 1, page_size: CATALOG_MAX_PAGE_SIZE });
  const byCategory = useCatalog({ q: q || undefined, page: 1, page_size: CATALOG_MAX_PAGE_SIZE }, Boolean(category));
  const paged = useCatalog({ q: q || undefined, page, page_size: CATALOG_PAGE_SIZE }, !category);
  const categories = categoriesQuery.data?.length
    ? categoriesQuery.data.map((c) => c.name)
    : distinctCategories(all.data?.items ?? [], i18n.language);

  const source = category ? byCategory : paged;
  let items: CatalogItem[] = [];
  let total = 0;
  if (source.data) {
    if (category) {
      const filtered = source.data.items.filter((item) => item.category === category);
      total = filtered.length;
      items = filtered.slice((page - 1) * CATALOG_PAGE_SIZE, page * CATALOG_PAGE_SIZE);
    } else {
      items = source.data.items;
      total = source.data.total;
    }
  }
  const pages = pageCount(total, CATALOG_PAGE_SIZE);

  return (
    <>
      <PageHeader title={t('pages.catalog.title')} />
      <SearchForm key={q} initial={q} onSearch={(value) => update({ q: value || null, page: null })} />
      {categories.length > 0 ? (
        <div role="group" aria-label={t('pages.catalog.categories')} className="mb-4 flex flex-wrap gap-2">
          {['', ...categories].map((name) => (
            <Button
              key={name || 'all'}
              type="button"
              size="sm"
              variant={name === category ? 'default' : 'outline'}
              aria-pressed={name === category}
              className="rounded-full"
              onClick={() => update({ category: name || null, page: null })}
            >
              {name || t('common.all')}
            </Button>
          ))}
        </div>
      ) : null}

      {source.isPending ? (
        <ListSkeleton rows={4} />
      ) : source.isError ? (
        <ErrorState error={source.error} onRetry={() => void source.refetch()} />
      ) : items.length === 0 ? (
        q || category ? (
          <EmptyState icon={SearchX} title={t('pages.catalog.notFoundTitle')} text={t('pages.catalog.notFoundText')}>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button variant="outline" onClick={() => update({ q: null, category: null, page: null })}>
                {t('pages.catalog.reset')}
              </Button>
              <CanAct>
                <Button asChild>
                  <Link to="/requests/new">{t('pages.catalog.askInRequest')}</Link>
                </Button>
              </CanAct>
            </div>
          </EmptyState>
        ) : (
          <EmptyState icon={Package} title={t('pages.catalog.emptyTitle')} text={t('pages.catalog.emptyText')} />
        )
      ) : (
        <>
          <p className="mb-3 text-sm text-muted-foreground" role="status" aria-live="polite">
            {t('pages.catalog.found', { count: total })}
          </p>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label={t('pages.catalog.results')}>
            {items.map((item) => (
              <li key={item.id}>
                <CatalogCard
                  item={item}
                  isSelected={selectedItems.some((x) => x.id === item.id)}
                  onToggleSelect={() => toggleSelect(item)}
                />
              </li>
            ))}
          </ul>
          {pages > 1 ? (
            <nav aria-label={t('pages.catalog.pagination')} className="mt-4 flex items-center justify-between gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => update({ page: page - 1 > 1 ? String(page - 1) : null })}>
                <ChevronLeft aria-hidden="true" />
                {t('pages.catalog.prev')}
              </Button>
              <span className="text-sm text-muted-foreground">{t('pages.catalog.page', { page, pages })}</span>
              <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
                {t('pages.catalog.next')}
                <ChevronRight aria-hidden="true" />
              </Button>
            </nav>
          ) : null}

          {selectedItems.length > 0 ? (
            <aside
              role="region"
              aria-label={t('pages.catalog.selectedCount', { count: selectedItems.length })}
              className="sticky bottom-4 z-20 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card/95 p-4 shadow-lg backdrop-blur"
            >
              <div className="flex items-center gap-2">
                <ToneBadge tone="info">{selectedItems.length}</ToneBadge>
                <span className="text-sm font-medium">{t('pages.catalog.selectedCount', { count: selectedItems.length })}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => setSelectedItems([])}>
                  {t('pages.catalog.clearSelection')}
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    const state: NewRequestPrefill = {
                      lines: selectedItems.map((item) => ({
                        text: item.name,
                        unit: item.unit ?? null,
                      })),
                    };
                    navigate('/requests/new', { state });
                  }}
                >
                  <FilePlus2 aria-hidden="true" />
                  {t('pages.catalog.createRequestWithSelected', { count: selectedItems.length })}
                </Button>
              </div>
            </aside>
          ) : null}
        </>
      )}
    </>
  );
}

function SearchForm({ initial, onSearch }: { initial: string; onSearch: (value: string) => void }) {
  const { t } = useTranslation();
  const id = useId();
  const [value, setValue] = useState(initial);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSearch(value.trim());
  };
  return (
    <form role="search" onSubmit={submit} className="mb-3 flex gap-2">
      <Label htmlFor={id} className="sr-only">
        {t('pages.catalog.search')}
      </Label>
      <div className="relative min-w-0 flex-1">
        <Input
          id={id}
          type="search"
          value={value}
          maxLength={200}
          placeholder={t('pages.catalog.searchPlaceholder')}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t('pages.catalog.clear')}
          onClick={() => {
            setValue('');
            onSearch('');
          }}
        >
          <X aria-hidden="true" />
        </Button>
      ) : null}
      <Button type="submit">
        <Search aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">{t('pages.catalog.searchSubmit')}</span>
      </Button>
    </form>
  );
}

function PriceText({ item, large = false }: { item: CatalogItem; large?: boolean }) {
  const { t } = useTranslation();
  return item.price ? (
    <span className={cn('font-semibold', large ? 'text-2xl' : 'text-base')}>
      {formatMoney(item.price)}
      <span className="text-sm font-normal text-muted-foreground"> / {item.unit}</span>
    </span>
  ) : (
    <span className={cn('font-medium text-muted-foreground', large ? 'text-lg' : 'text-sm')}>{t('pages.catalog.priceOnRequest')}</span>
  );
}

function AvailabilityText({ item }: { item: CatalogItem }) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <StatusBadge entity="availability" code={item.availability} />
      {item.lead_time_days !== null && item.lead_time_days !== undefined ? (
        <span className="text-muted-foreground">{t('pages.catalog.leadTime', { count: item.lead_time_days })}</span>
      ) : null}
    </span>
  );
}

function CatalogCard({
  item,
  isSelected = false,
  onToggleSelect,
}: {
  item: CatalogItem;
  isSelected?: boolean;
  onToggleSelect?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <article className="relative flex h-full min-w-0 flex-col gap-2 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2">
          {item.category ? <span>{item.category}</span> : null}
          {item.kind === 'service' ? <ToneBadge tone="info">{t('pages.catalog.kinds.service')}</ToneBadge> : null}
        </div>
        {onToggleSelect ? (
          <CanAct>
            <Button
              type="button"
              size="sm"
              variant={isSelected ? 'default' : 'outline'}
              className="relative z-10 h-7 text-xs"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onToggleSelect();
              }}
              aria-label={
                isSelected
                  ? `${t('pages.catalog.removeFromRequest')}: ${item.name}`
                  : `${t('pages.catalog.addToRequest')}: ${item.name}`
              }
            >
              {isSelected ? <Check className="size-3.5" aria-hidden="true" /> : <Plus className="size-3.5" aria-hidden="true" />}
              {isSelected ? t('pages.catalog.removeFromRequest') : t('pages.catalog.addToRequest')}
            </Button>
          </CanAct>
        ) : null}
      </div>
      <h2 className="text-sm font-medium wrap-break-word">
        <Link
          to={`/catalog/${item.id}`}
          className="rounded-sm underline-offset-4 outline-none after:absolute after:inset-0 after:rounded-lg hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
        >
          {item.name}
        </Link>
      </h2>
      <div className="mt-auto flex flex-col gap-2 pt-1">
        <PriceText item={item} />
        <AvailabilityText item={item} />
      </div>
    </article>
  );
}

export function CatalogItemPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const id = Number(useParams().id);
  const query = useCatalogItem(id);

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError) {
    if (isPortalApiError(query.error, 404)) {
      return (
        <>
          <PageHeader title={t('common.notFoundTitle')} />
          <EmptyState icon={SearchX} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
            <Button asChild variant="outline">
              <Link to="/catalog">{t('pages.catalogItem.backToList')}</Link>
            </Button>
          </EmptyState>
        </>
      );
    }
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const item = query.data;
  const askFor = () => {
    const state: NewRequestPrefill = { line: { text: item.name, unit: item.unit } };
    navigate('/requests/new', { state });
  };

  return (
    <>
      <PageHeader title={item.name} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          {item.images?.length ? (
            <ul className="flex snap-x gap-2 overflow-x-auto" aria-label={t('pages.catalogItem.photos')}>
              {item.images.map((src, index) => (
                <li key={src} className="shrink-0 snap-start">
                  <img
                    src={src}
                    alt={t('pages.catalogItem.photoAlt', { name: item.name, n: index + 1 })}
                    className="h-48 w-auto max-w-[80vw] rounded-lg border object-contain"
                    loading="lazy"
                  />
                </li>
              ))}
            </ul>
          ) : null}
          {item.description ? (
            <section aria-labelledby="catalog-description">
              <SectionTitle>
                <span id="catalog-description">{t('pages.catalogItem.description')}</span>
              </SectionTitle>
              <p className="text-sm whitespace-pre-line wrap-break-word">{item.description}</p>
            </section>
          ) : null}
          {item.attributes?.length ? (
            <section aria-labelledby="catalog-attributes">
              <SectionTitle>
                <span id="catalog-attributes">{t('pages.catalogItem.attributes')}</span>
              </SectionTitle>
              <dl className="divide-y rounded-lg border bg-card text-sm">
                {item.attributes.map((attribute) => (
                  <div key={attribute.name} className="flex min-w-0 justify-between gap-3 px-3 py-2">
                    <dt className="text-muted-foreground">{attribute.name}</dt>
                    <dd className="text-right font-medium wrap-break-word">{attribute.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
        </div>
        <Card className="h-fit">
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {item.category ? <span>{item.category}</span> : null}
              <ToneBadge tone="neutral">{t(`pages.catalog.kinds.${item.kind}`)}</ToneBadge>
            </div>
            <PriceText item={item} large />
            {item.price ? null : <p className="text-sm text-muted-foreground">{t('pages.catalogItem.priceOnRequestHint')}</p>}
            <AvailabilityText item={item} />
            <p className="text-sm text-muted-foreground">{t('pages.catalogItem.unit', { unit: item.unit })}</p>
            <CanAct>
              <Button onClick={askFor}>
                <FilePlus2 aria-hidden="true" />
                {t('pages.catalogItem.request')}
              </Button>
            </CanAct>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
