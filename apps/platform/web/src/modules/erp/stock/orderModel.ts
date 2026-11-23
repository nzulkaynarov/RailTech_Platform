/** Одна проверка нового заказа поставщику: галочка шага, список «нужно» шага и обязательность полей берутся отсюда. */
export interface OrderDraft {
  supplierId: string | undefined;
  manual: boolean;
  request: string | undefined;
  lines: readonly { product_id?: string | undefined; quantity?: number | undefined }[];
}

export type OrderRequirement = "supplier" | "request" | "product" | "quantity";

/** Минимальное количество в строке — то же, что `min` поля количества */
export const MIN_QUANTITY = 0.001;

/** Невыполненные требования по шагам: «Партнёр и способ» и «Строки» (только для ручного заказа); пусто — шаг готов. */
export function orderRequirements(
  draft: OrderDraft,
): Record<"supplier" | "lines", OrderRequirement[]> {
  const supplier: OrderRequirement[] = [];
  if (!draft.supplierId) supplier.push("supplier");
  if (!draft.manual && !(draft.request ?? "").trim()) supplier.push("request");
  const lines: OrderRequirement[] = [];
  if (draft.manual) {
    if (draft.lines.length === 0 || draft.lines.some((l) => !l.product_id)) lines.push("product");
    if (draft.lines.length === 0 || draft.lines.some((l) => !(Number(l.quantity) >= MIN_QUANTITY)))
      lines.push("quantity");
  }
  return { supplier, lines };
}
