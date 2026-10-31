import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Select, Skeleton, Table } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import type { CompanyArticle, CompanyArticleStatus } from "../../../shared/api/generated/model";
import {
  getListAdminCompanyArticlesQueryKey,
  getListCompanyArticlesQueryKey,
  useDeleteCompanyArticle,
  useListAdminCompanyArticles,
  usePublishCompanyArticle,
  useUnpublishCompanyArticle,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ArticleEditor, type Outcome } from "./ArticleEditor";
import { articleErrorText } from "./errors";

import "../../../features/help/help.css";
import "./articles.css";

const EDIT_PARAM = "edit";
const STATUSES: readonly CompanyArticleStatus[] = ["draft", "published"];

/**
 * Admin · Статьи компании (W18A-P5, B-079): внутренние инструкции «как у нас принято». Список со статусом
 * «Черновик / Опубликовано», создание и правка в редакторе с предпросмотром, публикация, снятие и удаление с
 * подтверждением. Пишет администратор (`admin` полный); директор читает, в том числе черновики. Опубликованные статьи
 * сотрудники видят в Помощи, раздел «Как у нас принято». Редактор открывается адресом `?edit=<id>` (`?edit=new` — новая).
 */
export function ArticlesPage() {
  const { t } = useTranslation("articles");
  const { me } = useAuth();
  const format = useFormat();
  const { mobile } = useViewport();
  const { modal } = App.useApp();
  const queryClient = useQueryClient();
  const base = useId();
  const [params, setParams] = useSearchParams();
  const editable = canEdit(me, "admin");
  const title = t("admin.title");
  useDocumentTitle(title);

  const [status, setStatus] = useState<CompanyArticleStatus | undefined>();
  const [notice, setNotice] = useState("");
  const list = useListAdminCompanyArticles();
  const all = list.data?.items ?? [];
  const items = status ? all.filter((a) => a.status === status) : all;
  const drafts = all.filter((a) => a.status === "draft").length;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListAdminCompanyArticlesQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListCompanyArticlesQueryKey() });
  };
  const publish = usePublishCompanyArticle({
    mutation: {
      onSuccess: () => {
        setNotice(t("admin.done.published"));
        refresh();
      },
    },
  });
  const unpublish = useUnpublishCompanyArticle({
    mutation: {
      onSuccess: () => {
        setNotice(t("admin.done.unpublished"));
        refresh();
      },
    },
  });
  const remove = useDeleteCompanyArticle({
    mutation: {
      onSuccess: () => {
        setNotice(t("admin.done.deleted"));
        refresh();
      },
    },
  });
  const failure = publish.error ?? unpublish.error ?? remove.error;

  const editing = params.get(EDIT_PARAM);
  const open = (value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(EDIT_PARAM, value);
    else next.delete(EDIT_PARAM);
    setParams(next);
  };
  const closeEditor = (outcome?: Outcome) => {
    if (outcome) setNotice(t(`admin.done.${outcome}`));
    open(null);
  };

  const confirmDelete = (article: CompanyArticle) => {
    modal.confirm({
      title: t("admin.delete.title"),
      content: t("admin.delete.text", { title: article.title }),
      okText: t("admin.delete.ok"),
      cancelText: t("admin.delete.cancel"),
      okButtonProps: { danger: true },
      onOk: () =>
        remove.mutateAsync({ id: article.id }).then(
          () => undefined,
          () => undefined,
        ),
    });
  };
  const confirmUnpublish = (article: CompanyArticle) => {
    modal.confirm({
      title: t("admin.unpublishConfirm.title"),
      content: t("admin.unpublishConfirm.text", { title: article.title }),
      okText: t("admin.unpublishConfirm.ok"),
      cancelText: t("admin.unpublishConfirm.cancel"),
      onOk: () =>
        unpublish.mutateAsync({ id: article.id }).then(
          () => undefined,
          () => undefined,
        ),
    });
  };

  const busy = publish.isPending || unpublish.isPending || remove.isPending;
  const actionButtons = (article: CompanyArticle) => {
    const label = (key: "edit" | "view" | "publish" | "unpublish" | "delete") =>
      t("admin.actionFor", { action: t(`admin.actions.${key}`), title: article.title });
    return (
      <div className="pf-ca-actions">
        <Button
          size="small"
          aria-label={label(editable ? "edit" : "view")}
          onClick={() => {
            open(String(article.id));
          }}
        >
          {editable ? t("admin.actions.edit") : t("admin.actions.view")}
        </Button>
        {editable ? (
          <>
            {article.status === "draft" ? (
              <Button
                size="small"
                disabled={busy}
                aria-label={label("publish")}
                onClick={() => {
                  setNotice("");
                  publish.mutate({ id: article.id });
                }}
              >
                {t("admin.actions.publish")}
              </Button>
            ) : (
              <Button
                size="small"
                disabled={busy}
                aria-label={label("unpublish")}
                onClick={() => {
                  setNotice("");
                  confirmUnpublish(article);
                }}
              >
                {t("admin.actions.unpublish")}
              </Button>
            )}
            <Button
              size="small"
              danger
              disabled={busy}
              aria-label={label("delete")}
              onClick={() => {
                setNotice("");
                confirmDelete(article);
              }}
            >
              {t("admin.actions.delete")}
            </Button>
          </>
        ) : null}
      </div>
    );
  };

  const statusTag = (article: CompanyArticle) => (
    <StatusTag kind="article" status={article.status}>
      {t(`admin.status_${article.status}`)}
    </StatusTag>
  );
  const changed = (article: CompanyArticle) =>
    [format.activity(article.updated_at), article.updated_by_name].filter(Boolean).join(" · ");

  let body;
  if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("admin.loadError")}
        text={t("admin.loadErrorText")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("admin.retry")}
          </Button>
        }
      />
    );
  } else if (all.length === 0) {
    body = (
      <EmptyState
        title={t("admin.empty")}
        text={editable ? t("admin.emptyText") : t("admin.emptyReadOnly")}
        action={
          editable ? (
            <Button
              type="primary"
              onClick={() => {
                open("new");
              }}
            >
              {t("admin.new")}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (items.length === 0) {
    body = (
      <EmptyState
        title={t("admin.noMatch")}
        text={t("admin.noMatchText")}
        action={
          <Button
            onClick={() => {
              setStatus(undefined);
            }}
          >
            {t("admin.reset")}
          </Button>
        }
      />
    );
  } else if (mobile) {
    body = (
      <ul aria-label={t("admin.listLabel")} style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {items.map((article) => (
          <li key={article.id} className="pf-ca-item">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button
                type="button"
                className="pf-ca-title pf-focusable"
                onClick={() => {
                  open(String(article.id));
                }}
              >
                {article.title}
              </button>
              {statusTag(article)}
            </div>
            <div className="pf-hint" style={{ margin: "4px 0 8px" }}>
              {t(`admin.language.${article.language}`)} · {changed(article)}
            </div>
            {actionButtons(article)}
          </li>
        ))}
      </ul>
    );
  } else {
    body = (
      <Table<CompanyArticle>
        rowKey="id"
        dataSource={items}
        pagination={false}
        tableLayout="fixed"
        aria-label={t("admin.listLabel")}
        columns={[
          {
            title: t("admin.columns.title"),
            key: "title",
            width: "32%",
            render: (_, article) => (
              <button
                type="button"
                className="pf-ca-title pf-focusable"
                onClick={() => {
                  open(String(article.id));
                }}
              >
                {article.title}
              </button>
            ),
          },
          {
            title: t("admin.columns.language"),
            key: "language",
            width: "12%",
            render: (_, article) => t(`admin.language.${article.language}`),
          },
          {
            title: t("admin.columns.status"),
            key: "status",
            width: "16%",
            render: (_, article) => statusTag(article),
          },
          {
            title: t("admin.columns.updated"),
            key: "updated",
            width: "20%",
            render: (_, article) => changed(article),
          },
          {
            title: t("admin.columns.actions"),
            key: "actions",
            width: "20%",
            render: (_, article) => actionButtons(article),
          },
        ]}
      />
    );
  }

  const target =
    editing && editing !== "new" ? all.find((a) => String(a.id) === editing) : undefined;
  let editor = null;
  if (editing === "new" && editable) {
    editor = <ArticleEditor key="new" readOnly={false} onClose={closeEditor} />;
  } else if (editing && editing !== "new") {
    editor = list.isPending ? (
      <Skeleton active paragraph={{ rows: 8 }} />
    ) : target ? (
      <ArticleEditor key={target.id} article={target} readOnly={!editable} onClose={closeEditor} />
    ) : (
      <EmptyState
        title={t("editor.errors.NOT_FOUND")}
        text={t("admin.loadErrorText")}
        action={
          <Button
            onClick={() => {
              open(null);
            }}
          >
            {t("editor.back")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={t("admin.subtitle")}
        extra={
          editable && !editing ? (
            <Button
              type="primary"
              onClick={() => {
                setNotice("");
                open("new");
              }}
            >
              {t("admin.new")}
            </Button>
          ) : undefined
        }
      />
      <div role="status" className="pf-hint" style={{ minHeight: 22 }}>
        {notice}
      </div>
      <Card styles={{ body: editor ? undefined : { padding: 0 } }}>
        {editor ?? (
          <>
            {failure ? (
              <Alert
                type="error"
                showIcon
                role="alert"
                message={articleErrorText(t, failure)}
                style={{ margin: 16 }}
              />
            ) : null}
            {!editable ? (
              <p className="pf-hint" style={{ margin: 16 }}>
                {t("admin.readOnly")}
              </p>
            ) : null}
            <form
              className="pf-ticket-filters"
              role="search"
              aria-label={t("admin.filtersLabel")}
              onSubmit={(event) => {
                event.preventDefault();
              }}
            >
              <div className="pf-ticket-field">
                <label htmlFor={`${base}-status`}>{t("admin.status")}</label>
                <Select<CompanyArticleStatus>
                  id={`${base}-status`}
                  allowClear
                  placeholder={t("admin.allStatuses")}
                  style={{ minWidth: 200 }}
                  value={status}
                  options={STATUSES.map((value) => ({
                    value,
                    label: t(`admin.status_${value}`),
                  }))}
                  onChange={(value?: CompanyArticleStatus) => {
                    setStatus(value);
                  }}
                />
              </div>
              {list.data ? (
                <span className="pf-hint" aria-live="polite" style={{ marginLeft: "auto" }}>
                  {t("admin.counts", { total: all.length, drafts })}
                </span>
              ) : null}
            </form>
            {body}
          </>
        )}
      </Card>
      <PanelPortal tab="card">
        <EmptyState level={3} compact title={t("admin.panelTitle")} text={t("admin.panelText")} />
      </PanelPortal>
    </>
  );
}
