import { Alert, App, Button, Input, Modal, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { LetterAssistSuggestion } from "../../../shared/api/generated/model";
import { assistLetterText } from "../../../shared/api/generated/platform-bff";
import {
  type BodyLang,
  type BodyNode,
  bodyText,
  isBlank,
  toBody,
} from "../../../shared/ui/BodyEditor/bodyModel";

function failureText(failure: unknown, fallback: string): string {
  return failure instanceof ApiError ? failure.message || fallback : fallback;
}

/**
 * Помощник письма (план 1.4): «Подготовить текст» по поручению и «Перевести на английский» с обратным переводом —
 * модель только предлагает, тело заменяет сотрудник кнопкой «Вставить».
 */
export function LetterAssist({
  value,
  lang,
  subject,
  recipient,
  onReplace,
}: {
  value: BodyNode;
  lang: BodyLang;
  subject: string;
  recipient: string;
  onReplace: (doc: BodyNode, lang: BodyLang) => void;
}) {
  const { t } = useTranslation("documents");
  const { message } = App.useApp();
  const [open, setOpen] = useState<"draft" | "translate" | null>(null);
  const [brief, setBrief] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LetterAssistSuggestion | null>(null);
  const blank = isBlank(value);

  const close = () => {
    setOpen(null);
    setError(null);
    setResult(null);
  };
  const run = async (action: "draft" | "translate") => {
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const answer = await assistLetterText({
        action,
        lang: action === "translate" ? "en" : lang,
        ...(action === "draft" ? { brief: brief.trim() } : {}),
        ...(subject.trim() ? { subject: subject.trim() } : {}),
        ...(recipient.trim() ? { recipient: recipient.trim() } : {}),
        ...(blank ? {} : { body: toBody(value, lang) }),
      });
      if (action === "draft") {
        onReplace(answer.body.doc as unknown as BodyNode, lang);
        void message.success(t("form.assist.inserted"));
        close();
        return;
      }
      setResult(answer);
    } catch (failure) {
      setError(failureText(failure, t("form.assist.failed")));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="pf-new-assist">
      <Button
        onClick={() => {
          setOpen("draft");
        }}
      >
        {t("form.assist.draft")}
      </Button>
      {lang !== "en" ? (
        <Button
          disabled={blank}
          onClick={() => {
            setOpen("translate");
            void run("translate");
          }}
        >
          {t("form.assist.translate")}
        </Button>
      ) : null}

      {open === "draft" ? (
        <Modal
          open
          width={560}
          title={t("form.assist.draftTitle")}
          onCancel={close}
          destroyOnHidden
          footer={[
            <Button key="cancel" onClick={close}>
              {t("form.assist.cancel")}
            </Button>,
            <Button
              key="run"
              type="primary"
              loading={pending}
              disabled={!brief.trim()}
              onClick={() => void run("draft")}
            >
              {t("form.assist.draftRun")}
            </Button>,
          ]}
        >
          <label htmlFor="letter-assist-brief">{t("form.assist.brief")}</label>
          <Input.TextArea
            id="letter-assist-brief"
            rows={4}
            maxLength={4000}
            value={brief}
            placeholder={t("form.assist.briefHint")}
            onChange={(event) => {
              setBrief(event.target.value);
            }}
          />
          {!blank ? <p className="pf-hint">{t("form.assist.replaces")}</p> : null}
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
        </Modal>
      ) : null}

      {open === "translate" ? (
        <Modal
          open
          width={880}
          title={t("form.assist.translateTitle")}
          onCancel={close}
          destroyOnHidden
          footer={[
            <Button key="cancel" onClick={close}>
              {t("form.assist.cancel")}
            </Button>,
            <Button
              key="insert"
              type="primary"
              disabled={!result}
              onClick={() => {
                if (!result) return;
                onReplace(result.body.doc as unknown as BodyNode, "en");
                void message.success(t("form.assist.inserted"));
                close();
              }}
            >
              {t("form.assist.insert")}
            </Button>,
          ]}
        >
          {pending ? (
            <div role="status">
              <Spin size="small" /> {t("form.assist.pending")}
            </div>
          ) : null}
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
          {result ? (
            <div className="pf-new-assist-columns">
              <section aria-label={t("form.assist.translation")}>
                <h3 className="pf-fp-title">{t("form.assist.translation")}</h3>
                <p className="pf-new-assist-text">{bodyText(result.body)}</p>
              </section>
              <section aria-label={t("form.assist.back")}>
                <h3 className="pf-fp-title">{t("form.assist.back")}</h3>
                <p className="pf-new-assist-text">{result.back_translation ?? ""}</p>
              </section>
            </div>
          ) : null}
        </Modal>
      ) : null}
    </div>
  );
}
