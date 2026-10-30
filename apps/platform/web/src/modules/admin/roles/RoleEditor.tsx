import { Alert, Button, Input, Radio } from "antd";
import type { TFunction } from "i18next";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { TEMPLATES } from "../../../app/rbac.generated";
import {
  fieldLabel,
  isSystemAdmin,
  lang,
  rolesAccess,
  sectionFullLabel,
} from "../../../entities/role/roles";
import { moduleName } from "../../registry";
import type { Role, RolePreview, SectionLevel } from "../../../shared/api/generated/model";
import { usePreviewRole } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ContextualSaveBar } from "../../../shared/ui/ContextualSaveBar";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { LockIcon } from "../../../shared/ui/icons";
import { isVersionConflict, roleErrorText } from "./errors";
import { type RoleDraft, type TemplateKey, TEMPLATE_KEYS, changesOf, newDraft } from "./draft";

function modulesLine(t: (key: string) => string, access: RoleDraft["access"]): string {
  return rolesAccess([{ access, system: false }])
    .modules.map((code) => moduleName(t, code))
    .join(", ");
}

/**
 * «Что произойдёт» из предпросмотра CRM: «1 сотрудник потеряет: …», «2 сотрудника потеряют: …» — число и глагол согласуются
 * плюральными формами i18next (`gained_one|few|many|other`, по `count` и языку).
 */
function previewLines(t: TFunction, language: string, preview: RolePreview): string[] {
  const levels = (items: readonly SectionLevel[]) =>
    items
      .map((s) =>
        t("admin.roles.preview.section", {
          section: sectionFullLabel(s.resource, language),
          level: t(`admin.roles.level.${s.level}`).toLocaleLowerCase(),
        }),
      )
      .join("; ");
  const fields = (items: readonly string[]) => items.map((f) => fieldLabel(f, language)).join(", ");
  const gainers = preview.employees.filter((e) => e.gained.length || e.fields_gained.length);
  const losers = preview.employees.filter((e) => e.lost.length || e.fields_lost.length);
  const lines: string[] = [];
  if (preview.employees_total === 0) lines.push(t("admin.roles.preview.nobody"));
  else if (preview.employees.length === 0) lines.push(t("admin.roles.preview.unchanged"));
  if (preview.gained.length) {
    lines.push(
      t("admin.roles.preview.gained", { count: gainers.length, list: levels(preview.gained) }),
    );
  }
  if (preview.lost.length) {
    lines.push(t("admin.roles.preview.lost", { count: losers.length, list: levels(preview.lost) }));
  }
  if (preview.fields_gained.length) {
    lines.push(t("admin.roles.preview.fieldsGained", { list: fields(preview.fields_gained) }));
  }
  if (preview.fields_lost.length) {
    lines.push(t("admin.roles.preview.fieldsLost", { list: fields(preview.fields_lost) }));
  }
  return lines;
}

/**
 * Роль в боковом окне только для чтения: замок у системной, что она даёт. `readOnly` — режим директора (BFF 0.4.0,
 * `admin: read`): любая роль без правки, без ссылки «Назначить роль сотруднику».
 */
export function SystemRoleCard({ role, readOnly = false }: { role: Role; readOnly?: boolean }) {
  const { t } = useTranslation("modules");
  return (
    <div className="pf-panel-stack">
      <div>
        <div className="pf-role-head">
          <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
            {role.name}
          </h3>
          {role.system ? (
            <StatusTag tone="default">
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <LockIcon size={12} />
                {t("admin.roles.system")}
              </span>
            </StatusTag>
          ) : null}
          <StatusTag tone="blue">
            {t("admin.roles.employeesCount", { count: role.employees })}
          </StatusTag>
        </div>
        {role.description ? (
          <p style={{ margin: "4px 0 0", color: "#595959" }}>{role.description}</p>
        ) : null}
      </div>
      <Alert
        type="info"
        showIcon
        message={
          role.system && !readOnly ? t("admin.roles.systemNote") : t("admin.roles.readOnlyNote")
        }
      />
      <Consequence
        title={t("admin.roles.gives")}
        items={[
          t("admin.roles.modules", { modules: modulesLine(t, draftAccess(role)) || "—" }),
          ...(isSystemAdmin(role) ? [t("admin.org.consequence.erpAdmin")] : []),
        ]}
      />
      {readOnly ? null : <LinkButton to="/admin/org">{t("admin.roles.assign")}</LinkButton>}
    </div>
  );
}

