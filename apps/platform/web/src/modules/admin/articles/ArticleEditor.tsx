import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ArticleView } from "../../../features/help/ArticleView";
import type { HelpArticle } from "../../../features/help/articles";
import type { CompanyArticle, CompanyArticleLanguage } from "../../../shared/api/generated/model";
import {
  getListAdminCompanyArticlesQueryKey,
  getListCompanyArticlesQueryKey,
  useCreateCompanyArticle,
  usePublishCompanyArticle,
  useUpdateCompanyArticle,
} from "../../../shared/api/generated/platform-bff";
import { ContextualSaveBar } from "../../../shared/ui/ContextualSaveBar";
import { articleErrorText } from "./errors";

import "../../../features/help/help.css";
import "./articles.css";

export const TITLE_MAX = 200;
export const BODY_MAX = 20000;
const LANGUAGES: readonly CompanyArticleLanguage[] = ["ru", "uz", "en"];

export type Outcome = "created" | "updated" | "published";

interface Props {
  /** Правится существующая статья; без неё — новая */
  article?: CompanyArticle | undefined;
  /** Директор: читает и черновики, но не правит */
  readOnly: boolean;
  /** Закрыть редактор (без сохранения или после него); `outcome` — что сделано */
  onClose: (outcome?: Outcome) => void;
}

/**
 * Редактор статьи компании (W18A-P5, B-079): заголовок, язык и текст в простом Markdown слева, предпросмотр справа тем
 * же безопасным рендером, что в Помощи (`Markdown` без `dangerouslySetInnerHTML`: HTML и ссылки остаются текстом).
 * Новая статья — черновик; «Сохранить и опубликовать» публикует сразу. Несохранённое при уходе с экрана подтверждается.
 */
