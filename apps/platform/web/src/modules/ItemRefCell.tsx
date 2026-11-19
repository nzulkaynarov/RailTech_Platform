import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../app/access";
import { useAuth } from "../app/auth/useAuth";
import type { ItemRef } from "../shared/api/generated/model";
import { ItemCell } from "../shared/ui/EntityCell";

/** Карточка позиции в каталоге: боковое окно «Номенклатуры» (`?item=`). */
const itemCardPath = (id: string) => `/erp/catalog?item=${encodeURIComponent(id)}&panel=open`;

/**
 * Позиция каталога в строке любого документа (ЕД-4, `ui-standard.md` §12): миниатюра или значок типа, название, наш
 * артикул. `name` — то, как позицию называет строка (слова клиента в расчёте, ADR-0027 п. 4); без него — название
 * карточки. Название ведёт в карточку каталога, если раздел виден сотруднику; строка без карточки — значок и текст.
 */
export function ItemRefCell({
  item,
  name,
  kind,
  title,
  size,
}: {
  item: ItemRef | null | undefined;
  name?: string;
  /** Тип строки, когда карточки нет (услуга в расчёте) */
  kind?: ItemRef["kind"];
  /** Своё название (кнопка, открывающая окно модуля) вместо ссылки на карточку каталога */
  title?: ReactNode;
  size?: 32 | 40;
}) {
  const { t } = useTranslation("ui");
  const { me } = useAuth();
  const to = item && canSee(me, { resource: "erp.stock" }) ? itemCardPath(item.id) : null;
  return (
    <ItemCell
      name={name ?? item?.name ?? ""}
      sku={item?.sku || null}
      skuLabel={t("entity.sku")}
      photoUrl={item?.thumbnail ?? null}
      kind={item?.kind ?? kind ?? "goods"}
      to={to}
      {...(title ? { title } : {})}
      {...(size ? { size } : {})}
    />
  );
}
