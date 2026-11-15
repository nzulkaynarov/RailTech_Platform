import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, InputNumber, Radio, Select } from "antd";
import { RowActions, ROW_ACTIONS_WIDTH } from "../../../shared/ui/RowActions";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type {
  LetterResolutionKind,
  ResolutionTemplate,
  ResolutionTemplateIn,
} from "../../../shared/api/generated/model";
import {
  getListResolutionTemplatesQueryKey,
  useCreateResolutionTemplate,
  useDeleteResolutionTemplate,
  useListEdsStaff,
  useListResolutionTemplates,
  useUpdateResolutionTemplate,
} from "../../../shared/api/generated/platform-bff";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { useResolutionKindName } from "../../eds/dictionaries";
import { RESOLUTION_KINDS, needsExecutor } from "../../eds/inbox/officeModel";
import { ConfirmModal, ListTable, TabHeader } from "../company/common";
import { useRequestedTemplate } from "../settings/useRequestedTemplate";
import { UnitLabel } from "../../../shared/ui/UnitLabel";
import { unitOf } from "../../../shared/lib/unit";

const ADDRESSEE = "addressee";
const NONE = "none";

interface Values {
  name: string;
  kind: LetterResolutionKind;
  text: string;
  /** `none`, `addressee` или id сотрудника */
  responsible: string;
  coIds: string[];
  acquaintIds: string[];
  dueDays: number | null;
}

function errorText(t: (key: string) => string, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (reason === "name_taken" || reason === "company_template_admin_only") {
      return t(`office.templates.errors.${reason}`);
    }
    if (error.status === 422) return t("office.templates.errors.invalid");
  }
  return t("office.templates.errors.DEFAULT");
}

/**
 * Настройки · Документооборот · Шаблоны резолюций (EDS-REG, R2; эталоны — Directum RX, 1С:Документооборот 3.0). Общие
 * шаблоны ведёт администратор; свои личные директор и делопроизводитель сохраняют прямо из формы резолюции, здесь их
 * тоже видно. Шаблон только заполняет форму резолюции: правка и удаление уже наложенных резолюций не меняют.
 */
export function TemplatesTab({ readOnly }: { readOnly: boolean }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const kindName = useResolutionKindName();
  const query = useListResolutionTemplates();
  const [editing, setEditing] = useState<ResolutionTemplate | "new" | null>(null);
  const [removing, setRemoving] = useState<ResolutionTemplate | null>(null);
  useRequestedTemplate(query.data?.items, setEditing);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListResolutionTemplatesQueryKey() });
  };
  const remove = useDeleteResolutionTemplate({
    mutation: {
      onSuccess: () => {
        refresh();
        setRemoving(null);
        void message.success(t("settings.templates.deleted"));
      },
    },
  });
  const items = query.data?.items ?? [];
  const add = (
    <Button
      type="primary"
      disabled={readOnly}
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("settings.templates.add")}
    </Button>
  );
  const responsibleText = (row: ResolutionTemplate) =>
    row.responsible_type === "person"
      ? (row.responsible?.name ?? "—")
      : row.responsible_type === "addressee"
        ? t("settings.templates.addressee")
        : needsExecutor(row.kind)
          ? t("settings.templates.chooseLater")
          : "—";

  return (
    <div className="pf-co-body">
      <TabHeader title={t("settings.templates.title")} hint={t("settings.templates.hint")} />
      <div className="pf-co-actions">{add}</div>
      {query.isError ? (
        <Alert type="error" showIcon role="alert" message={t("office.templates.unavailable")} />
      ) : null}
      <ListTable<ResolutionTemplate>
        tableId="admin.docflow.templates"
        label={t("settings.templates.title")}
        data={items}
        loading={query.isPending}
        rowKey={(row) => row.id}
        empty={{
          title: t("settings.templates.empty.title"),
          text: t("settings.templates.empty.text"),
          // Пока список грузится, antd показывает пустое состояние под спиннером: без второй кнопки «Добавить».
          action: query.isPending ? undefined : add,
        }}
        columns={[
          {
            id: "name",
            header: t("settings.templates.name"),
            width: null,
            cell: (row) => <b>{row.name}</b>,
          },
          {
            id: "kind",
            header: t("settings.templates.kind"),
            width: null,
            cell: (row) => kindName(row.kind),
          },
          {
            id: "responsible",
            header: t("settings.templates.responsible"),
            width: null,
            cell: (row) => responsibleText(row),
          },
          {
            id: "due",
            header: t("settings.templates.due"),
            width: null,
            cell: (row) =>
              row.due_days ? t("settings.templates.days", { count: row.due_days }) : "—",
          },
          {
            id: "scope",
            header: t("settings.templates.scope"),
            width: null,
            cell: (row) =>
              row.scope === "company"
                ? t("settings.templates.company")
                : t("settings.templates.personal", { name: row.owner?.name ?? "" }),
          },
          {
            id: "actions",
            header: t("settings.dict.actions"),
            headerHidden: true,
            width: ROW_ACTIONS_WIDTH,
            cell: (row) => (
              <RowActions
                name={row.name}
                items={[
                  {
                    key: "edit",
                    label: t("settings.dict.edit"),
                    disabled: !row.editable,
                    onClick: () => {
                      setEditing(row);
                    },
                  },
                  {
                    key: "delete",
                    label: t("settings.dict.delete"),
                    danger: true,
                    disabled: !row.editable,
                    onClick: () => {
                      remove.reset();
                      setRemoving(row);
                    },
                  },
                ]}
              />
            ),
          },
        ]}
      />
      {editing !== null ? (
        <TemplateModal
          template={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={() => {
            refresh();
            setEditing(null);
            void message.success(t("settings.dict.saved"));
          }}
        />
      ) : null}
      <ConfirmModal
        open={removing !== null}
        title={t("settings.templates.deleteTitle", { name: removing?.name ?? "" })}
        okLabel={t("settings.dict.delete")}
        danger
        loading={remove.isPending}
        onOk={() => {
          if (removing) remove.mutate({ id: removing.id });
        }}
        onCancel={() => {
          setRemoving(null);
        }}
      >
        {remove.isError ? (
          <Alert type="error" showIcon role="alert" message={errorText(t, remove.error)} />
        ) : null}
      </ConfirmModal>
    </div>
  );
}

