import { Checkbox, Input, InputNumber } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { StockTraceUnitRef } from "../../../shared/api/generated/model";
import { companyToday } from "../../../shared/lib/dates";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { FormField } from "../../../shared/ui/FormParts";
import { type TraceDraft, type TrackedLine, parseSerials } from "./trace";

/**
 * Прослеживаемость (ADR-0021, L0-3): поля появляются, только если категория товара их требует. Серийный (S) — номера
 * списком, их число = принятому (можно вставить столбец из упаковочного листа); партия (L) — номер и срок годности;
 * документ соответствия — номер и срок действия. Для «только количество» ничего нового нет.
 * Эталоны: Odoo «Lot/Serial Numbers» при приёмке (вставка списком), Business Central «Item Tracking Lines».
 */
export function ReceiveTracking({
  line,
  name,
  quantity,
  draft,
  onChange,
}: {
  line: TrackedLine;
  name: string;
  quantity: number;
  draft: TraceDraft;
  onChange: (next: TraceDraft) => void;
}) {
  const { t } = useTranslation("stock");
  const ids = { serials: useId(), lot: useId(), expiry: useId(), doc: useId(), valid: useId() };
  const set = (patch: Partial<TraceDraft>) => {
    onChange({ ...draft, ...patch });
  };
  const count = parseSerials(draft.serials).length;
  return (
    <div className="pf-stock-trace" aria-label={t("trace.fieldsFor", { name })} role="group">
      {line.tracking === "serial" ? (
        <FormField
          id={ids.serials}
          label={t("trace.serials")}
          hint={t("trace.serialsCount", { count, total: quantity })}
        >
          <Input.TextArea
            id={ids.serials}
            rows={Math.min(Math.max(quantity, 2), 6)}
            value={draft.serials}
            placeholder={t("trace.serialsPlaceholder")}
            status={count > 0 && count !== quantity ? "warning" : undefined}
            aria-describedby={`${ids.serials}-hint`}
            onChange={(event) => {
              set({ serials: event.target.value });
            }}
          />
        </FormField>
      ) : null}
      {line.tracking === "lot" ? (
        <div className="pf-stock-trace-row">
          <FormField id={ids.lot} label={t("trace.lot")}>
            <Input
              id={ids.lot}
              maxLength={100}
              value={draft.lot}
              onChange={(event) => {
                set({ lot: event.target.value });
              }}
            />
          </FormField>
          <FormField id={ids.expiry} label={t("trace.expiry")}>
            <DateField
              id={ids.expiry}
              value={draft.expiry}
              onChange={(value) => {
                set({ expiry: value });
              }}
            />
          </FormField>
        </div>
      ) : null}
      {line.requires_doc ? (
        <div className="pf-stock-trace-row">
          <FormField id={ids.doc} label={t("trace.docNumber")}>
            <Input
              id={ids.doc}
              maxLength={100}
              value={draft.docNumber}
              onChange={(event) => {
                set({ docNumber: event.target.value });
              }}
            />
          </FormField>
          <FormField id={ids.valid} label={t("trace.docValidUntil")}>
            <DateField
              id={ids.valid}
              min={companyToday()}
              value={draft.docValidUntil}
              onChange={(value) => {
                set({ docValidUntil: value });
              }}
            />
          </FormField>
        </div>
      ) : null}
    </div>
  );
}

/** Выбор единиц на строке отгрузки: серийные — отметить, партии — сколько из каждой. */
export function ShipUnits({
  name,
  units,
  quantity,
  picked,
  onChange,
}: {
  name: string;
  units: readonly StockTraceUnitRef[];
  quantity: number;
  picked: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}) {
  const { t } = useTranslation("stock");
  const { date } = useFormat();
  const chosen = Object.values(picked).reduce((sum, n) => sum + n, 0);
  if (units.length === 0) {
    return <p className="pf-hint pf-stock-trace">{t("trace.noUnits")}</p>;
  }
  return (
    <fieldset className="pf-stock-trace pf-stock-units">
      <legend className="pf-hint">
        {t(units[0]?.kind === "lot" ? "trace.pickLots" : "trace.pickSerials", {
          name,
          count: chosen,
          total: quantity,
        })}
      </legend>
      <ul>
        {units.map((u) => (
          <li key={u.id}>
            {u.kind === "serial" ? (
              <Checkbox
                checked={(picked[u.id] ?? 0) > 0}
                onChange={(event) => {
                  const rest = Object.fromEntries(
                    Object.entries(picked).filter(([id]) => id !== u.id),
                  );
                  onChange(event.target.checked ? { ...rest, [u.id]: 1 } : rest);
                }}
              >
                <span className="pf-num">{u.number}</span>
              </Checkbox>
            ) : (
              <label className="pf-stock-lot">
                <span>
                  <span className="pf-num">{u.number}</span>
                  <span className="pf-hint">
                    {" "}
                    · {t("trace.lotAvailable", { count: u.available })}
                    {u.expiry_date
                      ? ` · ${t("trace.expiryShort", { date: date(u.expiry_date) })}`
                      : ""}
                  </span>
                </span>
                <InputNumber
                  min={0}
                  max={u.available}
                  precision={0}
                  value={picked[u.id] ?? 0}
                  aria-label={t("trace.lotQuantity", { number: u.number })}
                  onChange={(value) => {
                    onChange({ ...picked, [u.id]: value ?? 0 });
                  }}
                />
              </label>
            )}
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
