import type { ReactNode } from "react";
import { useState } from "react";
import { Link } from "react-router";

import { entityInitials } from "../lib/initials";

import { Code } from "./Code";
import { TestTag } from "./TestTag";
import { PackageIcon, WrenchIcon } from "./lucide";
import "./entity-cell.css";

/**
 * Человек, компания и позиция каталога — одной строкой во всех реестрах, карточках и строках документов (стандарт
 * интерфейса §12): картинка (фото, логотип, миниатюра), иначе инициалы или значок типа; название; второй строкой —
 * должность, ИНН или наш артикул. Картинка декоративна: название всегда рядом текстом. Ссылка — только если передан
 * адрес (права проверяет вызывающий).
 */

function Picture({
  src,
  fallback,
  size,
  shape,
}: {
  src?: string | null;
  fallback: ReactNode;
  size: number;
  shape: "round" | "square";
}) {
  // Запоминаем адрес, который не загрузился: новая картинка (другой адрес) пробуется заново.
  const [broken, setBroken] = useState<string | null>(null);
  const show = Boolean(src) && broken !== src;
  return (
    <span
      aria-hidden="true"
      className={`pf-entity__pic pf-entity__pic--${shape}`}
      data-photo={show ? "true" : "false"}
      style={{ width: size, height: size, fontSize: size >= 40 ? 14 : 11 }}
    >
      {show ? (
        <img
          src={src ?? undefined}
          alt=""
          width={size}
          height={size}
          onError={() => {
            setBroken(src ?? null);
          }}
        />
      ) : (
        fallback
      )}
    </span>
  );
}

function Title({ name, to }: { name: string; to?: string | null }) {
  return to ? (
    <Link className="pf-entity__name" to={to}>
      {name}
    </Link>
  ) : (
    <span className="pf-entity__name">{name}</span>
  );
}

function Shell({ picture, children }: { picture: ReactNode; children: ReactNode }) {
  return (
    <span className="pf-entity">
      {picture}
      <span className="pf-entity__text">{children}</span>
    </span>
  );
}

type Size = 24 | 32 | 40 | 56;

/** Человек: сотрудник, контакт контрагента, лид. Круг с фото или инициалами, ФИО, должность или роль. */
export function PersonCell({
  name,
  caption,
  photoUrl,
  to,
  title,
  picture,
  size = 24,
}: {
  name: string;
  caption?: string | null;
  photoUrl?: string | null;
  to?: string | null;
  /** Своя ссылка на название (например, окно карточки модуля) вместо `to`; инициалы — из `name`. */
  title?: ReactNode;
  /** Своя картинка вместо круга с фото (например, кнопка загрузки фото в карточке контрагента). */
  picture?: ReactNode;
  size?: Size;
}) {
  return (
    <Shell
      picture={
        picture ?? (
          <Picture src={photoUrl} fallback={entityInitials(name)} size={size} shape="round" />
        )
      }
    >
      {title ?? <Title name={name} to={to} />}
      {caption ? <span className="pf-entity__caption">{caption}</span> : null}
    </Shell>
  );
}

/** Компания: клиент, партнёр, поставщик, изготовитель. Квадрат с логотипом или буквами названия, название, ИНН. */
export function CompanyCell({
  name,
  inn,
  innLabel = "ИНН",
  logoUrl,
  to,
  title,
  size = 24,
  test,
}: {
  name: string;
  inn?: string | null;
  innLabel?: string;
  logoUrl?: string | null;
  to?: string | null;
  /** Компания тестовая (ТЕСТ-2): после названия — метка «Тестовая». */
  test?: boolean;
  /** Своя ссылка на название (например, окно карточки модуля) вместо `to`; инициалы — из `name`. */
  title?: ReactNode;
  size?: Size;
}) {
  return (
    <Shell
      picture={
        <Picture src={logoUrl} fallback={entityInitials(name, true)} size={size} shape="square" />
      }
    >
      {title ?? <Title name={name} to={to} />}
      {test ? (
        <span className="pf-entity__caption">
          <TestTag value />
        </span>
      ) : null}
      {inn ? (
        <span className="pf-entity__caption">
          <span className="pf-sr-only">{innLabel}: </span>
          <Code quiet>{inn}</Code>
        </span>
      ) : null}
    </Shell>
  );
}

/** Позиция каталога: миниатюра или значок типа (товар, услуга), название, наш артикул. */
export function ItemCell({
  name,
  sku,
  skuLabel = "Артикул",
  photoUrl,
  kind = "goods",
  to,
  title,
  size = 32,
}: {
  name: string;
  sku?: string | null;
  skuLabel?: string;
  photoUrl?: string | null;
  kind?: "goods" | "service";
  to?: string | null;
  /** Своя ссылка на название (например, окно карточки модуля) вместо `to`; инициалы — из `name`. */
  title?: ReactNode;
  size?: Size;
}) {
  const icon = kind === "service" ? <WrenchIcon /> : <PackageIcon />;
  return (
    <Shell picture={<Picture src={photoUrl} fallback={icon} size={size} shape="square" />}>
      {title ?? <Title name={name} to={to} />}
      {sku ? (
        <span className="pf-entity__caption">
          <span className="pf-sr-only">{skuLabel}: </span>
          <Code quiet>{sku}</Code>
        </span>
      ) : null}
    </Shell>
  );
}

/** Только картинка человека (круг: фото или инициалы) — для шапки карточки и списков, где имя стоит своим заголовком. */
export function PersonAvatar({
  name,
  photoUrl,
  size = 40,
}: {
  name: string;
  photoUrl?: string | null;
  size?: Size;
}) {
  return <Picture src={photoUrl} fallback={entityInitials(name)} size={size} shape="round" />;
}

/** Только картинка компании (квадрат: логотип или буквы названия) — для шапки карточки, где название стоит заголовком. */
export function CompanyAvatar({
  name,
  logoUrl,
  size = 40,
}: {
  name: string;
  logoUrl?: string | null;
  size?: Size;
}) {
  return <Picture src={logoUrl} fallback={entityInitials(name, true)} size={size} shape="square" />;
}
