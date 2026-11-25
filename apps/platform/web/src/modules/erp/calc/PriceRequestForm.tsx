import { App, Button, Checkbox, Input } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcSheet, PriceRequestPreview } from "../../../shared/api/generated/model";
import {
  useCreateCalcPriceRequest,
  useListCounterpartyPickerPeople,
  usePreviewCalcPriceRequest,
} from "../../../shared/api/generated/platform-bff";
import { DisabledReason } from "../../../shared/ui/DisabledReason";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { CompanyPicker, useApplyCompanyRole, type PickedCompany } from "../../../shared/ui/pickers";
import { clean, useErrorText, useRefreshStock } from "../stock/api";
import { calcRef } from "./api";
import { useFormat } from "../../../shared/lib/useFormat";

/**
 * «Запросить цену у поставщика» (SPEC-v3 §7.4): письмо поставщику по выбранным строкам-товарам расчёта (почта ERP) и запись
 * в журнале — кто, когда, кому, по каким строкам. Цену из ответа поставщик вносит вручную в строку расчёта («Закупка»).
 * Короткая форма о выбранном расчёте — в боковом окне (platform-frontend.md §4.1a), кнопки в конце.
 */
export function PriceRequestForm({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { qty } = useFormat();
  const { t } = useTranslation("stock");
  const titleId = useId();
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const applyRole = useApplyCompanyRole();
  const noteId = useId();
  const emailId = useId();
  const previewId = useId();
  const goods = sheet.lines.filter((line) => line.zone === "goods");
  const needy = goods.filter((line) => line.kind === "goods_to_order");
  const [lines, setLines] = useState<string[]>((needy.length ? needy : goods).map((l) => l.id));
  const [supplier, setSupplier] = useState<PickedCompany | null>(null);
  const [note, setNote] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  // «Как назвать партнёру»: правки сотрудника по строкам; слова клиента партнёру сами не уходят (аудит 2026-11-25, В-2)
  const [names, setNames] = useState<Record<string, string>>({});
  const [view, setView] = useState<PriceRequestPreview | null>(null);
  // Адрес: почта компании, иначе почта человека из её карточки (как отправляет ERP); нет ни той, ни другой — вводят
  const people = useListCounterpartyPickerPeople(supplier?.id ?? "", {
    query: { enabled: supplier !== null && !supplier.email, staleTime: 30_000, retry: false },
  });
  const contactEmail = (people.data?.items ?? []).find((person) => person.email)?.email ?? null;
  const needsEmail =
    supplier !== null && !supplier.email && !people.isFetching && contactEmail === null;
  const reasonId = useId();
  const reason = !supplier
    ? t("priceRequest.reason.supplier")
    : lines.length === 0
      ? t("priceRequest.reason.lines")
      : needsEmail && clean(email) === undefined
        ? t("priceRequest.reason.email")
        : null;
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
  const preview = usePreviewCalcPriceRequest({
    mutation: {
      onSuccess: (data) => {
        setView(data);
      },
      onError: (e) => {
        setError(errorText(e));
      },
    },
  });
  const edited = Object.entries(names)
    .map(([line_id, name]) => ({ line_id, name: name.trim() }))
    .filter((row) => row.name !== "" && lines.includes(row.line_id));
  const previewKey = JSON.stringify([supplier?.id, lines, clean(note), clean(email), edited]);
  useEffect(() => {
    if (!supplier || lines.length === 0) return;
    preview.mutate({
      number: calcRef(sheet.number),
      data: {
        supplier_id: supplier.id,
        line_ids: lines,
        ...(clean(note) ? { note: clean(note) } : {}),
        ...(edited.length ? { partner_names: edited } : {}),
      },
    });
    // предпросмотр пересчитывается при смене партнёра, строк, комментария и названий
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);
  const shown =
    supplier && view && view.lines.length === lines.length && lines.length > 0 ? view : null;
  const nameOf = (id: string, fromServer: string | null) =>
    (names[id] ?? "").trim() || (fromServer ?? "");
  const unnamed = shown ? shown.lines.some((line) => nameOf(line.line_id, line.name) === "") : true;
  return (
    <section className="pf-calc-panel-form" aria-labelledby={titleId}>
      <h3 className="pf-fp-title" id={titleId}>
        {t("priceRequest.title", { number: sheet.number })}
      </h3>
      <div className="pf-calc-stack">
        <FormField id="pf-pr-supplier" label={t("priceRequest.supplier")}>
          <CompanyPicker
            id="pf-pr-supplier"
            role="supplier"
            assignRole
            value={supplier}
            onChange={(company) => {
              setSupplier(company);
              setEmail("");
            }}
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
                label: `${l.name} · ${qty(l.quantity)} ${l.unit}`.trim(),
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
        {supplier && shown ? (
          <section className="pf-pr-preview" aria-label={t("priceRequest.preview.title")}>
            <h4 className="pf-fp-subtitle">{t("priceRequest.preview.title")}</h4>
            <p className="pf-hint">
              {t("priceRequest.preview.subject")}: {shown.subject}
            </p>
            {shown.to_email ? (
              <p className="pf-hint">
                {t("priceRequest.preview.to")}: {shown.to_email}
              </p>
            ) : null}
            {shown.lines.map((line, index) => {
              const id = `${previewId}-${line.line_id}`;
              const missing =
                line.source === "missing" && (names[line.line_id] ?? "").trim() === "";
              const clientWords =
                line.client_name && line.client_name !== nameOf(line.line_id, line.name)
                  ? t("priceRequest.preview.clientWords", { name: line.client_name })
                  : undefined;
              const hint =
                [clientWords, missing ? t("priceRequest.preview.missing") : undefined]
                  .filter(Boolean)
                  .join(" ") || undefined;
              return (
                <FormField
                  key={line.line_id}
                  id={id}
                  label={t("priceRequest.preview.partnerName", { n: index + 1 })}
                  hint={hint}
                >
                  <Input
                    id={id}
                    value={names[line.line_id] ?? line.name ?? ""}
                    maxLength={500}
                    status={missing ? "error" : undefined}
                    aria-invalid={missing || undefined}
                    aria-describedby={hint ? `${id}-hint` : undefined}
                    onChange={(event) => {
                      setNames({ ...names, [line.line_id]: event.target.value });
                    }}
                  />
                </FormField>
              );
            })}
            {shown.note ? (
              <p className="pf-hint">
                {t("priceRequest.preview.note")}: {shown.note}
              </p>
            ) : null}
          </section>
        ) : null}
        <ErrorNote message={error} />
        <DisabledReason id={reasonId}>{reason}</DisabledReason>
        <div className="pf-calc-panel-actions">
          <Button
            type="primary"
            loading={create.isPending}
            aria-describedby={reason ? reasonId : undefined}
            disabled={
              !supplier ||
              lines.length === 0 ||
              unnamed ||
              people.isFetching ||
              (needsEmail && clean(email) === undefined)
            }
            onClick={() => {
              if (!supplier) return;
              const to = clean(email);
              const text = clean(note);
              setError(null);
              // роль поставщика — в момент отправки: закрытая форма не оставляет роль без запроса
              void applyRole(supplier).then((refused) => {
                if (refused) {
                  setError(refused);
                  return;
                }
                create.mutate({
                  number: calcRef(sheet.number),
                  data: {
                    supplier_id: supplier.id,
                    line_ids: lines,
                    ...(text ? { note: text } : {}),
                    ...(needsEmail && to ? { to_email: to } : {}),
                    ...(edited.length ? { partner_names: edited } : {}),
                  },
                });
              });
            }}
          >
            {t("priceRequest.submit")}
          </Button>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
        </div>
      </div>
    </section>
  );
}
