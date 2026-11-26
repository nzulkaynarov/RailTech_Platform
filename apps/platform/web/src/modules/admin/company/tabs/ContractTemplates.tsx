import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Select, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../../app/auth/useAuth";
import { canEdit } from "../../../../app/access";
import type { ContractTemplate, ContractTemplateIn } from "../../../../shared/api/generated/model";
import {
  getListContractTemplatesQueryKey,
  useApproveContractTemplate,
  useCreateContractTemplate,
  useListContractTemplates,
  useNewContractTemplateEdition,
  useReturnContractTemplateToDraft,
  useSubmitContractTemplate,
} from "../../../../shared/api/generated/platform-bff";
import { ApiError } from "../../../../shared/api/errors";
import { useFormat } from "../../../../shared/lib/useFormat";
import { RowActions, ROW_ACTIONS_WIDTH } from "../../../../shared/ui/RowActions";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { FormModal, ListTable, QueryGate, TabHeader } from "../common";

/** Текст отказа словами: подкод ERP (`details.reason`), иначе общий. */
function refusal(t: (key: string, options?: { defaultValue: string }) => string, error: unknown) {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string") {
      const text = t(`contractTemplates.errors.${reason}`, { defaultValue: "" });
      if (text) return text;
    }
  }
  return t("contractTemplates.errors.generic");
}

/**
 * Документы · Шаблоны · Договоры (ДОК-10, макет — доска 39): шаблоны договоров со статусом, редакцией и тем, кто утвердил.
 * «Новая редакция» (от утверждённого), «На утверждение» (черновик), «Утвердить» (держателю зоны «Право»). Закреплённый текст
 * в сделке не правится; в сделке предлагаются только утверждённые шаблоны вида контрагента.
 */
