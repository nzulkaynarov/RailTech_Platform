import { Alert, Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { LetterDuplicate } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import type { ForceState } from "./duplicates";

/**
 * Блок дублей формы (EDS-DUP; 1С:Документооборот — «Найдены похожие документы»): то же письмо — предупреждение со ссылкой и
 * «Это другое письмо — зарегистрировать» с причиной; похожие — список ссылок, регистрации не мешают.
 */
export function DuplicateNotice({
  items,
  force,
  onForce,
  reasonError,
}: {
  items: readonly LetterDuplicate[];
  force: ForceState;
  onForce: (next: ForceState) => void;
  reasonError: boolean;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const exact = items.find((item) => item.match === "exact");
  const similar = items.filter((item) => item !== exact);
  if (!exact && similar.length === 0) return null;
  return (
    <div className="pf-reg-dups" id="reg-duplicates">
      {exact ? (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message={t("register.duplicate.exactTitle")}
          description={
            <div className="pf-reg-dup">
              <p className="pf-reg-dup-line">
                <Link className="pf-focusable" to={exact.path}>
                  {exact.number}
                </Link>{" "}
                <StatusTag kind="incoming" status={exact.status} />{" "}
                <span className="pf-hint">
                  {t("register.duplicate.registered", {
                    date: date(exact.registered_at ?? exact.received_at),
                    subject: exact.subject,
                  })}
                </span>
              </p>
              {force.on ? (
                <div className="pf-fp-field">
                  <label htmlFor="reg-force-reason">{t("register.duplicate.reason")}</label>
                  <Input.TextArea
                    id="reg-force-reason"
                    value={force.reason}
                    maxLength={1000}
                    autoSize={{ minRows: 2, maxRows: 4 }}
                    status={reasonError ? "error" : undefined}
                    aria-invalid={reasonError || undefined}
                    aria-describedby={reasonError ? "reg-force-reason-error" : undefined}
                    onChange={(event) => {
                      onForce({ on: true, reason: event.target.value });
                    }}
                  />
                  {reasonError ? (
                    <span className="pf-field-error" id="reg-force-reason-error" role="alert">
                      {t("register.duplicate.reasonRequired")}
                    </span>
                  ) : null}
                </div>
              ) : null}
              <div className="pf-fp-row">
                <LinkButton to={exact.path}>{t("register.duplicate.open")}</LinkButton>
                {force.on ? (
                  <Button
                    onClick={() => {
                      onForce({ on: false, reason: "" });
                    }}
                  >
                    {t("register.duplicate.keep")}
                  </Button>
                ) : (
                  <Button
                    onClick={() => {
                      onForce({ on: true, reason: force.reason });
                    }}
                  >
                    {t("register.duplicate.other")}
                  </Button>
                )}
              </div>
            </div>
          }
        />
      ) : null}
      {similar.length > 0 ? (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t("register.duplicate.similarTitle")}
          description={
            <ul className="pf-reg-duplicates">
              {similar.map((item) => (
                <li key={item.id}>
                  <Link className="pf-focusable" to={item.path}>
                    {item.number}
                  </Link>{" "}
                  {t("register.duplicate.item", {
                    subject: item.subject,
                    date: date(item.received_at),
                  })}
                  {item.match ? (
                    <span className="pf-hint">
                      {" "}
                      · {t(`register.duplicate.match.${item.match}`)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          }
        />
      ) : null}
    </div>
  );
}
