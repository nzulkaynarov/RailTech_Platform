import type { ItemRef } from "../../shared/api/generated/model";
import { outsidePhoto, readErpCatalog } from "./erpCatalog";

/** Адрес миниатюры главного фото позиции каталога мока (ЕД-4) — как у BFF: с версией фото. */
export function thumbnailOf(itemId: string): string | null {
  const main =
    readErpCatalog()
      .items.find((item) => item.id === itemId)
      ?.images.find((image) => image.is_main) ?? outsidePhoto(itemId);
  return main ? `/api/v1/erp/catalog/items/${itemId}/thumbnail?v=${main.id}` : null;
}

/**
 * Ссылка на позицию в строке документа мока (ЕД-4). Позиция есть в каталоге мока — артикул и фото оттуда; нет (склад,
 * заказ и расчёт мока живут своими номерами) — то, что знает строка.
 */
export function itemRefOf(
  id: string | number,
  name: string,
  sku = "",
  kind: ItemRef["kind"] = "goods",
): ItemRef {
  const key = String(id);
  const card = readErpCatalog().items.find((item) => item.id === key);
  return {
    id: key,
    name: card?.name ?? name,
    sku: card?.sku ?? sku,
    kind,
    thumbnail: thumbnailOf(key),
  };
}
