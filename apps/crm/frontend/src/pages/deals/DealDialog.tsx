import {
  Alert,
  App as AntApp,
  DatePicker,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useEffect } from "react";

import { useClients } from "../../api/adminQueries";
import { useDealOptions, useSaveDeal } from "../../api/dealQueries";
import type { DealCreate, DealOut, DealUpdate } from "../../api/generated/model";
import { useTeam } from "../../api/queries";
import {
  currencyOptions,
  externalStageColor,
  externalStageLabel,
  formatMoney,
  groupThousands,
  isErpMirror,
  parseAmount,
  stageLabel,
} from "../../domain/deals";
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

/** Тело сохранения: у зеркала заявки ERP — только поля CRM (ответственный и срок, I-26). */
function saveBody(v: Values, deal: DealOut | null): DealCreate | DealUpdate {
  const expected_close_date = v.expected_close_date?.format("YYYY-MM-DD") ?? null;
  const owner_user_id = v.owner_user_id ?? null;
  if (deal && isErpMirror(deal)) return { expected_close_date, owner_user_id };
  const common = {
    title: v.title.trim(),
    amount: v.amount ?? null,
    currency: v.currency?.trim().toUpperCase() || null,
    expected_close_date,
    owner_user_id,
  };
  if (!deal) return { ...common, client_id: v.client_id ?? null };
  return { ...common, stage: v.stage, lost_reason: v.stage === "lost" ? v.lost_reason : null };
}

/** Поля зеркальной сделки, которыми владеет ERP: только текстом — менять их можно в бэк-офисе. */
function ErpOwnedFacts({ deal }: { deal: DealOut }) {
  return (
    <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
      <Descriptions.Item label={t.deals.title}>{deal.title}</Descriptions.Item>
      <Descriptions.Item label={t.deals.amount}>
        {formatMoney(deal.amount, deal.currency)}
      </Descriptions.Item>
      <Descriptions.Item label={t.deals.stage}>{stageLabel(deal.stage)}</Descriptions.Item>
      {deal.stage === "lost" ? (
        <Descriptions.Item label={t.deals.reason}>
          {deal.lost_reason ?? t.common.none}
        </Descriptions.Item>
      ) : null}
    </Descriptions>
  );
}

/** Создание и правка сделки (одна форма; стадия и причина — только при правке). */
export function DealDialog({ open, deal, clientId, onClose }: Props) {
  const [form] = Form.useForm<Values>();
  const stage = Form.useWatch("stage", form);
  const chosenCurrency = Form.useWatch("currency", form);
  const options = useDealOptions();
  const team = useTeam();
  const clients = useClients("");
  const save = useSaveDeal();
  const onError = useApiErrorToast();
  const { message } = AntApp.useApp();
  const currency = options.data?.currency ?? "UZS";
  const erpOwned = deal !== null && isErpMirror(deal);

  useEffect(() => {
    if (open) form.setFieldsValue(initial(deal, clientId, currency));
  }, [open, deal, clientId, currency, form]);

  const submit = (v: Values) => {
    save.mutate(
      { id: deal?.id ?? null, body: saveBody(v, deal) },
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
        {deal?.erp_deal_id || deal?.external_stage ? (
          <Alert
            style={{ marginBottom: 16 }}
            type="info"
            showIcon
            message={
              <Space wrap size={8}>
                <span>{t.clients.inBackoffice}:</span>
                {deal.erp_deal_id ? <Tag color="blue">#{String(deal.erp_deal_id)}</Tag> : null}
                {deal.external_stage ? (
                  <Tag color={externalStageColor(deal.external_stage)}>
                    {externalStageLabel(deal.external_stage)}
                  </Tag>
                ) : null}
              </Space>
            }
            description={erpOwned ? `${t.deals.erpOwned}. ${t.deals.erpOwnedHint}` : undefined}
          />
        ) : null}
        {deal && erpOwned ? (
          <ErpOwnedFacts deal={deal} />
        ) : (
          <>
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
            <Form.Item name="currency" label={t.deals.currency} rules={[{ len: 3 }]}>
              <Select options={currencyOptions(currency).map((c) => ({ value: c, label: c }))} />
            </Form.Item>
            <Form.Item name="amount" label={t.deals.amount}>
              <InputNumber<number>
                min={0}
                step={1000}
                style={{ width: "100%" }}
                formatter={groupThousands}
                parser={parseAmount}
                suffix={chosenCurrency ?? currency}
              />
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
          </>
        )}
        <Form.Item name="expected_close_date" label={t.deals.expected}>
          <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
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
