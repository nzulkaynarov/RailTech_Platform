import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import type { CatalogItem } from "../../../shared/api/generated/model";
import {
  getListCatalogItemsQueryKey,
  useMergeCatalogItem,
} from "../../../shared/api/generated/platform-bff";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";
import { catalogErrorText } from "./errors";

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
export function MergeButton({ row }: { row: CatalogItem }) {
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
