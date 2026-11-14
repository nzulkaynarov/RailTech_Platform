import { AutoComplete } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { useSearchMxik } from "../../../shared/api/generated/platform-bff";
import { useDebounced } from "./useDebounced";

/** Выбранный МХИК (ИКПУ): из классификатора — с названием, единицей и упаковкой; вручную — только код. */
export interface MxikValue {
  code: string;
  name: string;
  unit: string;
  package: string;
}

export const MXIK_CODE = /^(\d{17})?$/;

/**
 * Поле МХИК (план 1.8): слово или код ищется в классификаторе Налогового комитета, выбор подставляет код и название;
 * классификатор не отвечает — код вводится вручную (17 цифр).
 */
export function MxikField({
  id,
  value,
  invalid,
  onChange,
}: {
  id: string;
  value: MxikValue;
  invalid: boolean;
  onChange: (value: MxikValue) => void;
}) {
  const { t } = useTranslation("catalog");
  const [text, setText] = useState(value.code);
  const q = useDebounced(text.trim());
  const search = useSearchMxik(
    { q },
    { query: { enabled: q.length >= 2 && !/^\d{17}$/.test(q), retry: false } },
  );
  const down =
    search.error instanceof ApiError && search.error.details["reason"] === "mxik_unavailable";
  const items = search.data?.items ?? [];

  return (
    <>
      <AutoComplete
        id={id}
        value={text}
        status={invalid ? "error" : undefined}
        options={items.map((item) => ({
          value: item.code,
          label: `${item.code} · ${item.name}${item.unit ? ` · ${item.unit}` : ""}`,
        }))}
        onSearch={setText}
        onChange={(next: string) => {
          setText(next);
          const code = next.trim();
          onChange({ code, name: "", unit: "", package: "" });
        }}
        onSelect={(code: string) => {
          const hit = items.find((item) => item.code === code);
          setText(code);
          onChange(
            hit
              ? { code, name: hit.name, unit: hit.unit, package: hit.package }
              : { code, name: "", unit: "", package: "" },
          );
        }}
      />
      {value.name ? <span className="pf-hint">{value.name}</span> : null}
      {down ? <span className="pf-hint">{t("items.form.mxikDown")}</span> : null}
    </>
  );
}
