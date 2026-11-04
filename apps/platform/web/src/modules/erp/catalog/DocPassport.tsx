import { Checkbox, Input, Select } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { CatalogDocumentKind } from "../../../shared/api/generated/model";
import { DateField } from "../../../shared/ui/DateField";
import { FormField } from "../../../shared/ui/FormParts";
import type { DocPassport } from "./passportState";

/** Поля паспорта в форме загрузки и правки; одна разметка на «Документы» карточки и «Техдокументацию». */
export function DocPassportFields({
  value,
  onChange,
  kinds,
  invalid = [],
  currentKind,
}: {
  value: DocPassport;
  onChange: (next: DocPassport) => void;
  kinds: readonly CatalogDocumentKind[];
  invalid?: readonly string[];
  /** Вид правимого документа: если его выключили, он виден названием, но выбрать его заново нельзя. */
  currentKind?: { code: string; name: string };
}) {
  const { t } = useTranslation("catalog");
  const ids = { kind: useId(), number: useId(), by: useId(), from: useId(), until: useId() };
  const visibleId = useId();
  const patch = (part: Partial<DocPassport>) => {
    onChange({ ...value, ...part });
  };
  const selected = kinds.find((k) => k.code === value.kind);
  return (
    <>
      <div className="pf-cat-form-row">
        <FormField id={ids.kind} label={t("docs.form.kind")}>
          <Select
            id={ids.kind}
            value={value.kind}
            status={invalid.includes("kind") ? "error" : undefined}
            onChange={(code: string) => {
              const kind = kinds.find((k) => k.code === code);
              patch({
                kind: code,
                ...(value.visibleTouched || !kind
                  ? {}
                  : { clientVisible: kind.client_visible_default }),
              });
            }}
            options={[
              ...kinds.map((k) => ({ value: k.code, label: k.name })),
              ...(currentKind && !kinds.some((k) => k.code === currentKind.code)
                ? [{ value: currentKind.code, label: currentKind.name, disabled: true }]
                : []),
            ]}
          />
        </FormField>
        <FormField id={ids.number} label={t("docs.form.number")}>
          <Input
            id={ids.number}
            value={value.number}
            maxLength={100}
            onChange={(event) => {
              patch({ number: event.target.value });
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.by} label={t("docs.form.issuedBy")}>
        <Input
          id={ids.by}
          value={value.issuedBy}
          maxLength={255}
          onChange={(event) => {
            patch({ issuedBy: event.target.value });
          }}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField id={ids.from} label={t("docs.form.issuedAt")}>
          <DateField
            id={ids.from}
            value={value.issuedAt}
            status={invalid.includes("issued_at") ? "error" : undefined}
            onChange={(day) => {
              patch({ issuedAt: day });
            }}
          />
        </FormField>
        <FormField
          id={ids.until}
          label={t("docs.form.validUntil")}
          hint={selected?.has_validity ? t("docs.form.validUntilHint") : undefined}
        >
          <DateField
            id={ids.until}
            value={value.validUntil}
            status={invalid.includes("valid_until") ? "error" : undefined}
            onChange={(day) => {
              patch({ validUntil: day });
            }}
          />
        </FormField>
      </div>
      <div className="pf-fp-field">
        <Checkbox
          id={visibleId}
          checked={value.clientVisible}
          aria-describedby={`${visibleId}-hint`}
          onChange={(event) => {
            patch({ clientVisible: event.target.checked, visibleTouched: true });
          }}
        >
          {t("docs.form.clientVisible")}
        </Checkbox>
        <span className="pf-hint" id={`${visibleId}-hint`}>
          {t("docs.form.clientVisibleHint")}
        </span>
      </div>
    </>
  );
}