export function ContractTemplates({ titled = true }: { titled?: boolean }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { me } = useAuth();
  const format = useFormat();
  const query = useListContractTemplates();
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<ContractTemplateIn>();
  // Утверждает держатель зоны «Право»; администратор — всегда. Решающее слово за ERP.
  const mayApprove = canEdit(me, "eds.visa.legal") || canEdit(me, "admin");
  // Готовят шаблоны те, кто ведёт договоры или настройки; юрист без этих разделов только утверждает.
  const mayPrepare = canEdit(me, "eds.projects") || canEdit(me, "company.settings");

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListContractTemplatesQueryKey() });
  const done = (key: string) => () => {
    void refresh();
    void message.success(t(key));
  };
  const failed = (error: unknown) => {
    void message.error(refusal(t, error));
    void refresh();
  };
  const edition = useNewContractTemplateEdition({
    mutation: { onSuccess: done("contractTemplates.done.edition"), onError: failed },
  });
  const submit = useSubmitContractTemplate({
    mutation: { onSuccess: done("contractTemplates.done.submit"), onError: failed },
  });
  const approve = useApproveContractTemplate({
    mutation: { onSuccess: done("contractTemplates.done.approve"), onError: failed },
  });
  const back = useReturnContractTemplateToDraft({
    mutation: { onSuccess: done("contractTemplates.done.back"), onError: failed },
  });
  const create = useCreateContractTemplate({
    mutation: {
      onSuccess: () => {
        setCreating(false);
        form.resetFields();
        done("contractTemplates.done.create")();
      },
    },
  });

  const when = (value: string | null | undefined) => (value ? format.date(value) : "");
  const detail = (row: ContractTemplate) => {
    if (row.status === "approved") {
      return t("contractTemplates.approvedLine", {
        edition: row.edition,
        date: when(row.approved_at),
        who: row.approved_by ?? "—",
      });
    }
    if (row.status === "on_approval") {
      return t("contractTemplates.waitingLine", {
        edition: row.edition,
        date: when(row.submitted_at),
      });
    }
    return t("contractTemplates.draftLine", { edition: row.edition });
  };

  const add = mayPrepare ? (
    <Button
      type="primary"
      onClick={() => {
        setCreating(true);
      }}
    >
      {t("contractTemplates.add")}
    </Button>
  ) : null;

  return (
    <div className="pf-fp-stack">
      {titled ? (
        <TabHeader title={t("contractTemplates.title")} hint={t("contractTemplates.hint")} />
      ) : (
        <Typography.Paragraph type="secondary">{t("contractTemplates.hint")}</Typography.Paragraph>
      )}
      <QueryGate query={query}>
        {({ items }) => (
          <>
            {items.length > 0 ? <div>{add}</div> : null}
            <ListTable<ContractTemplate>
              tableId="admin.company.contractTemplates"
              label={t("contractTemplates.title")}
              data={items}
              rowKey={(row) => row.id}
              empty={{
                title: t("contractTemplates.empty.title"),
                text: t("contractTemplates.empty.text"),
                action: add,
              }}
              columns={[
                {
                  id: "name",
                  header: t("contractTemplates.columns.name"),
                  width: null,
                  cell: (row) => row.name,
                },
                {
                  id: "counterparty",
                  header: t("contractTemplates.columns.counterparty"),
                  width: 140,
                  cell: (row) =>
                    row.counterparty
                      ? t(`contractTemplates.counterparty.${row.counterparty}`)
                      : "—",
                },
                {
                  id: "status",
                  header: t("status"),
                  width: 170,
                  cell: (row) => (
                    <StatusTag kind="contractTemplate" status={row.status}>
                      {t(`contractTemplates.status.${row.status}`)}
                    </StatusTag>
                  ),
                },
                {
                  id: "edition",
                  header: t("contractTemplates.columns.edition"),
                  width: null,
                  cell: (row) => (
                    <span>
                      {detail(row)}
                      {row.status === "approved" && !row.is_active ? (
                        <Typography.Text type="secondary">
                          {" "}
                          · {t("contractTemplates.replaced")}
                        </Typography.Text>
                      ) : null}
                      {row.status === "draft" ? (
                        <Typography.Text type="secondary">
                          {" "}
                          · {t("contractTemplates.notOffered")}
                        </Typography.Text>
                      ) : null}
                      {row.languages.length < 3 ? (
                        <Typography.Text type="secondary">
                          {" "}
                          · {t("contractTemplates.fallback")}
                        </Typography.Text>
                      ) : null}
                    </span>
                  ),
                },
                {
                  id: "actions",
                  header: t("actions"),
                  headerHidden: true,
                  width: ROW_ACTIONS_WIDTH,
                  cell: (row) => {
                    const actions = [
                      row.status === "approved" && row.is_active && mayPrepare
                        ? {
                            key: "edition",
                            label: t("contractTemplates.actions.edition"),
                            onClick: () => {
                              edition.mutate({ id: row.id });
                            },
                          }
                        : null,
                      row.status === "draft" && mayPrepare
                        ? {
                            key: "submit",
                            label: t("contractTemplates.actions.submit"),
                            onClick: () => {
                              submit.mutate({ id: row.id });
                            },
                          }
                        : null,
                      row.status === "on_approval" && mayApprove
                        ? {
                            key: "approve",
                            label: t("contractTemplates.actions.approve"),
                            onClick: () => {
                              approve.mutate({ id: row.id });
                            },
                          }
                        : null,
                      row.status === "on_approval" && mayApprove
                        ? {
                            key: "back",
                            label: t("contractTemplates.actions.back"),
                            onClick: () => {
                              back.mutate({ id: row.id });
                            },
                          }
                        : null,
                    ].filter((item) => item !== null);
                    return actions.length === 0 ? null : (
                      <RowActions name={row.name} items={actions} />
                    );
                  },
                },
              ]}
            />
          </>
        )}
      </QueryGate>
      <Typography.Paragraph type="secondary">{t("contractTemplates.note")}</Typography.Paragraph>
      <FormModal
        open={creating}
        title={t("contractTemplates.createTitle")}
        formId="pf-contract-template-form"
        submitLabel={t("contractTemplates.createSubmit")}
        saving={create.isPending}
        error={create.error}
        onCancel={() => {
          setCreating(false);
        }}
      >
        <Form<ContractTemplateIn>
          id="pf-contract-template-form"
          form={form}
          layout="vertical"
          initialValues={{ counterparty: "client", subject: "supply" }}
          onFinish={(values) => {
            create.mutate({ data: values });
          }}
        >
          <Form.Item
            name="name"
            label={t("contractTemplates.columns.name")}
            rules={[{ required: true, message: t("required") }]}
          >
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="counterparty" label={t("contractTemplates.columns.counterparty")}>
            <Select
              options={(["client", "partner"] as const).map((value) => ({
                value,
                label: t(`contractTemplates.counterparty.${value}`),
              }))}
            />
          </Form.Item>
          <Form.Item name="subject" label={t("contractTemplates.columns.subject")}>
            <Select
              options={(["supply", "services"] as const).map((value) => ({
                value,
                label: t(`contractTemplates.subject.${value}`),
              }))}
            />
          </Form.Item>
        </Form>
      </FormModal>
    </div>
  );
}
