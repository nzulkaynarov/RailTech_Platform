import { App, Button, Form, Input, InputNumber, Modal, Radio } from "antd";
import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import { useAddCalcLines } from "../../../shared/api/generated/platform-bff";
import { calcRef, useApplySheet, useErrorText } from "./api";

interface Values {
  name: string;
  quantity: number;
  unit?: string;
  kind: "goods" | "service";
}

/** Новая строка вручную: товар (визирует снабженец) или услуга (гл. инженер) — тип доступен, если у роли есть его зона. */
export function AddLineModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const [form] = Form.useForm<Values>();
  const add = useAddCalcLines({
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
  const initialKind = sheet.rights.goods ? "goods" : "service";
  return (
    <Modal
      open
      title={t("add.title")}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("add.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={add.isPending}
          onClick={() => {
            form.submit();
          }}
        >
          {t("add.submit")}
        </Button>,
      ]}
    >
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={{ quantity: 1, kind: initialKind }}
        onFinish={(values) => {
          add.mutate({
            number: calcRef(sheet.number),
            data: {
              lines: [
                {
                  name: values.name.trim(),
                  quantity: values.quantity,
                  kind: values.kind,
                  ...(values.unit ? { unit: values.unit.trim() } : {}),
                },
              ],
            },
          });
        }}
      >
        <Form.Item
          name="name"
          label={t("add.name")}
          rules={[{ required: true, whitespace: true, message: t("add.nameRequired") }]}
        >
          <Input maxLength={500} />
        </Form.Item>
        <div className="pf-calc-add-row">
          <Form.Item name="quantity" label={t("add.quantity")} rules={[{ required: true }]}>
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item name="unit" label={t("add.unit")}>
            <Input maxLength={32} />
          </Form.Item>
        </div>
        <Form.Item name="kind" label={t("add.kind")} extra={t("add.kindHint")}>
          <Radio.Group>
            <Radio value="goods" disabled={!sheet.rights.goods}>
              {t("add.kindGoods")}
            </Radio>
            <Radio value="service" disabled={!sheet.rights.services}>
              {t("add.kindService")}
            </Radio>
          </Radio.Group>
        </Form.Item>
      </Form>
    </Modal>
  );
}
