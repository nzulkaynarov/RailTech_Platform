import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Skeleton,
} from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { SigningAuthorityDetail } from "../../../shared/api/generated/model";
import {
  getGetSigningAuthorityQueryKey,
  getDownloadSigningBasisFileUrl,
  useCreateSigningAuthority,
  useGetSigningAuthority,
  useListDictionaryItems,
  useListEdsStaff,
  useUpdateSigningAuthority,
  useUploadSigningBasisFile,
} from "../../../shared/api/generated/platform-bff";
import { companyToday } from "../../../shared/lib/dates";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { FilePicker } from "../../../shared/ui/FileField";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { localName } from "../../eds/dictionaries";
import { AuthorityStatus } from "./AuthorityStatus";
import { Summary } from "./Summary";
import { RevokeModal } from "./RevokeModal";
import {
  BASES,
  CURRENCIES,
  type FormValues,
  initialValues,
  powerDeadline,
  toNewBody,
  toPatchBody,
} from "./model";

export type DrawerTarget =
  { mode: "new"; preset?: Partial<FormValues> } | { mode: "edit"; id: string };

const FIELD_NAMES: Record<string, keyof FormValues> = {
  crm_user_id: "holderId",
  kinds: "kinds",
  basis: "basis",
  basis_number: "basisNumber",
  basis_date: "basisDate",
  valid_from: "validFrom",
  valid_to: "validTo",
  limit_amount: "limitAmount",
  limit_currency: "limitCurrency",
  vakolat_url: "vakolatUrl",
};

function failure(
  t: (key: string) => string,
  error: unknown,
): { text: string; fields: Partial<Record<keyof FormValues, string>> } {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (reason === "revoked") return { text: t("errors.revoked"), fields: {} };
    if (error.code === "PAYLOAD_TOO_LARGE" || error.code === "UNSUPPORTED_MEDIA_TYPE") {
      return { text: t(`errors.${error.code}`), fields: {} };
    }
    const raw = error.details["fields"];
    if (error.status === 422 && Array.isArray(raw)) {
      const fields: Partial<Record<keyof FormValues, string>> = {};
      for (const name of raw) {
        const key = typeof name === "string" ? FIELD_NAMES[name] : undefined;
        if (key) fields[key] = t(`errors.field.${String(name)}`);
      }
      return { text: t("errors.invalid"), fields };
    }
  }
  return { text: t("errors.DEFAULT"), fields: {} };
}

/**
 * Боковое окно полномочия (инвариант 18: карточки сущностей и история — Drawer): выдать или изменить, приложить скан основания,
 * отозвать (с причиной и блоком «Что произойдёт»), журнал. Отозванное только читается. Файл грузится сразу после сохранения:
 * сам BFF multipart не разбирает.
 */