function toBody(values: Values, scope: ResolutionTemplateIn["scope"]): ResolutionTemplateIn {
  const executor = needsExecutor(values.kind);
  const person = executor && values.responsible !== NONE && values.responsible !== ADDRESSEE;
  return {
    name: values.name.trim(),
    scope,
    kind: values.kind,
    text: values.text.trim(),
    responsible_type: !executor
      ? "none"
      : person
        ? "person"
        : (values.responsible as "none" | "addressee"),
    responsible_id: person ? values.responsible : null,
    co_executor_ids: executor ? values.coIds : [],
    acquaint_ids: values.acquaintIds,
    due_days: executor ? values.dueDays : null,
  };
}

/** Новый или изменённый шаблон: название, вид, текст, ответственный, соисполнители, «ознакомить», срок в днях. */
function TemplateModal({
  template,
  onClose,
  onSaved,
}: {
  template: ResolutionTemplate | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const formId = useId();
  const kindName = useResolutionKindName();
  const [form] = Form.useForm<Values>();
  const [dirty, setDirty] = useState(false);
  // До первой отрисовки формы `useWatch` даёт `undefined` (тип antd этого не отражает).
  const watched = Form.useWatch("kind", form) as LetterResolutionKind | undefined;
  const kind = watched ?? template?.kind ?? "execute";
  const staff = useListEdsStaff({ query: { staleTime: 5 * 60_000 } });
  const create = useCreateResolutionTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateResolutionTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = template ? update : create;
  // Здесь администратор ведёт общие; без права администратора — свой личный шаблон.
  const scope: ResolutionTemplateIn["scope"] =
    template?.scope ?? (canEdit(me, "admin") ? "company" : "personal");
  const people = (staff.data?.items ?? []).map((p) => ({
    value: p.id,
    label: p.position ? `${p.name} · ${p.position}` : p.name,
  }));
  const initial: Values = {
    name: template?.name ?? "",
    kind: template?.kind ?? "execute",
    text: template?.text ?? "",
    responsible:
      template?.responsible_type === "person"
        ? (template.responsible?.id ?? NONE)
        : (template?.responsible_type ?? NONE),
    coIds: template?.co_executors.map((p) => p.id) ?? [],
    acquaintIds: template?.acquaint.map((p) => p.id) ?? [],
    dueDays: template?.due_days ?? null,
  };
  const required = [
    { required: true, whitespace: true, message: t("settings.templates.required") },
  ];

  return (
    <FormSheet
      title={template ? t("settings.templates.editTitle") : t("settings.templates.addTitle")}
      formId={formId}
      submitLabel={t("settings.dict.save")}
      saving={mutation.isPending}
      dirty={dirty}
      onCancel={onClose}
      error={
        mutation.isError ? (
          <Alert type="error" showIcon role="alert" message={errorText(t, mutation.error)} />
        ) : undefined
      }
    >
      <Form<Values>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        onValuesChange={() => {
          setDirty(true);
        }}
        onFinish={(values) => {
          const data = toBody(values, scope);
          if (template) update.mutate({ id: template.id, data });
          else create.mutate({ data });
        }}
      >
        <Form.Item name="name" label={t("office.templates.name")} rules={required}>
          <Input maxLength={120} autoComplete="off" />
        </Form.Item>
        <Form.Item name="kind" label={t("office.kind.legend")}>
          <Radio.Group
            options={RESOLUTION_KINDS.map((value) => ({ value, label: kindName(value) }))}
          />
        </Form.Item>
        <Form.Item name="text" label={t("office.text.label")} rules={required}>
          <Input.TextArea maxLength={4000} autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
        {needsExecutor(kind) ? (
          <>
            <Form.Item name="responsible" label={t("office.responsible.label")}>
              <Select
                showSearch
                optionFilterProp="label"
                loading={staff.isPending}
                options={[
                  { value: NONE, label: t("settings.templates.chooseLater") },
                  { value: ADDRESSEE, label: t("settings.templates.addressee") },
                  ...people,
                ]}
              />
            </Form.Item>
            <Form.Item name="coIds" label={t("office.co.label")}>
              <Select mode="multiple" optionFilterProp="label" options={people} />
            </Form.Item>
            <Form.Item
              name="dueDays"
              label={<UnitLabel label={t("settings.templates.dueDays")} />}
              extra={t("settings.templates.dueHint")}
            >
              <InputNumber
                suffix={unitOf(t("settings.templates.dueDays"))}
                min={1}
                max={365}
                precision={0}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </>
        ) : null}
        <Form.Item name="acquaintIds" label={t("office.acquaint.label")}>
          <Select mode="multiple" optionFilterProp="label" options={people} />
        </Form.Item>
      </Form>
    </FormSheet>
  );
}
