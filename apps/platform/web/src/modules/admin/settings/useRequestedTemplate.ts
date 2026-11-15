import { useEffect } from "react";
import { useSearchParams } from "react-router";

/**
 * Каталог шаблонов (план 2.7) открывает редактор адресом `?template=<id>`: когда список загружен, шаблон с этим id
 * открывается, а параметр убирается — «Назад» и обновление страницы не открывают редактор снова.
 */
export function useRequestedTemplate<Row extends { id: string }>(
  items: readonly Row[] | undefined,
  open: (row: Row) => void,
): void {
  const [params, setParams] = useSearchParams();
  const requested = params.get("template");
  useEffect(() => {
    if (!requested || !items) return;
    const row = items.find((item) => item.id === requested);
    if (row) open(row);
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("template");
        return next;
      },
      { replace: true },
    );
    // open — сеттер состояния вызывающего: меняется вместе с ним, повторно не нужен
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested, items, setParams]);
}
