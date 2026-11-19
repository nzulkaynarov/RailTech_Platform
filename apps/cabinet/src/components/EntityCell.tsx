import { Package, Wrench } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { entityInitials } from '@/lib/initials';
import { cn } from '@/lib/utils';

/**
 * Человек, компания и позиция каталога — одинаково во всех списках, карточках и строках документов (стандарт интерфейса
 * §12): картинка (фото, логотип, миниатюра), иначе инициалы или значок типа; название; второй строкой — должность, ИНН
 * или наш артикул. Картинка декоративна: название всегда рядом текстом. Ссылка — только если передан адрес.
 */

type Size = 24 | 32 | 40;

function Picture({ src, fallback, size, shape }: { src?: string | null; fallback: ReactNode; size: Size; shape: 'round' | 'square' }) {
  // Адрес, который не загрузился: новая картинка (другой адрес) пробуется заново.
  const [broken, setBroken] = useState<string | null>(null);
  const show = Boolean(src) && broken !== src;
  return (
    <span
      aria-hidden="true"
      data-photo={show ? 'true' : 'false'}
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden font-semibold leading-none',
        shape === 'round' ? 'rounded-full' : 'rounded border border-border',
        show ? 'bg-card' : 'bg-primary/10 text-primary',
        size >= 40 ? 'text-sm' : 'text-xs',
      )}
      style={{ width: size, height: size }}
    >
      {show ? (
        <img
          src={src ?? undefined}
          alt=""
          width={size}
          height={size}
          className="block h-full w-full object-cover"
          onError={() => setBroken(src ?? null)}
        />
      ) : (
        fallback
      )}
    </span>
  );
}

function Shell({
  picture,
  name,
  to,
  caption,
  title,
}: {
  picture: ReactNode;
  name: string;
  to?: string | null;
  caption?: ReactNode;
  /** Своё название (кнопка окна, перенос длинной строки документа) вместо ссылки или текста в одну строку */
  title?: ReactNode;
}) {
  return (
    <span className={cn('inline-flex min-w-0 max-w-full gap-2 align-middle', title ? 'items-start' : 'items-center')}>
      {picture}
      <span className="flex min-w-0 flex-col">
        {title ??
          (to ? (
            <Link to={to} className="truncate font-medium text-primary underline-offset-4 hover:underline">
              {name}
            </Link>
          ) : (
            <span className="truncate">{name}</span>
          ))}
        {caption ? <span className="truncate text-xs text-muted-foreground">{caption}</span> : null}
      </span>
    </span>
  );
}

function CodeLine({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="sr-only">{label}: </span>
      <span className="font-mono" translate="no">
        {value}
      </span>
    </>
  );
}

/** Человек: круг с фото или инициалами, ФИО, должность или роль. */
export function PersonCell({
  name,
  caption,
  photoUrl,
  to,
  size = 24,
}: {
  name: string;
  caption?: string | null;
  photoUrl?: string | null;
  to?: string | null;
  size?: Size;
}) {
  return (
    <Shell
      picture={<Picture src={photoUrl} fallback={entityInitials(name)} size={size} shape="round" />}
      name={name}
      to={to}
      caption={caption}
    />
  );
}

/** Компания: квадрат с логотипом или буквами названия, название, ИНН. */
export function CompanyCell({
  name,
  inn,
  logoUrl,
  to,
  size = 24,
}: {
  name: string;
  inn?: string | null;
  logoUrl?: string | null;
  to?: string | null;
  size?: Size;
}) {
  const { t } = useTranslation();
  return (
    <Shell
      picture={<Picture src={logoUrl} fallback={entityInitials(name, true)} size={size} shape="square" />}
      name={name}
      to={to}
      caption={inn ? <CodeLine label={t('common.inn')} value={inn} /> : null}
    />
  );
}

/** Позиция каталога: миниатюра или значок типа (товар, услуга), название, наш артикул. */
export function ItemCell({
  name,
  sku,
  photoUrl,
  kind = 'goods',
  to,
  title,
  size = 32,
}: {
  name: string;
  sku?: string | null;
  photoUrl?: string | null;
  kind?: 'goods' | 'service';
  to?: string | null;
  /** Своё название вместо ссылки или текста в одну строку (кнопка окна, длинная строка КП) */
  title?: ReactNode;
  size?: Size;
}) {
  const { t } = useTranslation();
  const Icon = kind === 'service' ? Wrench : Package;
  return (
    <Shell
      picture={<Picture src={photoUrl} fallback={<Icon className="h-4 w-4" strokeWidth={1.75} />} size={size} shape="square" />}
      name={name}
      to={to}
      title={title}
      caption={sku ? <CodeLine label={t('common.article')} value={sku} /> : null}
    />
  );
}
