import { App, Form, Input, Select, Alert, Button } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { Zone, ZoneUpdate } from "../../../shared/api/generated/model";
import {
  useActivateResponsibilityZone,
  useCreateResponsibilityZone,
  useDeactivateResponsibilityZone,
  useListEmployees,
  useUpdateResponsibilityZone,
} from "../../../shared/api/generated/platform-bff";
import { DateField } from "../../../shared/ui/DateField";
import { EmployeePicker, type EmployeeOption } from "../../../shared/ui/EmployeePicker";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { sectionLabel, sectionOptions, slugOf, zoneText } from "./model";

export type ZoneTarget = { mode: "new" } | { mode: "edit"; id: string };

interface PeopleValues {
  responsible: string | undefined;
  deputy: string | undefined;
  curator: string | undefined;
  basis: string;
  validFrom: string;
  validTo: string;
}

interface NewValues {
  nameRu: string;
  nameUz: string;
  nameEn: string;
  descRu: string;
  descUz: string;
  descEn: string;
  sections: string[];
}

/** Поле формы поверх общего выбора сотрудника: `Form.Item` задаёт `value` и `onChange`. */
function PersonField({
  value,
  onChange,
  ...rest
}: {
  value?: string | undefined;
  onChange?: (id: string | undefined) => void;
  id: string;
  options: readonly EmployeeOption[];
  loading: boolean;
  placeholder: string;
  emptyText: string;
  disabled: boolean;
}) {
  return (
    <EmployeePicker
      {...rest}
      value={value}
      onChange={(id) => {
        onChange?.(id);
      }}
    />
  );
}

function errorText(t: (key: string) => string, error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return t("errors.invalid");
    if (error.status === 409) return t("errors.conflict");
    if (error.status === 403) return t("errors.FORBIDDEN");
  }
  return t("errors.DEFAULT");
}

/**
 * Боковое окно зоны (стандарт интерфейса §6): «Новая зона» из существующих разделов прав или карточка зоны — люди через
 * общий выбор сотрудника, основание и срок. Права решает сервер: директор назначает людей, заводит и выключает зоны
 * администратор. Нехватка прав у ответственного — предупреждение, не запрет.
 */
export function ZoneSheet({
  target,
  zones,
  canAssign,
  canManage,
  onChanged,
  onClose,
}: {
  target: ZoneTarget;
  zones: readonly Zone[];
  canAssign: boolean;
  canManage: boolean;
  onChanged: () => void;
  onClose: () => void;
}) {
  const zone = target.mode === "edit" ? zones.find((z) => z.id === target.id) : undefined;
  if (target.mode === "edit" && !zone) return null;
  return zone ? (
    <EditSheet
      key={zone.id}
      zone={zone}
      canAssign={canAssign}
      canManage={canManage}
      onChanged={onChanged}
      onClose={onClose}
    />
  ) : (
    <NewSheet onChanged={onChanged} onClose={onClose} />
  );
}

