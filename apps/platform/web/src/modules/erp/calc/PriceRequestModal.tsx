import { App, Button, Checkbox, Input, Modal, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import {
  useCreateCalcPriceRequest,
  useListStockSuppliers,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { clean, useErrorText, useRefreshStock } from "../stock/api";
import { calcRef } from "./api";

/**
 * «Запросить цену у поставщика» (SPEC-v3 §7.4): письмо поставщику по выбранным строкам-товарам расчёта (почта ERP) и запись
 * в журнале — кто, когда, кому, по каким строкам. Цену из ответа поставщик вносит вручную в строку расчёта («Закупка»).
 */
export function PriceRequestModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const noteId = useId();
  const emailId = useId();
  const goods = sheet.lines.filter((line) => line.zone === "goods");
  const needy = goods.filter((line) => line.kind === "goods_to_order");
  const [lines, setLines] = useState<string[]>((needy.length ? needy : goods).map((l) => l.id));
  const [supplier, setSupplier] = useState<string | undefined>();
  const [note, setNote] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const suppliers = useListStockSuppliers();
  const chosen = (suppliers.data?.items ?? []).find((s) => s.id === supplier);
  const needsEmail = chosen !== undefined && !chosen.email;
  const create = useCreateCalcPriceRequest({
    mutation: {
      onSuccess: (request) => {
        refresh();
        if (request.status === "failed") {
          void message.warning(t("priceRequest.failed", { name: request.supplier.name }));
        } else {
          void message.success(t("priceRequest.sent", { email: request.to_email }));
        }
        onClose();
      },
      onError: (e) => {
        setError(errorText(e));
      },
    },
  });
  return (
    <Modal
      open
      width={640}
      title={t("priceRequest.title", { number: sheet.number })}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={create.isPending}
          disabled={!supplier || lines.length === 0 || (needsEmail && clean(email) === undefined)}
          onClick={() => {
            if (!supplier) return;
            const to = clean(email);
            const text = clean(note);
            setError(null);
            create.mutate({
              number: calcRef(sheet.number),
              data: {
                supplier_id: supplier,
                line_ids: lines,
                ...(text ? { note: text } : {}),
                ...(needsEmail && to ? { to_email: to } : {}),
              },
            });
          }}
        >
          {t("priceRequest.submit")}
        </Button>,
      ]}
    >
      <div className="pf-calc-stack">
        <FormField id="pf-pr-supplier" label={t("priceRequest.supplier")}>
          <Select<string>
            id="pf-pr-supplier"
            showSearch
            optionFilterProp="label"
            loading={suppliers.isPending}
            value={supplier}
            placeholder={t("priceRequest.supplierPlaceholder")}
            onChange={setSupplier}
            options={(suppliers.data?.items ?? []).map((s) => ({
              value: s.id,
              label: s.email ? `${s.name} · ${s.email}` : `${s.name} · ${t("create.noEmail")}`,
            }))}
          />
        </FormField>
        {needsEmail ? (
          <FormField
            id={emailId}
            label={t("priceRequest.email")}
            hint={t("priceRequest.emailHint")}
          >
            <Input
              id={emailId}
              type="email"
              value={email}
              maxLength={254}
              aria-describedby={`${emailId}-hint`}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </FormField>
        ) : null}
        <fieldset className="pf-calc-proposal">
          <legend>{t("priceRequest.lines")}</legend>
          {goods.length === 0 ? (
            <p className="pf-hint">{t("priceRequest.noGoods")}</p>
          ) : (
            <Checkbox.Group
              value={lines}
              onChange={(values) => {
                setLines(values.map(String));
              }}
              className="pf-stock-checks"
              options={goods.map((l) => ({
                value: l.id,
                label: `${l.name} · ${String(l.quantity)} ${l.unit}`.trim(),
              }))}
            />
          )}
        </fieldset>
        <FormField id={noteId} label={t("priceRequest.note")}>
          <Input.TextArea
            id={noteId}
            value={note}
            maxLength={1000}
            rows={2}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </FormField>
        <ErrorNote message={error} />
        <Consequence items={t("priceRequest.consequence", { returnObjects: true }) as string[]} />
      </div>
    </Modal>
  );
}