export function ArticleEditor({ article: initial, readOnly, onClose }: Props) {
  const { t } = useTranslation("articles");
  const { modal } = App.useApp();
  const queryClient = useQueryClient();
  const ids = useId();
  // Сохранённая версия: после «создать» и неудачной «опубликовать» повтор правит эту статью, а не создаёт вторую.
  const [article, setArticle] = useState(initial);
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [language, setLanguage] = useState<CompanyArticleLanguage>(initial?.language ?? "ru");
  const [touched, setTouched] = useState(false);

  const dirty = article
    ? title !== article.title || body !== article.body || language !== article.language
    : title !== "" || body !== "";

  const create = useCreateCompanyArticle();
  const update = useUpdateCompanyArticle();
  const publish = usePublishCompanyArticle();
  const busy = create.isPending || update.isPending || publish.isPending;
  const error = create.error ?? update.error ?? publish.error;

  const trimmedTitle = title.split(/\s+/).filter(Boolean).join(" ");
  const trimmedBody = body.trim();
  const titleError = !touched
    ? undefined
    : trimmedTitle === ""
      ? t("editor.titleRequired")
      : trimmedTitle.length > TITLE_MAX
        ? t("editor.titleTooLong", { max: TITLE_MAX })
        : undefined;
  const bodyError = !touched
    ? undefined
    : trimmedBody === ""
      ? t("editor.bodyRequired")
      : trimmedBody.length > BODY_MAX
        ? t("editor.bodyTooLong", { max: BODY_MAX })
        : undefined;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListAdminCompanyArticlesQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListCompanyArticlesQueryKey() });
  };

  const save = async (andPublish: boolean) => {
    setTouched(true);
    create.reset();
    update.reset();
    publish.reset();
    if (
      trimmedTitle === "" ||
      trimmedTitle.length > TITLE_MAX ||
      trimmedBody === "" ||
      trimmedBody.length > BODY_MAX
    ) {
      return;
    }
    try {
      let saved = article;
      if (!saved) {
        saved = await create.mutateAsync({ data: { title, body, language } });
        setArticle(saved);
      } else if (dirty) {
        saved = await update.mutateAsync({ id: saved.id, data: { title, body, language } });
        setArticle(saved);
      }
      if (andPublish) setArticle(await publish.mutateAsync({ id: saved.id }));
      refresh();
      onClose(andPublish ? "published" : initial ? "updated" : "created");
    } catch {
      // Текст ошибки показан под формой; частично сохранённое (черновик без публикации) видно в списке.
      refresh();
    }
  };

  const close = () => {
    if (!dirty || readOnly) {
      onClose();
      return;
    }
    modal.confirm({
      title: t("editor.discardTitle"),
      content: t("editor.discardText"),
      okText: t("editor.discardOk"),
      cancelText: t("editor.discardCancel"),
      okButtonProps: { danger: true },
      onOk: () => {
        onClose();
      },
    });
  };

  const published = article?.status === "published";
  const previewArticle: HelpArticle = {
    slug: "preview",
    title: trimmedTitle || t("editor.previewHeading"),
    sections: [],
    screens: [],
    order: 0,
    body: trimmedBody,
    source: "company",
    language,
    ...(article?.updated_at ? { updatedAt: article.updated_at } : {}),
  };
  const heading = readOnly
    ? t("editor.titleView")
    : article
      ? t("editor.titleEdit")
      : t("editor.titleNew");

  return (
    <div className="pf-help-block" style={{ gap: 16 }}>
      <div>
        <Button onClick={close}>{t("editor.back")}</Button>
      </div>
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>{heading}</h2>
      <div className="pf-ca-editor">
        <form
          className="pf-ca-fields"
          aria-label={heading}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!readOnly) void save(false);
          }}
        >
          {error ? (
            <Alert type="error" showIcon role="alert" message={articleErrorText(t, error)} />
          ) : null}
          <div className="pf-ca-row">
            <div className="pf-ca-field" style={{ flex: "1 1 260px" }}>
              <label htmlFor={`${ids}-title`}>{t("editor.titleField")}</label>
              <Input
                id={`${ids}-title`}
                value={title}
                readOnly={readOnly}
                placeholder={t("editor.titlePlaceholder")}
                status={titleError ? "error" : undefined}
                aria-invalid={titleError ? true : undefined}
                aria-describedby={titleError ? `${ids}-title-error` : undefined}
                onChange={(event) => {
                  setTitle(event.target.value);
                }}
              />
              {titleError ? (
                <div id={`${ids}-title-error`} role="alert" className="pf-ca-error">
                  {titleError}
                </div>
              ) : null}
            </div>
            <div className="pf-ca-field">
              <label htmlFor={`${ids}-language`}>{t("editor.languageField")}</label>
              <Select<CompanyArticleLanguage>
                id={`${ids}-language`}
                value={language}
                disabled={readOnly}
                style={{ minWidth: 160 }}
                options={LANGUAGES.map((value) => ({
                  value,
                  label: t(`admin.language.${value}`),
                }))}
                onChange={setLanguage}
              />
            </div>
          </div>
          <div className="pf-ca-field">
            <label htmlFor={`${ids}-body`}>{t("editor.bodyField")}</label>
            <Input.TextArea
              id={`${ids}-body`}
              rows={14}
              value={body}
              readOnly={readOnly}
              status={bodyError ? "error" : undefined}
              aria-invalid={bodyError ? true : undefined}
              aria-describedby={`${ids}-body-help${bodyError ? ` ${ids}-body-error` : ""}`}
              onChange={(event) => {
                setBody(event.target.value);
              }}
            />
            {bodyError ? (
              <div id={`${ids}-body-error`} role="alert" className="pf-ca-error">
                {bodyError}
              </div>
            ) : null}
            <div id={`${ids}-body-help`} className="pf-hint">
              {readOnly ? null : <div>{t("editor.bodyHelp")}</div>}
              <div>{t("editor.counter", { count: trimmedBody.length, max: BODY_MAX })}</div>
            </div>
          </div>
          {readOnly ? null : (
            <>
              <p className="pf-hint" style={{ margin: 0 }}>
                {published
                  ? t("editor.consequencePublished")
                  : `${t("editor.consequenceDraft")} ${t("editor.consequencePublish")}`}
              </p>
              {published ? null : (
                <div className="pf-ca-actions">
                  <Button
                    disabled={busy}
                    onClick={() => {
                      void save(true);
                    }}
                  >
                    {t("editor.saveAndPublish")}
                  </Button>
                </div>
              )}
              {/* «Сохранить» черновик или статью — только в баре (UX-1b, S6): он держит место в конце формы */}
              <ContextualSaveBar
                visible={dirty}
                message={t("editor.unsaved")}
                saveLabel={article ? t("editor.save") : t("editor.saveDraft")}
                loading={busy}
                onSave={() => {
                  void save(false);
                }}
                onDiscard={() => {
                  setTitle(article?.title ?? "");
                  setBody(article?.body ?? "");
                  setLanguage(article?.language ?? "ru");
                  setTouched(false);
                  create.reset();
                  update.reset();
                  publish.reset();
                }}
              />
            </>
          )}
        </form>
        <section className="pf-ca-preview" aria-labelledby={`${ids}-preview`}>
          <h2 id={`${ids}-preview`}>{t("editor.previewTitle")}</h2>
          {trimmedBody === "" ? (
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("editor.previewEmpty")}
            </p>
          ) : (
            <ArticleView article={previewArticle} headingLevel={3} />
          )}
        </section>
      </div>
    </div>
  );
}
