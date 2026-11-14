import { App, Button, Empty, Modal, Radio, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import { useCopyCalcLines, useListCalcPrevious } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { calcRef, useApplySheet, useErrorText } from "./api";

/**
 * «Как в прошлой заявке» (план 1.5): состав прошлого расчёта того же клиента новыми строками; цены — сегодняшние
 * (ERP подставляет действующие цены партнёров). Копируются строки своей зоны, остальные добавит коллега.
 */
export function PreviousModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const { date } = useFormat();
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const list = useListCalcPrevious(calcRef(sheet.number));
  const [source, setSource] = useState<string | null>(null);
  const copy = useCopyCalcLines({
    mutation: {
      onSuccess: (result) => {
        apply(result.sheet);
        void message.success(
          result.skipped
            ? t("previous.doneSkipped", { count: result.skipped })
            : t("previous.done"),
        );
        onClose();
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  const items = list.data?.items ?? [];

  return (
    <Modal
      open
      width={640}
      title={t("previous.title")}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="close" onClick={onClose}>
          {t("parse.cancel")}
        </Button>,
        <Button
          key="copy"
          type="primary"
          disabled={source === null}
          loading={copy.isPending}
          onClick={() => {
            if (source) copy.mutate({ number: calcRef(sheet.number), data: { source } });
          }}
        >
          {t("previous.copy")}
        </Button>,
      ]}
    >
      <p>{t("previous.intro")}</p>
      {list.isPending ? (
        <div role="status">
          <Spin size="small" /> {t("previous.loading")}
        </div>
      ) : items.length === 0 ? (
        <Empty description={t("previous.empty")} />
      ) : (
        <Radio.Group
          className="pf-calc-previous"
          aria-label={t("previous.title")}
          value={source}
          onChange={(event) => {
            setSource(String(event.target.value));
          }}
        >
          {items.map((item) => (
            <Radio key={item.number} value={item.number}>
              <strong>{item.number}</strong> · {date(item.created_at)} ·{" "}
              {t("previous.lines", { count: item.lines })}
              <span className="pf-hint"> · {item.names.join(", ")}</span>
            </Radio>
          ))}
        </Radio.Group>
      )}
    </Modal>
  );
}
