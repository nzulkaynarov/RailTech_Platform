import { Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectContractActionInAction,
  ProjectContractTemplate,
} from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";

type Send = (
  action: ProjectContractActionInAction,
  extra?: { text?: string; approve?: boolean },
) => void;

/**
 * Договор по утверждённому шаблону (ДОК-10, макет — доска 40): метка «По шаблону · без отступлений», название и редакция,
 * путь по фактам (собран → наша подпись → в Кабинете → подписан обеими), «Запросить отступление». Что можно сейчас, решает
 * ERP (`template.actions`); текст договора здесь не правится — закреплённый текст меняется только новой редакцией шаблона.
 */
export function ContractTemplateBlock({
  template,
  busy,
  pending,
  send,
}: {
  template: ProjectContractTemplate;
  busy: boolean;
  pending: string | null;
  send: Send;
}) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  const fieldId = useId();
  const [asking, setAsking] = useState(false);
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);
  const may = (action: ProjectContractTemplate["actions"][number]) =>
    template.actions.includes(action);

  const tag =
    template.deviation === "none" || template.deviation === "rejected" ? (
      <StatusTag tone="green">{t("contract.template.tag.none")}</StatusTag>
    ) : template.deviation === "requested" ? (
      <StatusTag tone="gold">{t("contract.template.tag.requested")}</StatusTag>
    ) : (
      <StatusTag tone="blue">{t("contract.template.tag.approved")}</StatusTag>
    );

  return (
    <section className="pf-ctpl" aria-label={t("contract.template.title")}>
      <p className="pf-ctpl-head">
        {tag}
        <span>
          {t("contract.template.line", { name: template.name, edition: template.edition })}
        </span>
      </p>
      <ol className="pf-ctpl-steps" aria-label={t("contract.template.path")}>
        {template.steps.map((step) => (
          <li key={step.key} className={`pf-ctpl-step pf-ctpl-${step.state}`}>
            <b>{t(`contract.template.steps.${step.key}`)}</b>
            <span>
              {t(`contract.template.state.${step.state}`)}
              {step.at ? ` · ${date(step.at)}` : ""}
            </span>
          </li>
        ))}
      </ol>
      {template.visas_required ? <p className="pf-hint">{t("contract.template.visas")}</p> : null}
      {template.deviation_text ? (
        <p className="pf-hint">
          {t(`contract.template.deviation.${template.deviation}`)}: {template.deviation_text}
        </p>
      ) : null}
      {template.send_blocker ? (
        <p className="pf-hint" role="status">
          {t(`contract.template.blocker.${template.send_blocker}`)}
        </p>
      ) : null}

      {may("sign_ours") ? (
        <Button
          type="primary"
          block
          loading={pending === "sign_ours"}
          disabled={busy}
          onClick={() => {
            send("sign_ours");
          }}
        >
          {t("contract.template.action.sign_ours")}
        </Button>
      ) : null}
      {may("decide_deviation") ? (
        <div className="pf-ctpl-row">
          <Button
            type="primary"
            loading={pending === "decide_deviation"}
            disabled={busy}
            onClick={() => {
              send("decide_deviation", { approve: true });
            }}
          >
            {t("contract.template.action.approve")}
          </Button>
          <Button
            disabled={busy}
            onClick={() => {
              send("decide_deviation", { approve: false });
            }}
          >
            {t("contract.template.action.reject")}
          </Button>
        </div>
      ) : null}
      {may("request_deviation") ? (
        asking ? (
          <form
            className="pf-fp-form"
            aria-label={t("contract.template.ask.title")}
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              setTouched(true);
              if (!text.trim() || busy) return;
              send("request_deviation", { text: text.trim() });
            }}
          >
            <label htmlFor={fieldId}>{t("contract.template.ask.label")}</label>
            <Input.TextArea
              id={fieldId}
              rows={3}
              maxLength={4000}
              value={text}
              status={touched && !text.trim() ? "error" : undefined}
              aria-invalid={touched && !text.trim()}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
            <p className="pf-hint">{t("contract.template.ask.hint")}</p>
            <div className="pf-ctpl-row">
              <Button
                type="primary"
                htmlType="submit"
                loading={pending === "request_deviation"}
                disabled={busy}
              >
                {t("contract.template.ask.submit")}
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  setAsking(false);
                  setTouched(false);
                }}
              >
                {t("contract.template.ask.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <Button
            block
            disabled={busy}
            onClick={() => {
              setAsking(true);
            }}
          >
            {t("contract.template.action.request_deviation")}
          </Button>
        )
      ) : null}
    </section>
  );
}
