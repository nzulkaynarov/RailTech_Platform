import { Alert, App, Button, Checkbox, Form, Input, Modal, Select, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { CalcProposalLine, CalcSheet } from "../../../shared/api/generated/model";
import {
  useAddCalcLines,
  useGetCalcParse,
  useParseCalcText,
} from "../../../shared/api/generated/platform-bff";
import { calcRef, useApplySheet, useErrorText } from "./api";

const REASONS = new Set([
  "ai_disabled",
  "request_text_empty",
  "ai_extract_failed",
  "ai_budget_exceeded",
]);
type Kind = "goods" | "service";

/**
 * ИИ-разбор текста заявки в строки (SPEC-v3 §7.4): модель только ПРЕДЛАГАЕТ строки, ничего не пишется, пока сотрудник
 * не отметит нужные и не нажмёт «Добавить выбранные» (инвариант «код решает, модель предлагает»).
 */
export function ParseModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const [text, setText] = useState(sheet.request.text);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [kinds, setKinds] = useState<Record<number, Kind>>({});
  const defaultKind: Kind = sheet.rights.goods ? "goods" : "service";

  const start = useParseCalcText({
    mutation: {
      onSuccess: (job) => {
        setJobId(job.job_id);
        setPicked({});
        setKinds({});
      },
      onError: (error) => {
        const reason = error instanceof ApiError ? error.details["reason"] : undefined;
        setStartError(
          t("parse.failed", {
            reason: t(
              `parse.reasons.${typeof reason === "string" && REASONS.has(reason) ? reason : "other"}`,
            ),
          }),
        );
      },
    },
  });
  const result = useGetCalcParse(jobId ?? "", {
    query: {
      enabled: jobId !== null,
      refetchInterval: (query) => (query.state.data?.status === "pending" ? 2000 : false),
    },
  });
  const add = useAddCalcLines({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        onClose();
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });

  const data = result.data;
  const lines: readonly CalcProposalLine[] = data?.status === "done" ? data.lines : [];
  const isPicked = (index: number) => picked[index] ?? true;
  const kindOf = (index: number): Kind => kinds[index] ?? defaultKind;
  const chosen = lines
    .map((line, index) => ({ line, index }))
    .filter(({ index }) => isPicked(index));
  const failedReason = data?.status === "failed" ? (data.reason ?? "other") : null;

  return (
    <Modal
      open
      width={720}
      title={t("parse.title")}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="close" onClick={onClose}>
          {t("parse.cancel")}
        </Button>,
        lines.length ? (
          <Button
            key="add"
            type="primary"
            disabled={chosen.length === 0}
            loading={add.isPending}
            onClick={() => {
              add.mutate({
                number: calcRef(sheet.number),
                data: {
                  lines: chosen.map(({ line, index }) => ({
                    name: line.name,
                    quantity: line.quantity,
                    kind: kindOf(index),
                    ...(line.unit ? { unit: line.unit } : {}),
                    ...(line.article ? { article: line.article } : {}),
                    ...(line.note ? { note: line.note } : {}),
                  })),
                },
              });
            }}
          >
            {t("parse.addSelected", { count: chosen.length })}
          </Button>
        ) : null,
      ]}
    >
      <p>{t("parse.intro")}</p>
      <Form
        layout="vertical"
        onFinish={() => {
          setStartError(null);
          start.mutate({ number: calcRef(sheet.number), data: { text } });
        }}
      >
        <Form.Item label={t("parse.text")} extra={t("parse.textHint")} htmlFor="pf-calc-parse-text">
          <Input.TextArea
            id="pf-calc-parse-text"
            value={text}
            autoSize={{ minRows: 3, maxRows: 8 }}
            maxLength={20000}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </Form.Item>
        <Button htmlType="submit" loading={start.isPending} disabled={!text.trim()}>
          {t("parse.start")}
        </Button>
      </Form>
      {startError ? (
        <Alert type="error" showIcon message={startError} className="pf-calc-gap" />
      ) : null}
      {jobId !== null && (data === undefined || data.status === "pending") ? (
        <div className="pf-calc-gap" role="status">
          <Spin size="small" /> {t("parse.pending")}
        </div>
      ) : null}
      {failedReason ? (
        <Alert
          type="error"
          showIcon
          className="pf-calc-gap"
          message={t("parse.failed", {
            reason: t(`parse.reasons.${REASONS.has(failedReason) ? failedReason : "other"}`),
          })}
        />
      ) : null}
      {data?.status === "done" && lines.length === 0 ? (
        <p className="pf-hint pf-calc-gap">{t("parse.nothing")}</p>
      ) : null}
      {lines.length ? (
        <fieldset className="pf-calc-proposal pf-calc-gap">
          <legend>{t("parse.proposal")}</legend>
          {data?.truncated ? (
            <p className="pf-hint">{t("parse.truncated", { count: data.recognized ?? 0 })}</p>
          ) : null}
          <ul>
            {lines.map((line, index) => (
              <li key={`${line.name}-${String(index)}`}>
                <Checkbox
                  checked={isPicked(index)}
                  onChange={(event) => {
                    setPicked((prev) => ({ ...prev, [index]: event.target.checked }));
                  }}
                >
                  {line.name} · {line.quantity} {line.unit}
                  {line.article ? <span className="pf-hint"> · {line.article}</span> : null}
                </Checkbox>
                <Select<Kind>
                  size="small"
                  value={kindOf(index)}
                  aria-label={`${t("add.kind")}: ${line.name}`}
                  onChange={(value) => {
                    setKinds((prev) => ({ ...prev, [index]: value }));
                  }}
                  options={[
                    { value: "goods", label: t("add.kindGoods"), disabled: !sheet.rights.goods },
                    {
                      value: "service",
                      label: t("add.kindService"),
                      disabled: !sheet.rights.services,
                    },
                  ]}
                />
              </li>
            ))}
          </ul>
        </fieldset>
      ) : null}
    </Modal>
  );
}
