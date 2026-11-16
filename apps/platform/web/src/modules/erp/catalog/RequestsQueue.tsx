import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import type { CatalogItem } from "../../../shared/api/generated/model";
import {
  getListCatalogItemsQueryKey,
  useListCatalogItems,
  useMergeCatalogItem,
} from "../../../shared/api/generated/platform-bff";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";
import type { Column } from "./common";
import { catalogErrorText } from "./errors";

/** Сколько позиций ждут разбора в «Новых из заявок» (ADR-0027): страница размером 1, берётся `total`. */
export function useRequestsCount(): number | undefined {
  const query = useListCatalogItems({ review: "requests", page: 1, page_size: 1 });
  return query.data?.total;
}

/** Похожая карточка под названием: с чем совпала и с какой карточкой. */
export function DuplicateHint({ row }: { row: CatalogItem }) {
  const { t } = useTranslation("catalog");
  const dup = row.duplicate;
  if (!dup) return null;
  return (
    <span className="pf-cat-sub pf-cat-duplicate">
      {t("queue.duplicate", { name: dup.name, sku: dup.sku })} — {t(`queue.duplicateBy.${dup.by}`)}
    </span>
  );
}

/** «Слить с …»: строки заявок, КП и заказов переходят к похожей карточке, черновик — в архив. Подтверждение обязательно. */
function MergeButton({ row }: { row: CatalogItem }) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const client = useQueryClient();
  const confirm = useConfirmAction();
  const merge = useMergeCatalogItem();
  const dup = row.duplicate;
  if (!dup) return null;
  return (
    <Button
      size="small"
      type="primary"
      loading={merge.isPending}
      aria-label={t("queue.mergeLabel", { name: row.name, sku: dup.sku })}
      onClick={() => {
        confirm({
          action: t("queue.mergeAction"),
          object: `«${row.name}»`,
          summary: t("queue.mergeSummary", { name: dup.name }),
          onConfirm: () => {
            merge.mutate(
              { id: row.id, data: { into: dup.id } },
              {
                onSuccess: () => {
                  void client.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
                  void message.success(t("queue.merged"));
                },
                onError: (error) => {
                  void message.error(catalogErrorText(t, error));
                },
              },
            );
          },
        });
      }}
    >
      {t("queue.merge", { sku: dup.sku })}
    </Button>
  );
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