export function AuthorityDrawer({
  target,
  kindName,
  onChanged,
  onTarget,
  onClose,
}: {
  target: DrawerTarget;
  kindName: (code: string) => string;
  onChanged: () => void;
  onTarget: (next: DrawerTarget) => void;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("signing");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const format = useFormat();
  const formId = useId();
  const [form] = Form.useForm<FormValues>();
  const id = target.mode === "edit" ? target.id : null;
  const detail = useGetSigningAuthority(id ?? "", { query: { enabled: id !== null } });
  const staff = useListEdsStaff({ query: { staleTime: 5 * 60_000 } });
  const kinds = useListDictionaryItems("signing-kinds", undefined, {
    query: { staleTime: 5 * 60_000 },
  });
  const create = useCreateSigningAuthority();
  const update = useUpdateSigningAuthority();
  const upload = useUploadSigningBasisFile();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const today = companyToday();
  const authority: SigningAuthorityDetail | null = detail.data ?? null;
  const readOnly = authority?.status === "revoked";
  const basis =
    (Form.useWatch("basis", form) as FormValues["basis"] | undefined) ?? "power_of_attorney";
  const basisDate = (Form.useWatch("basisDate", form) as string | undefined) ?? "";
  const validFrom = (Form.useWatch("validFrom", form) as string | undefined) ?? "";
  const numbered = basis !== "charter";
  const power = basis === "power_of_attorney";
  const deadline = power && basisDate ? powerDeadline(basisDate) : undefined;
  const busy = create.isPending || update.isPending || upload.isPending;

  const kindOptions = (kinds.data?.items ?? []).map((item) => ({
    value: item.code,
    label: localName(item.name, i18n.language),
  }));
  // Вид, который скрыли после выдачи, остаётся в списке выбранных, чтобы его видно и не потерять при сохранении.
  const known = new Set(kindOptions.map((o) => o.value));
  const extra = (authority?.kinds ?? [])
    .filter((code) => !known.has(code))
    .map((code) => ({ value: code, label: kindName(code) }));
  const people = (staff.data?.items ?? []).map((p) => ({
    value: p.id,
    label: p.position ? `${p.name} · ${p.position}` : p.name,
  }));
  const title =
    target.mode === "new"
      ? t("drawer.addTitle")
      : readOnly
        ? t("drawer.revokedTitle", { name: authority.holder.name })
        : t("drawer.editTitle", { name: authority?.holder.name ?? "" });

  const afterSave = async (saved: SigningAuthorityDetail) => {
    queryClient.setQueryData(getGetSigningAuthorityQueryKey(saved.id), saved);
    onChanged();
    if (file) {
      try {
        const withFile = await upload.mutateAsync({ id: saved.id, data: { file } });
        queryClient.setQueryData(getGetSigningAuthorityQueryKey(saved.id), withFile);
        onChanged();
      } catch (caught) {
        // Полномочие уже сохранено: остаёмся в нём, файл выбирают заново.
        onTarget({ mode: "edit", id: saved.id });
        setFile(null);
        setError(`${t("form.savedFileFailed")} ${failure(t, caught).text}`);
        return;
      }
    }
    void message.success(t("form.saved"));
    onClose();
  };

  const submit = async (values: FormValues) => {
    setError(null);
    try {
      const saved =
        target.mode === "new"
          ? await create.mutateAsync({ data: toNewBody(values) })
          : await update.mutateAsync({ id: target.id, data: toPatchBody(values) });
      await afterSave(saved);
    } catch (caught) {
      const { text, fields } = failure(t, caught);
      setError(text);
      form.setFields(
        (Object.keys(fields) as (keyof FormValues)[]).map((name) => ({
          name,
          errors: [fields[name] ?? text],
        })),
      );
    }
  };

  const required = [{ required: true, whitespace: true, message: t("form.required") }];
  // У выбора (`Select`) правило `required` ставит `aria-required` на контейнер без роли — axe это не принимает: проверка своя.
  const chosen = [
    {
      validator: (_: unknown, value: unknown) =>
        Array.isArray(value)
          ? value.length > 0
            ? Promise.resolve()
            : Promise.reject(new Error(t("form.required")))
          : value
            ? Promise.resolve()
            : Promise.reject(new Error(t("form.required"))),
    },
  ];
  const journal: HistoryItem[] = (authority?.journal ?? []).map((entry) => ({
    state: "done",
    title: (
      <>
        {t(`journal.${entry.action}`)}
        {entry.file_name ? `: ${entry.file_name}` : ""}
        {entry.comment ? `: ${entry.comment}` : ""}
      </>
    ),
    meta: (
      <>
        {format.date(entry.at, "datetime")} · {entry.by?.name ?? t("journal.system")}
        {entry.changes.map((change) => (
          <div key={change.field}>
            {t("journal.change", {
              field: t(`fields.${change.field}`, { defaultValue: change.field }),
              before: change.before ?? t("journal.empty"),
              after: change.after ?? t("journal.empty"),
            })}
          </div>
        ))}
      </>
    ),
  }));

  const ready = target.mode === "new" || authority !== null;
  const values = initialValues(today, authority, target.mode === "new" ? target.preset : undefined);

  return (
    <Drawer
      open
      title={title}
      width="min(520px, 100vw)"
      onClose={onClose}
      destroyOnHidden
      maskClosable={false}
      closeIcon={null}
      extra={
        <Button onClick={onClose} aria-label={t("drawer.close")}>
          {t("drawer.close")}
        </Button>
      }
      footer={
        readOnly ? null : (
          <div className="pf-sign-footer">
            {authority ? (
              <Button
                danger
                onClick={() => {
                  setRevoking(true);
                }}
              >
                {t("form.revoke")}
              </Button>
            ) : (
              <span />
            )}
            <span className="pf-sign-footer-main">
              <Button onClick={onClose}>{t("form.cancel")}</Button>
              <Button type="primary" htmlType="submit" form={formId} loading={busy}>
                {t("form.save")}
              </Button>
            </span>
          </div>
        )
      }
    >
      {target.mode === "edit" && detail.isError ? (
        <Alert type="error" showIcon role="alert" message={t("unavailable")} />
      ) : null}
      {!ready && !detail.isError ? <Skeleton active /> : null}
      {ready ? (
        <>
          {authority ? (
            <div className="pf-sign-state">
              <AuthorityStatus status={authority.status} />
              {authority.revoked ? (
                <span className="pf-hint">
                  {format.date(authority.revoked.at)} · {authority.revoked.by.name}:{" "}
                  {authority.revoked.reason}
                </span>
              ) : null}
            </div>
          ) : null}
          {error ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={error}
              style={{ marginBottom: 16 }}
            />
          ) : null}
          {authority && readOnly ? (
            <Summary authority={authority} kindName={kindName} />
          ) : (
            <Form<FormValues>
              id={formId}
              form={form}
              layout="vertical"
              initialValues={values}
              onFinish={(v) => {
                void submit(v);
              }}
            >
              {authority ? (
                <Form.Item label={t("form.holder")}>
                  <div>
                    <b>{authority.holder.name}</b>
                    {authority.holder_position ? (
                      <div className="pf-hint">{authority.holder_position}</div>
                    ) : null}
                  </div>
                </Form.Item>
              ) : (
                <Form.Item name="holderId" label={t("form.holder")} rules={chosen}>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    loading={staff.isPending}
                    placeholder={t("form.holderPlaceholder")}
                    options={people}
                  />
                </Form.Item>
              )}
              <Form.Item
                name="kinds"
                label={t("form.kinds")}
                extra={t("form.kindsHint")}
                rules={chosen}
              >
                <Select
                  mode="multiple"
                  optionFilterProp="label"
                  placeholder={t("form.kindsPlaceholder")}
                  options={[...kindOptions, ...extra]}
                />
              </Form.Item>
              <Form.Item name="basis" label={t("form.basis")} extra={t(`basis.hint.${basis}`)}>
                <Radio.Group
                  options={BASES.map((value) => ({ value, label: t(`basis.${value}`) }))}
                />
              </Form.Item>
              {numbered ? (
                <div className="pf-sign-pair">
                  <Form.Item name="basisNumber" label={t("form.basisNumber")} rules={required}>
                    <Input maxLength={64} autoComplete="off" />
                  </Form.Item>
                  <Form.Item name="basisDate" label={t("form.basisDate")} rules={required}>
                    <DateField />
                  </Form.Item>
                </div>
              ) : null}
              <div className="pf-sign-pair">
                <Form.Item name="validFrom" label={t("form.validFrom")} rules={required}>
                  <DateField />
                </Form.Item>
                <Form.Item
                  name="validTo"
                  label={t("form.validTo")}
                  rules={power ? required : []}
                  extra={
                    deadline ? t("form.validToPower", { date: format.date(deadline) }) : undefined
                  }
                >
                  <DateField
                    allowClear={!power}
                    {...(validFrom ? { min: validFrom } : {})}
                    {...(deadline ? { max: deadline } : {})}
                  />
                </Form.Item>
              </div>
              <Form.Item label={t("form.limit")} extra={t("form.limitHint")}>
                <div className="pf-sign-pair">
                  <Form.Item name="limitAmount" noStyle>
                    <InputNumber
                      min={0}
                      precision={2}
                      style={{ width: "100%" }}
                      aria-label={t("form.limitAmount")}
                      placeholder={t("form.limitAmount")}
                    />
                  </Form.Item>
                  <Form.Item name="limitCurrency" noStyle>
                    <Select
                      aria-label={t("form.limitCurrency")}
                      options={CURRENCIES.map((code) => ({
                        value: code,
                        label: format.currency(code),
                      }))}
                    />
                  </Form.Item>
                </div>
              </Form.Item>
              {power ? (
                <Form.Item
                  name="vakolatUrl"
                  label={t("form.vakolat")}
                  extra={t("form.vakolatHint")}
                >
                  <Input maxLength={500} autoComplete="off" inputMode="url" />
                </Form.Item>
              ) : null}
              <Form.Item name="note" label={t("form.note")}>
                <Input.TextArea maxLength={2000} autoSize={{ minRows: 2, maxRows: 5 }} />
              </Form.Item>
              <Form.Item label={t("form.file")} extra={t("form.fileHint")}>
                <div className="pf-sign-file">
                  {authority?.file ? (
                    <a
                      className="pf-focusable"
                      href={getDownloadSigningBasisFileUrl(authority.id)}
                      download
                    >
                      {t("form.fileDownload", { name: authority.file.name })}
                    </a>
                  ) : (
                    <span className="pf-hint">{t("form.fileNone")}</span>
                  )}
                  {authority?.file ? (
                    <span className="pf-hint">
                      {formatFileSize(authority.file.size)} ·{" "}
                      {t("form.fileVersion", { version: authority.file.version })}
                    </span>
                  ) : null}
                  {readOnly ? null : (
                    <FilePicker
                      accept="application/pdf,image/*"
                      inputLabel={t("form.file")}
                      buttonLabel={authority?.file ? t("form.fileReplace") : t("form.fileChoose")}
                      onPick={(files) => {
                        setFile(files[0] ?? null);
                      }}
                    />
                  )}
                  {file ? <span>{file.name}</span> : null}
                </div>
              </Form.Item>
            </Form>
          )}
          {journal.length > 0 ? (
            <section className="pf-sign-journal" aria-label={t("journal.title")}>
              <h3 className="pf-sign-h3">{t("journal.title")}</h3>
              <History items={journal} label={t("journal.title")} />
            </section>
          ) : null}
        </>
      ) : null}
      {authority && revoking ? (
        <RevokeModal
          authority={authority}
          onClose={() => {
            setRevoking(false);
          }}
          onRevoked={(saved) => {
            queryClient.setQueryData(getGetSigningAuthorityQueryKey(saved.id), saved);
            onChanged();
            setRevoking(false);
            void message.success(t("revoke.done"));
            onClose();
          }}
        />
      ) : null}
    </Drawer>
  );
}
