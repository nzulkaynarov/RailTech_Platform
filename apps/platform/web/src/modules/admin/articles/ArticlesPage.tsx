import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Select, Skeleton } from "antd";
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
import { RowActions, ROW_ACTIONS_WIDTH } from "../../../shared/ui/RowActions";
import { ArticleEditor, type Outcome } from "./ArticleEditor";
import { articleErrorText } from "./errors";

import "../../../features/help/help.css";
import "./articles.css";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { PageFrame } from "../../../shared/ui/PageFrame";

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
  const actionMenu = (article: CompanyArticle) => (
    <RowActions
      name={article.title}
      items={
        editable
          ? [
              article.status === "draft"
                ? {
                    key: "publish",
                    label: t("admin.actions.publish"),
                    disabled: busy,
                    onClick: () => {
                      setNotice("");
                      publish.mutate({ id: article.id });
                    },
                  }
                : {
                    key: "unpublish",
                    label: t("admin.actions.unpublish"),
                    disabled: busy,
                    onClick: () => {
                      setNotice("");
                      confirmUnpublish(article);
                    },
                  },
              {
                key: "delete",
                label: t("admin.actions.delete"),
                danger: true,
                disabled: busy,
                onClick: () => {
                  setNotice("");
                  confirmDelete(article);
                },
              },
            ]
          : []
      }
    />
  );

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
              <span style={{ marginLeft: "auto" }}>{actionMenu(article)}</span>
            </div>
            <div className="pf-hint" style={{ margin: "4px 0 8px" }}>
              {t(`admin.language.${article.language}`)} · {changed(article)}
            </div>
          </li>
        ))}
      </ul>
    );
  } else {
    body = (
      <DataTable<CompanyArticle>
        tableId="admin.articles"
        caption={t("admin.listLabel")}
        scrollLabel={t("admin.listLabel")}
        rows={items}
        rowKey={(row) => String(row.id)}
        columns={[
          {
            id: "title",
            header: t("admin.columns.title"),
            width: 352,
            cell: (article) => (
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
            id: "language",
            header: t("admin.columns.language"),
            width: 132,
            cell: (article) => t(`admin.language.${article.language}`),
          },
          {
            id: "status",
            header: t("admin.columns.status"),
            width: 176,
            cell: (article) => statusTag(article),
          },
          {
            id: "updated",
            header: t("admin.columns.updated"),
            width: 220,
            cell: (article) => changed(article),
          },
          {
            id: "actions",
            header: t("admin.columns.actions"),
            headerHidden: true,
            width: ROW_ACTIONS_WIDTH,
            cell: (article) => actionMenu(article),
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
    <PageFrame layout="registry">
      <PageHeader
        title={title}
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
            <FilterBar
              inset
              label={t("admin.filtersLabel")}
              actions={
                list.data ? (
                  <span className="pf-hint" aria-live="polite">
                    {t("admin.counts", { total: all.length, drafts })}
                  </span>
                ) : undefined
              }
            >
              <FilterField id={`${base}-status`} label={t("admin.status")}>
                <Select<CompanyArticleStatus>
                  id={`${base}-status`}
                  allowClear
                  placeholder={t("admin.allStatuses")}
                  value={status}
                  options={STATUSES.map((value) => ({
                    value,
                    label: t(`admin.status_${value}`),
                  }))}
                  onChange={(value?: CompanyArticleStatus) => {
                    setStatus(value);
                  }}
                />
              </FilterField>
            </FilterBar>
            {body}
          </>
        )}
      </Card>
      <PanelPortal tab="card">
        <EmptyState level={3} compact title={t("admin.panelTitle")} text={t("admin.panelText")} />
      </PanelPortal>
    </PageFrame>
  );
}
