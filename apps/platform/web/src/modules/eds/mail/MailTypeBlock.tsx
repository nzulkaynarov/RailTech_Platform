import { Alert, App, Button, Segmented, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import {
  createMailSenderRule,
  setInboundMailType,
  useListDictionaryItems,
} from "../../../shared/api/generated/platform-bff";
import { localName } from "../dictionaries";
import { MailTypeTag } from "./MailTypeTag";
import { useRefreshMail } from "./mailModel";

const NONE = "";

function reasonOf(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error);
}

/**
 * Тип письма в карточке (MAIL-TYPES): тег, кто его выбрал, смена одним щелчком (запись в журнал письма) и — для
 * администратора — «Всегда считать письма от этого домена этим типом» (правило отправителя, как фильтр Gmail и правило
 * Front; применяется до помощника и побеждает его). Выбор человека помощник и правило не перебивают.
 */
export function MailTypeBlock({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t, i18n } = useTranslation("letters");
  const { message } = App.useApp();
  const { me } = useAuth();
  const refresh = useRefreshMail();
  const types = useListDictionaryItems("mail-types", undefined, { query: { staleTime: 60_000 } });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = mail.type;
  const options = [
    { value: NONE, label: t("mail.type.none") },
    ...(types.data?.items ?? []).map((item) => ({
      value: item.code,
      label: localName(item.name, i18n.language),
    })),
    // Отключённый тип у письма остаётся в списке, чтобы выбор не «потерялся».
    ...(current && !(types.data?.items ?? []).some((item) => item.code === current.code)
      ? [{ value: current.code, label: localName(current.name, i18n.language), disabled: true }]
      : []),
  ];
  const change = async (code: string) => {
    setPending(true);
    setError(null);
    try {
      await setInboundMailType(mail.id, { type_code: code === NONE ? null : code });
      void message.success(t(code === NONE ? "mail.type.removed" : "mail.type.changed"));
      await refresh();
      reload();
    } catch (failure) {
      setError(t("mail.actions.failed", { reason: reasonOf(failure) }));
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-labelledby="mail-type-title" className="pf-mail-actions">
      <h3 id="mail-type-title" className="pf-res-subhead">
        {t("mail.type.title")}
      </h3>
      {current ? (
        <p className="pf-mail-what">
          <MailTypeTag type={current} />{" "}
          <span className="pf-hint">{t(`mail.type.source.${current.source}`)}</span>
        </p>
      ) : (
        <p className="pf-hint pf-mail-what">{t("mail.type.empty")}</p>
      )}
      <label htmlFor="mail-type-select">{t("mail.type.change")}</label>
      <Select
        id="mail-type-select"
        value={current?.code ?? NONE}
        options={options}
        loading={types.isPending || pending}
        disabled={pending || types.isError}
        onChange={(code) => void change(code)}
      />
      {canEdit(me, "admin") && current && mail.from_email.includes("@") ? (
        <SenderRule mail={mail} typeName={localName(current.name, i18n.language)} />
      ) : null}
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </section>
  );
}

/** «Всегда считать письма от … таким типом»: домен или только этот адрес; правило создаёт администратор. */
function SenderRule({ mail, typeName }: { mail: InboundMail; typeName: string }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [scope, setScope] = useState<"domain" | "address">("domain");
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<{ type: "error" | "success"; text: string } | null>(null);
  const email = mail.from_email.toLowerCase();
  const domain = email.split("@")[1] ?? "";
  const pattern = scope === "domain" ? domain : email;
  if (!mail.type || mail.type.source === "rule") return null;
  const type = mail.type;
  const create = async () => {
    setPending(true);
    setNote(null);
    try {
      const rule = await createMailSenderRule({
        pattern,
        type_code: type.code,
        mail_id: mail.id,
      });
      const text = t("mail.type.rule.created", { count: rule.applied });
      void message.success(text);
      setNote({ type: "success", text });
      await refresh();
    } catch (failure) {
      const exists =
        failure instanceof ApiError && failure.details["reason"] === "mail_rule_exists";
      setNote({
        type: "error",
        text: exists
          ? t("mail.type.rule.exists")
          : t("mail.actions.failed", { reason: reasonOf(failure) }),
      });
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="pf-mail-actions">
      <Segmented<"domain" | "address">
        block
        aria-label={t("mail.type.rule.scope")}
        value={scope}
        onChange={setScope}
        options={[
          { value: "domain", label: t("mail.type.rule.domain") },
          { value: "address", label: t("mail.type.rule.address") },
        ]}
      />
      <div>
        <Button className="pf-mail-rule-btn" loading={pending} onClick={() => void create()}>
          {t("mail.type.rule.button", { pattern, type: typeName })}
        </Button>
      </div>
      <p className="pf-hint pf-mail-what">{t("mail.type.rule.what")}</p>
      {note ? <Alert type={note.type} showIcon role="status" message={note.text} /> : null}
    </div>
  );
}
