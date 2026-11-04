import { useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import type { CatalogItem, CatalogItemDocument } from '@/api/portal';
import { DocumentButton } from '@/components/DocumentButton';
import { SectionTitle } from '@/components/Details';
import { ToneBadge } from '@/components/StatusBadge';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Галерея карточки: главное фото крупно (бэкенд отдаёт его первым), миниатюры под ним. Клавиатура: на миниатюрах
 * ←/→ и Home/End переключают фото (роль «одна кнопка в Tab, остальные стрелками»), кнопки «Предыдущее/Следующее»
 * — для касания. Подпись фото читает диктор: «{название}, фото N из M». Одно фото — без миниатюр и кнопок.
 */
export function ProductGallery({ name, images }: { name: string; images: string[] }) {
  const { t } = useTranslation();
  const [current, setCurrent] = useState(0);
  const thumbs = useRef<Array<HTMLButtonElement | null>>([]);
  const total = images.length;
  if (total === 0) return null;
  const index = Math.min(current, total - 1);

  const go = (next: number, focus = false) => {
    const target = (next + total) % total;
    setCurrent(target);
    if (focus) thumbs.current[target]?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const keys: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowDown: index + 1,
      ArrowLeft: index - 1,
      ArrowUp: index - 1,
      Home: 0,
      End: total - 1,
    };
    if (!(event.key in keys)) return;
    event.preventDefault();
    go(keys[event.key], true);
  };

  return (
    <section aria-label={t('pages.catalogItem.photos')} className="flex min-w-0 flex-col gap-2">
      <div className="relative">
        <img
          src={images[index]}
          alt={t('pages.catalogItem.photoAlt', { name, n: index + 1, total })}
          className="aspect-4/3 w-full rounded-lg border bg-card object-contain"
        />
        {total > 1 ? (
          <>
            <button
              type="button"
              onClick={() => go(index - 1)}
              aria-label={t('pages.catalogItem.photoPrev')}
              className="absolute top-1/2 left-2 flex size-10 -translate-y-1/2 items-center justify-center rounded-full border bg-background/90 shadow-xs outline-none hover:bg-background focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronLeft className="size-5" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => go(index + 1)}
              aria-label={t('pages.catalogItem.photoNext')}
              className="absolute top-1/2 right-2 flex size-10 -translate-y-1/2 items-center justify-center rounded-full border bg-background/90 shadow-xs outline-none hover:bg-background focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronRight className="size-5" aria-hidden="true" />
            </button>
          </>
        ) : null}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {total > 1 ? t('pages.catalogItem.photoOf', { n: index + 1, total }) : ''}
      </span>
      {total > 1 ? (
        <ul className="flex gap-2 overflow-x-auto p-1" onKeyDown={onKeyDown}>
          {images.map((src, position) => (
            <li key={src} className="shrink-0">
              <button
                type="button"
                ref={(node) => {
                  thumbs.current[position] = node;
                }}
                tabIndex={position === index ? 0 : -1}
                aria-pressed={position === index}
                aria-label={t('pages.catalogItem.photoOf', { n: position + 1, total })}
                onClick={() => go(position)}
                className={cn(
                  'block size-16 overflow-hidden rounded-md border bg-card outline-none focus-visible:ring-2 focus-visible:ring-ring sm:size-20',
                  position === index ? 'border-primary ring-2 ring-primary' : 'opacity-80 hover:opacity-100',
                )}
              >
                <img src={src} alt="" className="size-full object-contain" loading="lazy" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function SpecRows({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="divide-y rounded-lg border bg-card text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex min-w-0 justify-between gap-3 px-3 py-2">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right font-medium wrap-break-word">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * «Изготовитель»: изготовитель, страна изготовителя, артикул изготовителя; страна происхождения — только если она
 * отличается от страны изготовителя (schema.org: brand, mpn, countryOfOrigin). Пусто — блок не рисуется.
 */
export function ManufacturerBlock({ item }: { item: CatalogItem }) {
  const { t } = useTranslation();
  const manufacturer = item.manufacturer ?? null;
  const origin = item.country_of_origin ?? null;
  const rows: Array<[string, string]> = [];
  if (manufacturer) rows.push([t('pages.catalogItem.manufacturer'), manufacturer.name]);
  if (manufacturer?.country) rows.push([t('pages.catalogItem.manufacturerCountry'), manufacturer.country]);
  if (item.manufacturer_part_number) rows.push([t('pages.catalogItem.partNumber'), item.manufacturer_part_number]);
  if (origin && origin !== manufacturer?.country) rows.push([t('pages.catalogItem.countryOfOrigin'), origin]);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="catalog-manufacturer">
      <SectionTitle>
        <span id="catalog-manufacturer">{t('pages.catalogItem.manufacturerTitle')}</span>
      </SectionTitle>
      <SpecRows rows={rows} />
    </section>
  );
}

/** «Гарантия»: срок в месяцах и условия; нет гарантии (`warranty = null`) — блока нет. */
export function WarrantyBlock({ item }: { item: CatalogItem }) {
  const { t } = useTranslation();
  const warranty = item.warranty ?? null;
  if (!warranty) return null;
  return (
    <section aria-labelledby="catalog-warranty">
      <SectionTitle>
        <span id="catalog-warranty">{t('pages.catalogItem.warrantyTitle')}</span>
      </SectionTitle>
      <div className="rounded-lg border bg-card px-3 py-2 text-sm">
        <p className="font-medium">{t('pages.catalogItem.warrantyMonths', { count: warranty.months })}</p>
        {warranty.terms ? <p className="mt-1 whitespace-pre-line text-muted-foreground wrap-break-word">{warranty.terms}</p> : null}
      </div>
    </section>
  );
}

function DocumentRow({ itemId, document }: { itemId: number; document: CatalogItemDocument }) {
  const { t, i18n } = useTranslation();
  const meta = [
    document.number ? t('pages.catalogItem.documentNumber', { number: document.number }) : null,
    document.issued_by ? t('pages.catalogItem.issuedBy', { name: document.issued_by }) : null,
    document.valid_until
      ? t('pages.catalogItem.validUntil', { date: formatDate(document.valid_until, i18n.language) })
      : t('pages.catalogItem.noExpiry'),
  ].filter(Boolean);
  return (
    <li className="flex min-w-0 flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <ToneBadge tone="neutral">{document.kind_name}</ToneBadge>
          <span className="text-sm font-medium wrap-break-word">{document.title}</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground wrap-break-word">{meta.join(' · ')}</p>
      </div>
      <DocumentButton
        documentId={document.id}
        catalogItemId={itemId}
        fileName={document.title}
        label={document.title}
      />
    </li>
  );
}

/** «Документы»: действующие документы, видимые клиенту (отбирает ERP), с кнопкой «Скачать». Пусто — блока нет. */
export function DocumentsBlock({ item }: { item: CatalogItem }) {
  const { t } = useTranslation();
  const documents = item.documents ?? [];
  if (documents.length === 0) return null;
  return (
    <section aria-labelledby="catalog-documents">
      <SectionTitle>
        <span id="catalog-documents">{t('pages.catalogItem.documentsTitle')}</span>
      </SectionTitle>
      <ul className="divide-y rounded-lg border bg-card">
        {documents.map((document) => (
          <DocumentRow key={document.id} itemId={item.id} document={document} />
        ))}
      </ul>
    </section>
  );
}
