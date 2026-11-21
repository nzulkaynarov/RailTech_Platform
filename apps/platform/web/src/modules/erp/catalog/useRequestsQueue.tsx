import { useTranslation } from "react-i18next";

import type { CatalogItem } from "../../../shared/api/generated/model";
import { useListCatalogItems } from "../../../shared/api/generated/platform-bff";
import type { Column } from "./common";
import { MergeButton } from "./RequestsQueue";

/** Сколько позиций ждут разбора в «Новых из заявок» (ADR-0027): страница размером 1, берётся `total`. */
export function useRequestsCount(): number | undefined {
  const query = useListCatalogItems({ review: "requests", page: 1, page_size: 1 });
  return query.data?.total;
}

/** Колонки очереди «Новые из заявок»: спрос, где спрашивали, полнота и действие. Название — общая колонка списка. */
export function useRequestsColumns(): Column<CatalogItem>[] {
  const { t } = useTranslation("catalog");
  return [
    {
      key: "demand",
      title: t("queue.columns.demand"),
      num: true,
      render: (row) => String(row.demand ?? 0),
    },
    {
      key: "asked",
      title: t("queue.columns.askedIn"),
      render: (row) => {
        const shown = row.asked_in ?? [];
        if (shown.length === 0) return "—";
        const more = (row.asked_total ?? shown.length) - shown.length;
        // Номер на строку: длинные номера не налезают на соседние колонки
        return (
          <>
            {shown.map((number) => (
              <span key={number} className="pf-num pf-cat-asked">
                {number}
              </span>
            ))}
            {more > 0 ? (
              <span className="pf-cat-sub">{t("queue.askedMore", { count: more })}</span>
            ) : null}
          </>
        );
      },
    },
    {
      key: "completeness",
      title: t("queue.columns.completeness"),
      num: true,
      render: (row) =>
        row.completeness === null || row.completeness === undefined
          ? "—"
          : `${String(row.completeness)} %`,
    },
    {
      key: "action",
      title: t("queue.columns.action"),
      render: (row) => <MergeButton row={row} />,
    },
  ];
}
