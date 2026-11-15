import { useEffect } from "react";
import { useSearchParams } from "react-router";

type Editing<Row> = Row | "new" | null;

/**
 * Редактор шаблона — страницей на месте списка (стандарт интерфейса §6: больше 15 полей и предпросмотр — страница):
 * открытый шаблон живёт в адресе `?edit=<id>` или `?edit=new`. Открытие — новый шаг истории («Назад» браузера
 * возвращает к списку), закрытие заменяет шаг. Каталог шаблонов (план 2.7) открывает редактор адресом `?template=<id>` —
 * он превращается в `?edit=<id>`.
 */
export function useEditParam<Row extends { id: string }>(
  items: readonly Row[] | undefined,
): [Editing<Row>, (row: Editing<Row>) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("edit");
  const requested = params.get("template");
  useEffect(() => {
    if (!requested) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("template");
        next.set("edit", requested);
        return next;
      },
      { replace: true },
    );
  }, [requested, setParams]);
  const editing: Editing<Row> =
    raw === "new" ? "new" : raw && items ? (items.find((item) => item.id === raw) ?? null) : null;
  const set = (row: Editing<Row>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (row === null) next.delete("edit");
        else next.set("edit", row === "new" ? "new" : row.id);
        return next;
      },
      { replace: row === null },
    );
  };
  return [editing, set];
}
