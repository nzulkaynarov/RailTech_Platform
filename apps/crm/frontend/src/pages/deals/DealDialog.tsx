import { App as AntApp, DatePicker, Form, Input, InputNumber, Modal, Select } from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useEffect } from "react";

import { useClients } from "../../api/adminQueries";
import { useDealOptions, useSaveDeal } from "../../api/dealQueries";
import type { DealOut } from "../../api/generated/model";
import { useTeam } from "../../api/queries";
import { stageLabel } from "../../domain/deals";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";

type Values = {
  title: string;
  client_id?: number | null;
  amount?: number | null;
  currency?: string;
  stage?: "open" | "won" | "lost";
  expected_close_date?: Dayjs | null;
  lost_reason?: string | null;
  owner_user_id?: number | null;
};

type Props = {
  open: boolean;
  deal: DealOut | null;
  /** Карточка клиента: клиент задан заранее и не меняется. */
  clientId?: number;
  onClose: () => void;
};

function initial(deal: DealOut | null, clientId: number | undefined, currency: string): Values {
  if (!deal) return { title: "", client_id: clientId ?? null, currency, stage: "open" };
  return {
    title: deal.title,
    client_id: deal.client_id,
    amount: deal.amount === null ? null : Number(deal.amount),
    currency: deal.currency,
    stage: deal.stage,
    expected_close_date: deal.expected_close_date ? dayjs(deal.expected_close_date) : null,
    lost_reason: deal.lost_reason,
    owner_user_id: deal.owner_user_id,
  };
}

/** Создание и правка сделки (одна форма; стадия и причина — только при правке). */
export function DealDialog({ open, deal, clientId, onClose }: Props) {
  const [form] = Form.useForm<Values>();
  const stage = Form.useWatch("stage", form);
  const options = useDealOptions();
  const team = useTeam();
  const clients = useClients("");
  const save = useSaveDeal();
  const onError = useApiErrorToast();
  const { message } = AntApp.useApp();
  const currency = options.data?.currency ?? "UZS";

  useEffect(() => {
    if (open) form.setFieldsValue(initial(deal, clientId, currency));
  }, [open, deal, clientId, currency, form]);

  const submit = (v: Values) => {
    const common = {
      title: v.title.trim(),
      amount: v.amount ?? null,
      currency: v.currency?.trim().toUpperCase() || null,
      expected_close_date: v.expected_close_date?.format("YYYY-MM-DD") ?? null,
      owner_user_id: v.owner_user_id ?? null,
    };
    const body = deal
      ? { ...common, stage: v.stage, lost_reason: v.stage === "lost" ? v.lost_reason : null }
      : { ...common, client_id: v.client_id ?? null };
    save.mutate(
      { id: deal?.id ?? null, body },
      {
        onSuccess: () => {
          void message.success(deal ? t.deals.saved : t.deals.created);
          onClose();
        },
        onError,
      },
    );
  };

  return (
    <Modal
      open={open}
      title={deal ? t.deals.editTitle.replace("{title}", deal.title) : t.deals.createTitle}
      okText={t.common.save}
      cancelText={t.actions.cancel}
      confirmLoading={save.isPending}
      onOk={() => {
        form.submit();
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="title" label={t.deals.title} rules={[{ required: true, max: 255 }]}>
          <Input />
        </Form.Item>
        {!deal && clientId === undefined ? (
          <Form.Item name="client_id" label={t.deals.client}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={(clients.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
        ) : null}
        <Form.Item name="amount" label={t.deals.amount}>
          <InputNumber min={0} step={1000} className="settings-number" />
        </Form.Item>
        <Form.Item name="currency" label={t.deals.currency} rules={[{ len: 3 }]}>
          <Input maxLength={3} />
        </Form.Item>
        {deal ? (
          <Form.Item name="stage" label={t.deals.stage}>
            <Select
              options={(["open", "won", "lost"] as const).map((s) => ({
                value: s,
                label: stageLabel(s),
              }))}
            />
          </Form.Item>
        ) : null}
        {deal && stage === "lost" ? (
          <Form.Item name="lost_reason" label={t.deals.reason}>
            <Select
              allowClear
              options={(options.data?.lost_reasons ?? []).map((r) => ({ value: r, label: r }))}
            />
          </Form.Item>
        ) : null}
        <Form.Item name="expected_close_date" label={t.deals.expected}>
          <DatePicker format="DD.MM.YYYY" />
        </Form.Item>
        <Form.Item name="owner_user_id" label={t.deals.owner}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            options={(team.data ?? []).map((m) => ({ value: m.id, label: m.full_name }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