function EditSheet({
  zone,
  canAssign,
  canManage,
  onChanged,
  onClose,
}: {
  zone: Zone;
  canAssign: boolean;
  canManage: boolean;
  onChanged: () => void;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("zones");
  const { message } = App.useApp();
  const formId = useId();
  const [form] = Form.useForm<PeopleValues>();
  const [error, setError] = useState<string | null>(null);
  const staff = useListEmployees({ status: "active" }, { query: { staleTime: 5 * 60_000 } });
  const update = useUpdateResponsibilityZone();
  const off = useDeactivateResponsibilityZone();
  const on = useActivateResponsibilityZone();
  const options: EmployeeOption[] = (staff.data?.items ?? []).map((e) => ({
    id: e.id,
    name: e.name,
    position: e.position ?? null,
  }));
  // Назначенный, но уже отключённый сотрудник остаётся в списке выбранных, чтобы его видно и можно было заменить.
  for (const person of [zone.responsible, zone.deputy, zone.curator]) {
    if (person && !options.some((o) => o.id === person.id)) {
      options.push({ id: person.id, name: person.name, position: person.position ?? null });
    }
  }
  const initial: PeopleValues = {
    responsible: zone.responsible?.id,
    deputy: zone.deputy?.id,
    curator: zone.curator?.id,
    basis: zone.basis,
    validFrom: zone.valid_from ?? "",
    validTo: zone.valid_to ?? "",
  };
  const readOnly = !canAssign || !zone.active;
  const title = t("sheet.editTitle", { name: zoneText(zone.name, i18n.language) });

  const submit = async (values: PeopleValues) => {
    setError(null);
    const data: ZoneUpdate = {
      responsible_id: values.responsible ?? null,
      deputy_id: values.deputy ?? null,
      curator_id: values.curator ?? null,
      basis: values.basis.trim(),
      valid_from: values.validFrom || null,
      valid_to: values.validTo || null,
    };
    try {
      await update.mutateAsync({ id: zone.id, data });
      onChanged();
      void message.success(t("saved"));
      onClose();
    } catch (caught) {
      setError(errorText(t, caught));
    }
  };

  const toggle = async () => {
    setError(null);
    try {
      if (zone.active) await off.mutateAsync({ id: zone.id });
      else await on.mutateAsync({ id: zone.id });
      onChanged();
      void message.success(zone.active ? t("deactivated") : t("activated"));
      onClose();
    } catch (caught) {
      setError(errorText(t, caught));
    }
  };

  const picker = (name: "responsible" | "deputy" | "curator") => (
    <Form.Item name={name} label={t(`sheet.${name}`)} htmlFor={`${formId}-${name}`}>
      <PersonField
        id={`${formId}-${name}`}
        options={options}
        loading={staff.isPending}
        placeholder={t("sheet.pick")}
        emptyText={t("sheet.noStaff")}
        disabled={readOnly}
      />
    </Form.Item>
  );

  return (
    <FormSheet
      title={title}
      formId={formId}
      submitLabel={t("sheet.save")}
      saving={update.isPending}
      readOnly={readOnly}
      dirty={form.isFieldsTouched()}
      error={error ? <Alert type="error" showIcon role="alert" message={error} /> : undefined}
      onCancel={onClose}
    >
      <p>{zoneText(zone.description, i18n.language)}</p>
      <p className="pf-hint">
        {t("sheet.sections")}:{" "}
        {zone.sections.map((key) => sectionLabel(key, i18n.language)).join("; ")}
      </p>
      {zone.problems.map((problem) => (
        <Alert
          key={problem.code}
          type={problem.severity === "warning" ? "warning" : "error"}
          showIcon
          message={t(`problem.${problem.code}`)}
          description={t(`problemText.${problem.code}`, {
            sections: (problem.sections ?? [])
              .map((key) => sectionLabel(key, i18n.language))
              .join("; "),
          })}
          style={{ marginBottom: 12 }}
        />
      ))}
      <Form<PeopleValues>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        disabled={readOnly}
        onFinish={(values) => {
          void submit(values);
        }}
      >
        {picker("responsible")}
        {picker("deputy")}
        {picker("curator")}
        <Form.Item name="basis" label={t("sheet.basis")}>
          <Input maxLength={500} placeholder={t("sheet.basisPlaceholder")} />
        </Form.Item>
        <Form.Item name="validFrom" label={t("sheet.validFrom")} htmlFor={`${formId}-from`}>
          <DateField id={`${formId}-from`} />
        </Form.Item>
        <Form.Item name="validTo" label={t("sheet.validTo")} htmlFor={`${formId}-to`}>
          <DateField id={`${formId}-to`} />
        </Form.Item>
      </Form>
      {canManage ? (
        <Button
          loading={off.isPending || on.isPending}
          onClick={() => {
            void toggle();
          }}
        >
          {zone.active ? t("sheet.deactivate") : t("sheet.activate")}
        </Button>
      ) : null}
    </FormSheet>
  );
}

function NewSheet({ onChanged, onClose }: { onChanged: () => void; onClose: () => void }) {
  const { t, i18n } = useTranslation("zones");
  const { message } = App.useApp();
  const formId = useId();
  const [form] = Form.useForm<NewValues>();
  const [error, setError] = useState<string | null>(null);
  const create = useCreateResponsibilityZone();
  const required = [{ required: true, whitespace: true, message: t("required") }];
  // У множественного выбора правило `required` ставит `aria-required` на контейнер без роли — axe это не принимает.
  const sectionRules = [
    {
      validator: (_: unknown, value: unknown) =>
        Array.isArray(value) && value.length > 0
          ? Promise.resolve()
          : Promise.reject(new Error(t("pickSections"))),
    },
  ];

  const submit = async (values: NewValues) => {
    setError(null);
    try {
      await create.mutateAsync({
        data: {
          code: slugOf(values.nameEn),
          name: { ru: values.nameRu.trim(), uz: values.nameUz.trim(), en: values.nameEn.trim() },
          description: {
            ru: values.descRu.trim(),
            uz: values.descUz.trim(),
            en: values.descEn.trim(),
          },
          sections: values.sections,
        },
      });
      onChanged();
      void message.success(t("created"));
      onClose();
    } catch (caught) {
      setError(errorText(t, caught));
    }
  };

  return (
    <FormSheet
      title={t("sheet.addTitle")}
      formId={formId}
      submitLabel={t("sheet.create")}
      saving={create.isPending}
      dirty={form.isFieldsTouched()}
      error={error ? <Alert type="error" showIcon role="alert" message={error} /> : undefined}
      onCancel={onClose}
    >
      <Form<NewValues>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={{ descRu: "", descUz: "", descEn: "" }}
        onFinish={(values) => {
          void submit(values);
        }}
      >
        <Form.Item name="nameRu" label={t("sheet.nameRu")} rules={required}>
          <Input maxLength={120} />
        </Form.Item>
        <Form.Item name="nameUz" label={t("sheet.nameUz")} rules={required}>
          <Input maxLength={120} />
        </Form.Item>
        <Form.Item name="nameEn" label={t("sheet.nameEn")} rules={required}>
          <Input maxLength={120} />
        </Form.Item>
        <Form.Item name="descRu" label={t("sheet.descRu")}>
          <Input maxLength={1000} />
        </Form.Item>
        <Form.Item name="descUz" label={t("sheet.descUz")}>
          <Input maxLength={1000} />
        </Form.Item>
        <Form.Item name="descEn" label={t("sheet.descEn")}>
          <Input maxLength={1000} />
        </Form.Item>
        <Form.Item
          name="sections"
          label={t("sheet.sections")}
          extra={t("sheet.sectionsHint")}
          rules={sectionRules}
        >
          <Select
            mode="multiple"
            showSearch
            optionFilterProp="label"
            options={sectionOptions(i18n.language)}
          />
        </Form.Item>
      </Form>
    </FormSheet>
  );
}