function draftAccess(role: Role): RoleDraft["access"] {
  return role.access;
}

export interface RoleEditorProps {
  /** Роль из данных; нет — черновик новой роли */
  role: Role | null;
  base: RoleDraft;
  draft: RoleDraft;
  onDraft: (next: RoleDraft) => void;
  onReset: () => void;
  onSave: () => void;
  saving: boolean;
  saveError: unknown;
  /** Роль изменена другим пользователем (409): перечитать роли и сбросить черновик */
  onReload: () => void;
  onDelete: () => void;
  deleting: boolean;
  deleteError: unknown;
}

/**
 * Редактор роли в боковом окне (ADR-0012): название, описание, сводка модулей, предупреждение про раздел Admin, главная
 * кнопка «Сохранить роль» / «Создать роль» и под ней «Что произойдёт» из `POST /admin/roles/preview`. Уровни по разделам
 * и поля с ограничением меняются в столбце роли в матрице. Удаление — только без сотрудников.
 */
export function RoleEditor({
  role,
  base,
  draft,
  onDraft,
  onReset,
  onSave,
  saving,
  saveError,
  onReload,
  onDelete,
  deleting,
  deleteError,
}: RoleEditorProps) {
  const { t, i18n } = useTranslation("modules");
  const nameId = useId();
  const descriptionId = useId();
  const templateId = useId();
  const deleteNoteId = useId();
  const [template, setTemplate] = useState<TemplateKey | "empty">("empty");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const changes = changesOf(base, draft);
  const isNew = role === null;
  const nameMissing = draft.name.trim() === "";
  const access = rolesAccess([{ access: draft.access, system: false }]);

  // «Что произойдёт» для существующей роли: предпросмотр CRM по черновику матрицы (после паузы ввода).
  const preview = usePreviewRole();
  const { mutate: requestPreview, reset: resetPreview } = preview;
  const matrixChanged = changes.access || changes.fields;
  const accessKey = JSON.stringify([draft.access, draft.restricted_fields]);
  useEffect(() => {
    if (!role || !matrixChanged) {
      resetPreview();
      return;
    }
    const timer = window.setTimeout(() => {
      requestPreview({
        data: {
          role_id: role.id,
          access: draft.access,
          restricted_fields: draft.restricted_fields,
        },
      });
    }, 250);
    return () => {
      window.clearTimeout(timer);
    };
    // accessKey — содержимое черновика матрицы; сам объект черновика новый на каждый ввод.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessKey, isNew, role?.id, matrixChanged, requestPreview, resetPreview]);

  const items: string[] = [];
  if (isNew) {
    items.push(t("admin.roles.new.created"));
    items.push(t("admin.roles.modules", { modules: modulesLine(t, draft.access) || "—" }));
    if (access.adminWithoutSystem) items.push(t("admin.roles.adminNote"));
    items.push(t("admin.roles.new.assign"));
  } else {
    if (changes.name) {
      items.push(t("admin.roles.renamed", { name: draft.name.trim(), count: role.employees }));
    }
    if (matrixChanged) {
      if (preview.isPending) items.push(t("admin.roles.preview.loading"));
      else if (preview.isError) items.push(t("admin.roles.preview.failed"));
      else if (preview.data) items.push(...previewLines(t, i18n.language, preview.data));
      items.push(t("admin.roles.modules", { modules: modulesLine(t, draft.access) || "—" }));
      if (access.adminWithoutSystem) items.push(t("admin.roles.adminNote"));
      items.push(t("admin.roles.applied"));
    }
    if (!changes.name && !matrixChanged && changes.description) {
      items.push(t("admin.roles.descriptionOnly"));
    }
  }

  const inUse = role !== null && role.employees > 0;
  const templateOptions = [
    { value: "empty", label: t("admin.roles.new.empty") },
    ...TEMPLATE_KEYS.map((key) => ({
      value: key,
      label: TEMPLATES[key].name[lang(i18n.language)],
    })),
  ];

  return (
    <form
      className="pf-panel-stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!saving && !nameMissing && (isNew || changes.any)) onSave();
      }}
    >
      <div className="pf-role-head">
        <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
          {isNew ? t("admin.roles.new.title") : role.name}
        </h3>
        {isNew ? null : (
          <StatusTag tone="blue">
            {t("admin.roles.employeesCount", { count: role.employees })}
          </StatusTag>
        )}
      </div>
      {isNew ? (
        <fieldset className="pf-roles" aria-describedby={templateId}>
          <legend className="pf-roles-legend">{t("admin.roles.new.from")}</legend>
          <Radio.Group
            value={template}
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
            options={templateOptions}
            onChange={(event) => {
              const value = String(event.target.value);
              const key = value === "empty" ? null : (value as TemplateKey);
              setTemplate(key ?? "empty");
              const next = newDraft(key, draft.name);
              onDraft({ ...next, description: draft.description });
            }}
          />
          <p id={templateId} className="pf-hint" style={{ margin: "4px 0 0" }}>
            {t("admin.roles.new.fromHint")}
          </p>
        </fieldset>
      ) : null}
      <div>
        <label htmlFor={nameId} style={{ display: "block", marginBottom: 4 }}>
          {t("admin.roles.name")}
        </label>
        <Input
          id={nameId}
          value={draft.name}
          maxLength={120}
          autoComplete="off"
          status={nameMissing && (changes.name || isNew) ? "error" : undefined}
          aria-invalid={nameMissing}
          onChange={(event) => {
            onDraft({ ...draft, name: event.target.value });
          }}
        />
      </div>
      <div>
        <label htmlFor={descriptionId} style={{ display: "block", marginBottom: 4 }}>
          {t("admin.roles.description")}
        </label>
        <Input.TextArea
          id={descriptionId}
          value={draft.description}
          maxLength={1000}
          autoSize={{ minRows: 2, maxRows: 5 }}
          onChange={(event) => {
            onDraft({ ...draft, description: event.target.value });
          }}
        />
      </div>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.roles.matrixHint")}
      </p>
      {access.adminWithoutSystem ? (
        <Alert type="warning" showIcon message={t("admin.roles.adminNote")} />
      ) : null}
      {saveError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={roleErrorText(t, saveError)}
          action={
            isVersionConflict(saveError) ? (
              <Button size="small" onClick={onReload}>
                {t("admin.roles.errors.reload")}
              </Button>
            ) : undefined
          }
        />
      ) : null}
      {/* Новая роль: бар виден сразу («Создать роль» и «Отмена»), вопрос при уходе — когда есть название */}
      <ContextualSaveBar
        visible={isNew || changes.any}
        guard={isNew ? Boolean(draft.name) : changes.any}
        message={isNew ? t("admin.roles.new.unsaved") : undefined}
        saveLabel={isNew ? t("admin.roles.new.submit") : t("admin.roles.save")}
        discardLabel={isNew ? t("admin.roles.new.cancel") : t("admin.roles.reset")}
        loading={saving}
        disabled={nameMissing}
        guardParams={["role"]}
        onSave={() => {
          if (!saving && !nameMissing && (isNew || changes.any)) onSave();
        }}
        onDiscard={onReset}
      />
      {items.length > 0 ? <Consequence items={items} /> : null}
      {isNew ? null : (
        <div className="pf-panel-stack" style={{ gap: 8 }}>
          {inUse ? (
            <p id={deleteNoteId} className="pf-roles-note" style={{ margin: 0 }}>
              {t("admin.roles.deleteBlocked", { count: role.employees })}
            </p>
          ) : null}
          {confirmDelete && !inUse ? (
            <div
              className="pf-panel-stack"
              role="group"
              aria-label={t("admin.roles.deleteTitle")}
              style={{ gap: 8 }}
            >
              <Consequence items={[t("admin.roles.deleteResult")]} />
              <div style={{ display: "flex", gap: 8 }}>
                <Button danger loading={deleting} onClick={onDelete}>
                  {t("admin.roles.deleteConfirm")}
                </Button>
                <Button
                  onClick={() => {
                    setConfirmDelete(false);
                  }}
                >
                  {t("admin.roles.deleteCancel")}
                </Button>
              </div>
            </div>
          ) : (
            <Button
              danger
              block
              disabled={inUse}
              aria-describedby={inUse ? deleteNoteId : undefined}
              onClick={() => {
                setConfirmDelete(true);
              }}
            >
              {t("admin.roles.delete")}
            </Button>
          )}
          {deleteError ? (
            <Alert type="error" showIcon role="alert" message={roleErrorText(t, deleteError)} />
          ) : null}
        </div>
      )}
    </form>
  );
}
