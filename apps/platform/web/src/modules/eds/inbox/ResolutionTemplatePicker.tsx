import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Input, Modal, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard, ResolutionTemplate } from "../../../shared/api/generated/model";
import {
  getListResolutionTemplatesQueryKey,
  useCreateResolutionTemplate,
  useListResolutionTemplates,
} from "../../../shared/api/generated/platform-bff";
import { FormField } from "../../../shared/ui/FormParts";
import { companyDate } from "./api";
import { type OfficeValues, applyTemplate, templateFromForm } from "./officeModel";

/** Текст ошибки сохранения шаблона: причина EDS важнее кода. */
function saveErrorText(t: (key: string) => string, error: unknown): string {
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
 * «Из шаблона» и «Сохранить как шаблон» в форме резолюции (EDS-REG, R2; эталоны — шаблоны резолюций Directum RX и
 * 1С:Документооборот 3.0). Шаблон только заполняет поля — их можно поправить перед резолюцией. Свой шаблон сохраняет
 * директор и делопроизводитель, общий («для всех») — администратор.
 */
export function ResolutionTemplatePicker({
  letter,
  values,
  onApply,
  idPrefix,
}: {
  letter: Pick<LetterCard, "addressee" | "suggested_due">;
  values: OfficeValues;
  onApply: (values: OfficeValues) => void;
  idPrefix: string;
}) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const templates = useListResolutionTemplates({ query: { staleTime: 60_000 } });
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [nameError, setNameError] = useState(false);
  const create = useCreateResolutionTemplate({
    mutation: {
      onSuccess: (template) => {
        void queryClient.invalidateQueries({ queryKey: getListResolutionTemplatesQueryKey() });
        setSaving(false);
        void message.success(t("office.templates.saved", { name: template.name }));
      },
    },
  });
  const items = templates.data?.items ?? [];
  const mine = items.filter((item) => item.scope === "personal");
  const company = items.filter((item) => item.scope === "company");
  const options = [
    ...(mine.length > 0
      ? [{ label: t("office.templates.mine"), options: mine.map(toOption) }]
      : []),
    ...(company.length > 0
      ? [{ label: t("office.templates.company"), options: company.map(toOption) }]
      : []),
  ];
  const pickerId = `${idPrefix}-template`;
  const nameId = `${idPrefix}-template-name`;
  const canShare = canEdit(me, "admin");
  const ready = values.kind !== "" && values.text.trim() !== "";

  return (
    <div className="pf-res-templates">
      <FormField
        id={pickerId}
        label={t("office.templates.pick")}
        hint={
          templates.isError
            ? t("office.templates.unavailable")
            : items.length === 0 && !templates.isPending
              ? t("office.templates.none")
              : t("office.templates.hint")
        }
      >
        <Select<string>
          id={pickerId}
          className="pf-res-select"
          value={null}
          placeholder={t("office.templates.placeholder")}
          loading={templates.isPending}
          disabled={!templates.isPending && items.length === 0}
          showSearch
          optionFilterProp="label"
          options={options}
          aria-describedby={`${pickerId}-hint`}
          onChange={(id) => {
            const found = items.find((item) => item.id === id);
            if (!found) return;
            onApply(applyTemplate(found, letter, companyDate()));
            void message.info(t("office.templates.applied", { name: found.name }));
          }}
        />
      </FormField>
      <Button
        disabled={!ready}
        onClick={() => {
          create.reset();
          setName("");
          setShared(false);
          setNameError(false);
          setSaving(true);
        }}
      >
        {t("office.templates.saveAs")}
      </Button>
      <Modal
        open={saving}
        title={t("office.templates.saveTitle")}
        onCancel={() => {
          setSaving(false);
        }}
        destroyOnHidden
        maskClosable={false}
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setSaving(false);
            }}
          >
            {t("office.templates.cancel")}
          </Button>,
          <Button
            key="save"
            type="primary"
            loading={create.isPending}
            onClick={() => {
              if (name.trim() === "") {
                setNameError(true);
                return;
              }
              create.mutate({
                data: templateFromForm(
                  values,
                  name,
                  shared ? "company" : "personal",
                  companyDate(),
                ),
              });
            }}
          >
            {t("office.templates.save")}
          </Button>,
        ]}
      >
        {create.isError ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={saveErrorText(t, create.error)}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <FormField
          id={nameId}
          label={t("office.templates.name")}
          hint={t("office.templates.nameHint")}
        >
          <Input
            id={nameId}
            value={name}
            maxLength={120}
            autoComplete="off"
            status={nameError ? "error" : undefined}
            aria-invalid={nameError || undefined}
            aria-describedby={`${nameId}-hint`}
            onChange={(event) => {
              setName(event.target.value);
              setNameError(false);
            }}
          />
          {nameError ? (
            <span className="pf-res-error" role="alert">
              {t("office.templates.nameRequired")}
            </span>
          ) : null}
        </FormField>
        {canShare ? (
          <Checkbox
            checked={shared}
            onChange={(event) => {
              setShared(event.target.checked);
            }}
          >
            {t("office.templates.shared")}
          </Checkbox>
        ) : null}
      </Modal>
    </div>
  );
}

function toOption(template: ResolutionTemplate) {
  return { value: template.id, label: template.name };
}
