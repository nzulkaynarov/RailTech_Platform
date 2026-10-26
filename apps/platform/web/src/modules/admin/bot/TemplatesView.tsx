import { App, Button, Card, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import type { ReplyTemplate, ReplyTemplateIn } from "../../../shared/api/generated/model";
import {
  useCreateReplyTemplate,
  useDeleteReplyTemplate,
  useListReplyTemplates,
  useUpdateReplyTemplate,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { EmptyState } from "../../../shared/ui/EmptyState";
import {
  ActionToggle,
  ErrorNote,
  FormField,
  QueryState,
  ScrollRegion,
} from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { botErrorText } from "./errors";
import { useBotStateLabels } from "./labels";
import { parseId, useRefreshBot, withParams } from "./refresh";

const LANGS = ["ru", "uz", "en"] as const;
const BLANK: ReplyTemplateIn = { title: "", text: { ru: "", uz: "", en: "" } };

function TemplateForm({
  template,
  onClose,
}: {
  template: ReplyTemplate | null;
  onClose: () => void;
}) {
  const { t } = useTranslation(["bot", "kb"]);
  const { message } = App.useApp();
  const refresh = useRefreshBot();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [draft, setDraft] = useState<ReplyTemplateIn>(
    template ? { title: template.title, text: template.text } : BLANK,
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Создание открывает новый шаблон, правка остаётся в карточке, удаление закрывает её.
  const done = (text: string, next: "open" | "stay" | "close", id: number | null = null) => {
    void refresh();
    void message.success(text);
    if (next === "open" && id !== null) {
      void navigate({ search: withParams(params, { template: String(id) }) }, { replace: true });
    } else if (next === "close") onClose();
  };
  const create = useCreateReplyTemplate({
    mutation: {
      onSuccess: (out) => {
        done(t("bot:templates.created"), "open", out.id);
      },
    },
  });
  const update = useUpdateReplyTemplate({
    mutation: {
      onSuccess: () => {
        done(t("bot:templates.saved"), "stay");
      },
    },
  });
  const remove = useDeleteReplyTemplate({
    mutation: {
      onSuccess: () => {
        done(t("bot:templates.removed"), "close");
      },
    },
  });
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;
  const invalid = draft.title.trim() === "" || draft.text.ru.trim() === "";
  return (
    <div className="pf-fp-stack">
      <h3 className="pf-fp-title">{template ? template.title : t("bot:templates.new")}</h3>
      <form
        className="pf-fp-form"
        aria-label={t(template ? "bot:templates.edit" : "bot:templates.new")}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (invalid || pending) return;
          const data = { title: draft.title.trim(), text: draft.text };
          if (template) update.mutate({ id: template.id, data });
          else create.mutate({ data });
        }}
      >
        <FormField
          id="tpl-title"
          label={t("bot:templates.fieldTitle")}
          hint={t("bot:templates.titleHint")}
        >
          <Input
            id="tpl-title"
            value={draft.title}
            maxLength={120}
            autoComplete="off"
            onChange={(event) => {
              setDraft({ ...draft, title: event.target.value });
            }}
          />
        </FormField>
        {LANGS.map((lang) => (
          <FormField
            key={lang}
            id={`tpl-text-${lang}`}
            label={t("bot:templates.text", { language: t(`kb:languages.${lang}`) })}
            hint={lang === "ru" ? t("bot:templates.placeholders") : t("bot:templates.fallbackHint")}
          >
            <Input.TextArea
              id={`tpl-text-${lang}`}
              value={draft.text[lang]}
              maxLength={4000}
              autoSize={{ minRows: 3, maxRows: 8 }}
              onChange={(event) => {
                setDraft({ ...draft, text: { ...draft.text, [lang]: event.target.value } });
              }}
            />
          </FormField>
        ))}
        <Consequence
          items={[t("bot:templates.step1"), t("bot:templates.step2"), t("bot:templates.step3")]}
        />
        <ErrorNote message={error ? botErrorText(t, error) : null} />
        <div className="pf-fp-row">
          <Button type="primary" htmlType="submit" loading={pending} disabled={invalid}>
            {t(template ? "bot:templates.save" : "bot:templates.create")}
          </Button>
        </div>
      </form>
      {template ? (
        <section className="pf-fp-block" aria-labelledby="tpl-delete-title">
          <h4 id="tpl-delete-title">{t("bot:templates.dangerTitle")}</h4>
          <ActionToggle
            danger
            label={t("bot:templates.remove")}
            open={confirmDelete}
            onToggle={setConfirmDelete}
          >
            <form
              className="pf-fp-form"
              aria-label={t("bot:templates.remove")}
              onSubmit={(event) => {
                event.preventDefault();
                remove.mutate({ id: template.id });
              }}
            >
              <Consequence
                items={[
                  t("bot:templates.removeStep1"),
                  t("bot:templates.removeStep2"),
                  t("bot:templates.removeStep3"),
                ]}
              />
              <ErrorNote message={remove.isError ? botErrorText(t, remove.error) : null} />
              <div className="pf-fp-row">
                <Button type="primary" danger htmlType="submit" loading={remove.isPending}>
                  {t("bot:templates.removeSubmit")}
                </Button>
              </div>
            </form>
          </ActionToggle>
        </section>
      ) : null}
    </div>
  );
}

/** Шаблоны быстрых ответов: список, создание, правка и удаление (карточка — в боковом окне). */
export function TemplatesView({ editable }: { editable: boolean }) {
  const { t } = useTranslation("bot");
  const { date } = useFormat();
  const query = useListReplyTemplates();
  const labels = useBotStateLabels();
  const [params] = useSearchParams();
  const requested = params.get("template");
  const selectedId = parseId(requested);
  const creating = requested === "new" && editable;
  const navigate = useNavigate();
  const close = () => {
    void navigate({ search: withParams(params, { template: null }) }, { replace: true });
  };
  return (
    <section aria-labelledby="pf-bot-templates">
      <Card
        styles={{ body: { padding: 0 } }}
        title={
          <h2 className="pf-bot-section-title" id="pf-bot-templates">
            {t("templates.title")}
          </h2>
        }
        extra={
          editable ? (
            <LinkButton type="primary" to={withParams(params, { template: "new", panel: "open" })}>
              {t("templates.new")}
            </LinkButton>
          ) : null
        }
      >
        <p className="pf-fp-sub pf-bot-lead">{t("templates.intro")}</p>
        <QueryState query={query} labels={labels}>
          {(data) => {
            const selected = data.items.find((tpl) => tpl.id === selectedId) ?? null;
            return (
              <>
                {data.items.length === 0 ? (
                  <EmptyState
                    title={t("templates.empty.title")}
                    text={t("templates.empty.text")}
                    action={
                      editable ? (
                        <LinkButton
                          type="primary"
                          to={withParams(params, { template: "new", panel: "open" })}
                        >
                          {t("templates.new")}
                        </LinkButton>
                      ) : undefined
                    }
                  />
                ) : (
                  <ScrollRegion label={t("templates.tableScroll")}>
                    <table className="pf-bot-table">
                      <caption className="pf-sr-only">{t("templates.caption")}</caption>
                      <thead>
                        <tr>
                          <th scope="col">{t("templates.columns.title")}</th>
                          <th scope="col">{t("templates.columns.text")}</th>
                          <th scope="col">{t("templates.columns.updated")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.items.map((tpl) => (
                          <tr key={tpl.id} data-selected={selectedId === tpl.id}>
                            <td>
                              <Link
                                className="pf-focusable pf-bot-link"
                                to={withParams(params, { template: String(tpl.id), panel: "open" })}
                                aria-label={t("templates.open", { title: tpl.title })}
                                aria-current={selectedId === tpl.id ? "true" : undefined}
                              >
                                {tpl.title}
                              </Link>
                            </td>
                            <td className="pf-bot-excerpt">{tpl.text.ru}</td>
                            <td>{date(tpl.updated_at, "datetime")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollRegion>
                )}
                {creating ? (
                  <PanelPortal tab="card">
                    <TemplateForm key="new" template={null} onClose={close} />
                  </PanelPortal>
                ) : selected ? (
                  <PanelPortal tab="card">
                    <TemplateForm
                      key={`${String(selected.id)}-${selected.updated_at}`}
                      template={selected}
                      onClose={close}
                    />
                  </PanelPortal>
                ) : null}
              </>
            );
          }}
        </QueryState>
      </Card>
    </section>
  );
}
