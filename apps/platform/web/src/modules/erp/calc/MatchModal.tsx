import { App, Button, Form, Input, Modal } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcLine, CalcSheet } from "../../../shared/api/generated/model";
import {
  useSearchCalcCatalog,
  useUpdateCalcLine,
} from "../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { calcRef, useApplySheet, useErrorText } from "./api";

/**
 * Сопоставление строки с каталогом: поиск по словам названия, артикула, кода производителя и ГОСТ (ERP, без ИИ);
 * человек выбирает карточку — строка получает её тип, склад и поставщика. Виза строки при этом снимается.
 */
export function MatchModal({
  sheet,
  line,
  onClose,
}: {
  sheet: CalcSheet;
  line: CalcLine;
  onClose: () => void;
}) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const [draft, setDraft] = useState(line.name);
  const [q, setQ] = useState(line.name);
  const search = useSearchCalcCatalog({ q }, { query: { enabled: q.trim().length > 0 } });
  const update = useUpdateCalcLine({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        onClose();
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  const items = search.data?.items ?? [];
  return (
    <Modal
      open
      title={t("match.title")}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t("match.cancel")}</Button>}
      destroyOnHidden
    >
      <Form
        layout="vertical"
        onFinish={() => {
          setQ(draft.trim());
        }}
      >
        <Form.Item
          label={t("match.search")}
          extra={t("match.searchHint")}
          htmlFor="pf-calc-match-q"
        >
          <Input.Search
            id="pf-calc-match-q"
            value={draft}
            enterButton={t("match.find")}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            onSearch={(value) => {
              setQ(value.trim());
            }}
          />
        </Form.Item>
      </Form>
      {search.isSuccess && items.length === 0 ? (
        <p className="pf-hint">{t("match.nothing")}</p>
      ) : null}
      <ul className="pf-calc-match">
        {items.map((item) => (
          <li key={item.id}>
            <div className="pf-calc-match-text">
              <span>{item.name}</span>
              <span className="pf-hint">
                {[
                  item.article,
                  t("match.stock", { count: item.on_hand }),
                  item.supplier_name && item.lead_days
                    ? t("match.supplier", { name: item.supplier_name, days: item.lead_days })
                    : item.supplier_name,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <StatusTag tone={item.kind === "service" ? "cyan" : "blue"}>
                {t(`lines.kind.${item.kind === "service" ? "service" : "goods"}`)}
              </StatusTag>
            </div>
            <Button
              size="small"
              loading={update.isPending && update.variables.data.product_id === item.id}
              aria-label={t("match.chooseLabel", { name: item.name })}
              onClick={() => {
                update.mutate({
                  number: calcRef(sheet.number),
                  lineId: line.id,
                  data: { product_id: item.id },
                });
              }}
            >
              {t("match.choose")}
            </Button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
