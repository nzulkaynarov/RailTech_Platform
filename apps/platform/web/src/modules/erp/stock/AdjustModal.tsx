import { App, Button, Form, Input, InputNumber, Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { StockRow } from "../../../shared/api/generated/model";
import { useAdjustStock } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { clean, useErrorText, useRefreshStock } from "./api";

interface Values {
  quantity: number;
  cell?: string;
  note?: string;
}

/** Оприходовать (плюс) или списать (минус) вручную: начальные остатки, итоги инвентаризации. */
export function AdjustModal({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const [form] = Form.useForm<Values>();
  const adjust = useAdjustStock({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("adjust.done"));
        onClose();
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  return (
    <Modal
      open
      title={t("adjust.title", { name: row.name })}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={adjust.isPending}
          onClick={() => {
            form.submit();
          }}
        >
          {t("adjust.submit")}
        </Button>,
      ]}
    >
      <Form<Values>
        form={form}
        layout="vertical"
        onFinish={(values) => {
          const cell = clean(values.cell);
          const note = clean(values.note);
          adjust.mutate({
            data: {
              product_id: row.product_id,
              quantity: values.quantity,
              ...(cell ? { cell } : {}),
              ...(note ? { note } : {}),
            },
          });
        }}
      >
        <Form.Item
          name="quantity"
          label={t("adjust.quantity")}
          extra={t("adjust.quantityHint")}
          rules={[
            { required: true, message: t("adjust.quantityRequired") },
            {
              validator: (_rule, value: number | null) =>
                value === 0
                  ? Promise.reject(new Error(t("adjust.quantityRequired")))
                  : Promise.resolve(),
            },
          ]}
        >
          <InputNumber precision={0} />
        </Form.Item>
        <Form.Item name="cell" label={t("adjust.cell")}>
          <Input maxLength={32} />
        </Form.Item>
        <Form.Item name="note" label={t("adjust.note")}>
          <Input maxLength={500} />
        </Form.Item>
      </Form>
      <Consequence items={t("adjust.consequence", { returnObjects: true }) as string[]} />
    </Modal>
  );
}
