import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Select, Skeleton } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import type { LegalEditionRow, LegalKind } from "../../../shared/api/generated/model";
import {
  getListLegalAcceptancesQueryKey,
  getListLegalEditionsQueryKey,
  useCreateLegalEdition,
  useDeleteLegalEdition,
  useListLegalAcceptances,
  useListLegalEditions,
  usePublishLegalEdition,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";
import { Dialog } from "../../../shared/ui/Dialog";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { SettingsPage } from "../settings/SettingsPage";
import { useSettingsEditable } from "../settings/useSettingsEditable";
import { legalErrorText } from "./errors";
import { LegalEditor } from "./LegalEditor";
import { LegalReader } from "./LegalReader";

import "./legal.css";

const KINDS: readonly LegalKind[] = ["terms", "privacy"];
const VIEW = "view";
const EDIT = "edit";
const LOG_PAGE = 100;

/**
 * Admin · Оферта и политика (ДВ-5): тексты, которые контакт кабинета принимает при первом входе и при каждой новой
 * редакции. Два документа — две карточки: что действует сейчас, черновик, чтение на трёх языках, новая редакция
 * (копия действующей), публикация с подтверждением. Ниже — список всех редакций и журнал принятий (только чтение).
 * Адрес `?view=<id>` — чтение, `?edit=<id>` — правка черновика. Правит директор и администратор (`company.settings`).
 */
export function LegalPage() {
  const { t } = useTranslation("legal");
  const format = useFormat();
  const queryClient = useQueryClient();
  const editable = useSettingsEditable("legal");
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState("");
  const [publishing, setPublishing] = useState<LegalEditionRow | null>(null);
  const [discarding, setDiscarding] = useState<LegalEditionRow | null>(null);

  const list = useListLegalEditions();
  const editions = list.data?.items ?? [];
  const create = useCreateLegalEdition();
  const publish = usePublishLegalEdition();
  const discard = useDeleteLegalEdition();
  const failure = create.error ?? publish.error ?? discard.error;
  const busy = create.isPending || publish.isPending || discard.isPending;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListLegalEditionsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListLegalAcceptancesQueryKey() });
  };
  const open = (key: string, id: string | null) => {
    const next = new URLSearchParams(params);
    next.delete(VIEW);
    next.delete(EDIT);
    if (id) next.set(key, id);
    setParams(next);
  };
  const reading = params.get(VIEW);
  const editing = params.get(EDIT);

  const current = (kind: LegalKind) =>
    editions.find((e) => e.kind === kind && e.status === "current");
  const draft = (kind: LegalKind) => editions.find((e) => e.kind === kind && e.status === "draft");

  const startNew = (kind: LegalKind) => {
    setNotice("");
    create.reset();
    create.mutate(
      { data: { kind } },
      {
        onSuccess: (edition) => {
          setNotice(t("created", { label: edition.label }));
          refresh();
          open(EDIT, edition.id);
        },
      },
    );
  };
  const doPublish = () => {
    const target = publishing;
    if (!target) return;
    publish.mutate(
      { id: target.id },
      {
        onSuccess: () => {
          setNotice(t("publish.done", { label: target.label }));
          setPublishing(null);
          refresh();
        },
        onError: () => {
          setPublishing(null);
        },
      },
    );
  };
  const doDiscard = () => {
    const target = discarding;
    if (!target) return;
    discard.mutate(
      { id: target.id },
      {
        onSuccess: () => {
          setNotice(t("discard.done"));
          setDiscarding(null);
          refresh();
        },
        onError: () => {
          setDiscarding(null);
        },
      },
    );
  };

  let body;
  if (reading) {
    body = (
      <Card>
        <LegalReader
          id={reading}
          onClose={() => {
            open(VIEW, null);
          }}
        />
      </Card>
    );
  } else if (editing && editable) {
    body = (
      <Card>
        <LegalEditor
          id={editing}
          onClose={(saved) => {
            if (saved) setNotice(t("editor.saved"));
            refresh();
            open(EDIT, null);
          }}
        />
      </Card>
    );
  } else if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 8 }} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("loadError")}
        text={t("loadErrorText")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  } else {
    const nothingPublished = !editions.some((e) => e.status === "current");
    body = (
      <>
        {nothingPublished ? <Alert type="info" showIcon message={t("noneYet")} /> : null}
        {failure ? (
          <Alert type="error" showIcon role="alert" message={legalErrorText(t, failure)} />
        ) : null}
        <div className="pf-legal-cards">
          {KINDS.map((kind) => {
            const now = current(kind);
            const next = draft(kind);
            return (
              <Card
                key={kind}
                title={<h2 style={{ margin: 0, fontSize: 16 }}>{t(`kinds.${kind}`)}</h2>}
              >
                <div className="pf-legal-card-body">
                  {now ? (
                    <>
                      <p>
                        <strong>
                          {t("card.current", {
                            date: format.date(now.published_at ?? now.created_at),
                          })}
                        </strong>
                      </p>
                      {now.published_by ? (
                        <p className="pf-hint">{t("card.by", { who: now.published_by })}</p>
                      ) : null}
                      <p className="pf-hint">
                        {t("card.accepted", { count: now.acceptances_count })}
                      </p>
                    </>
                  ) : (
                    <p>{t("card.notPublished")}</p>
                  )}
                  <p className="pf-hint">
                    {next ? t("card.draft", { label: next.label }) : t("card.noDraft")}
                  </p>
                  <div className="pf-legal-actions">
                    {now ? (
                      <Button
                        onClick={() => {
                          open(VIEW, now.id);
                        }}
                      >
                        {t("actions.read")}
                      </Button>
                    ) : null}
                    {editable && next ? (
                      <>
                        <Button
                          onClick={() => {
                            open(EDIT, next.id);
                          }}
                        >
                          {t("actions.editDraft")}
                        </Button>
                        <Button
                          type="primary"
                          disabled={busy}
                          onClick={() => {
                            setNotice("");
                            publish.reset();
                            setPublishing(next);
                          }}
                        >
                          {t("actions.publish")}
                        </Button>
                        <Button
                          danger
                          disabled={busy}
                          onClick={() => {
                            setNotice("");
                            discard.reset();
                            setDiscarding(next);
                          }}
                        >
                          {t("actions.discard")}
                        </Button>
                      </>
                    ) : null}
                    {editable && !next ? (
                      <Button
                        disabled={busy}
                        onClick={() => {
                          startNew(kind);
                        }}
                      >
                        {t("actions.newEdition")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
        <Card
          title={<h2 style={{ margin: 0, fontSize: 16 }}>{t("editions.title")}</h2>}
          styles={{ body: { padding: 0 } }}
        >
          <DataTable<LegalEditionRow>
            tableId="admin.legal-editions"
            caption={t("editions.listLabel")}
            scrollLabel={t("editions.listLabel")}
            rows={editions}
            rowKey={(row) => row.id}
            columns={[
              {
                id: "kind",
                header: t("editions.columns.kind"),
                width: 288,
                cell: (row) => t(`kinds.${row.kind}`),
              },
              {
                id: "label",
                header: t("editions.columns.label"),
                width: 144,
                cell: (row) => (
                  <Button
                    type="link"
                    style={{ padding: 0 }}
                    onClick={() => {
                      open(row.status === "draft" && editable ? EDIT : VIEW, row.id);
                    }}
                  >
                    {row.label}
                  </Button>
                ),
              },
              {
                id: "status",
                header: t("editions.columns.status"),
                width: 144,
                cell: (row) => (
                  <StatusTag kind="legalEdition" status={row.status}>
                    {t(`statuses.${row.status}`)}
                  </StatusTag>
                ),
              },
              {
                id: "published",
                header: t("editions.columns.published"),
                width: 220,
                cell: (row) =>
                  row.published_at
                    ? [format.activity(row.published_at), row.published_by]
                        .filter(Boolean)
                        .join(" · ")
                    : "—",
              },
              {
                id: "accepted",
                header: t("editions.columns.accepted"),
                width: 112,
                numeric: true,
                cell: (row) => format.number(row.acceptances_count),
              },
            ]}
          />
        </Card>
        <AcceptanceLog editions={editions} />
      </>
    );
  }

  return (
    <SettingsPage sectionKey="legal" subtitle={t("subtitle")}>
      <div role="status" className="pf-hint" style={{ minHeight: 22 }}>
        {notice}
      </div>
      {body}
      <Dialog
        open={publishing !== null}
        title={t("publish.title", { label: publishing?.label ?? "" })}
        okLabel={t("publish.ok")}
        cancelLabel={t("publish.cancel")}
        loading={publish.isPending}
        onOk={doPublish}
        onCancel={() => {
          setPublishing(null);
        }}
      >
        <p>{t("publish.text")}</p>
        {publishing && current(publishing.kind) ? (
          <p>{t("publish.replaces", { label: current(publishing.kind)?.label ?? "" })}</p>
        ) : null}
        <p className="pf-hint">{t("publish.immutable")}</p>
      </Dialog>
      <Dialog
        open={discarding !== null}
        title={t("discard.title", { label: discarding?.label ?? "" })}
        okLabel={t("discard.ok")}
        cancelLabel={t("discard.cancel")}
        danger
        loading={discard.isPending}
        onOk={doDiscard}
        onCancel={() => {
          setDiscarding(null);
        }}
      >
        {t("discard.text")}
      </Dialog>
    </SettingsPage>
  );
}

/** Журнал принятий: кто, когда, какую редакцию и на каком языке. Только чтение; последние {LOG_PAGE}, дальше — поиском. */
function AcceptanceLog({ editions }: { editions: readonly LegalEditionRow[] }) {
  const { t } = useTranslation("legal");
  const format = useFormat();
  const base = useId();
  const [edition, setEdition] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const query = useListLegalAcceptances({
    page: 1,
    page_size: LOG_PAGE,
    ...(edition ? { edition } : {}),
    ...(search ? { q: search } : {}),
  });
  const rows = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  let content;
  if (query.isPending) {
    content = <Skeleton active paragraph={{ rows: 4 }} title={false} style={{ padding: 16 }} />;
  } else if (query.isError) {
    content = (
      <EmptyState
        level={3}
        title={t("loadError")}
        text={t("loadErrorText")}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  } else if (rows.length === 0) {
    const filtered = Boolean(edition || search);
    content = (
      <EmptyState
        level={3}
        title={filtered ? t("log.noMatch") : t("log.empty")}
        text={filtered ? t("log.noMatchText") : t("log.emptyText")}
      />
    );
  } else {
    content = (
      <DataTable
        tableId="admin.legal-acceptances"
        caption={t("log.tableLabel")}
        scrollLabel={t("log.tableLabel")}
        rows={rows}
        pageSize={25}
        rowKey={(row) => row.id}
        columns={[
          {
            id: "when",
            header: t("log.columns.when"),
            width: 176,
            cell: (row) => format.date(row.accepted_at, "datetime"),
          },
          {
            id: "contact",
            header: t("log.columns.contact"),
            width: 264,
            cell: (row) => [row.contact.name, row.contact.email].filter(Boolean).join(" · "),
          },
          {
            id: "company",
            header: t("log.columns.company"),
            width: 240,
            cell: (row) => row.company.name,
          },
          {
            id: "document",
            header: t("log.columns.document"),
            width: 288,
            cell: (row) => `${t(`kinds.${row.kind}`)} · ${row.edition}`,
          },
          {
            id: "language",
            header: t("log.columns.language"),
            width: 112,
            cell: (row) => t(`languages.${row.language}`),
          },
        ]}
      />
    );
  }

  return (
    <Card
      title={<h2 style={{ margin: 0, fontSize: 16 }}>{t("log.title")}</h2>}
      styles={{ body: { padding: 0 } }}
    >
      <FilterBar
        inset
        label={t("log.label")}
        actions={
          query.data ? (
            <span className="pf-hint" aria-live="polite">
              {t("log.count", { total })}
              {total > rows.length ? ` · ${t("log.capped", { shown: rows.length })}` : ""}
            </span>
          ) : undefined
        }
      >
        <FilterField id={`${base}-edition`} label={t("log.edition")}>
          <Select<string>
            id={`${base}-edition`}
            allowClear
            style={{ minWidth: 220 }}
            placeholder={t("log.allEditions")}
            value={edition}
            options={editions.map((e) => ({
              value: e.id,
              label: `${t(`kinds.${e.kind}`)} · ${e.label}`,
            }))}
            onChange={(value?: string) => {
              setEdition(value);
            }}
          />
        </FilterField>
        <FilterField id={`${base}-q`} label={t("log.search")}>
          <Input.Search
            id={`${base}-q`}
            allowClear
            placeholder={t("log.search")}
            value={q}
            maxLength={100}
            onChange={(event) => {
              setQ(event.target.value);
              if (!event.target.value) setSearch("");
            }}
            onSearch={(value) => {
              setSearch(value.trim());
            }}
          />
        </FilterField>
      </FilterBar>
      {content}
    </Card>
  );
}
