import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Segmented, Select } from "antd";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CatalogCategory,
  CatalogCategoryList,
  CategoryRequest,
} from "../../../../shared/api/generated/model";
import {
  getListCategoryRequestsQueryKey,
  getListCatalogCategoriesQueryKey,
  useApproveCategoryRequest,
  useCreateCatalogCategory,
  useDeleteCatalogCategory,
  useListCatalogCategories,
  useListCategoryRequests,
  useRejectCategoryRequest,
  useUpdateCatalogCategory,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { useFormat } from "../../../../shared/lib/useFormat";
import { ConfirmModal, FormModal, ListTable, QueryGate, TabHeader, ReadOnlyFence } from "../common";
import { errorFields } from "../errors";

type Part = "categories" | "requests";

/** Категории каталога и запросы на новые категории (ERP `catalog/categories`, `catalog/category-requests`). */
export function CategoriesTab() {
  const { t } = useTranslation("company");
  const [part, setPart] = useState<Part>("categories");
  // Число запросов на рассмотрении — в подписи вкладки, чтобы решение не осталось незамеченным.
  const pending = useListCategoryRequests({ status: "pending" });
  const count = pending.data?.items.length ?? 0;
  return (
    <div className="pf-co-body">
      <TabHeader title={t("categories.title")} hint={t("categories.hint")} />
      <Segmented<Part>
        aria-label={t("categories.part")}
        value={part}
        onChange={setPart}
        options={[
          { value: "categories", label: t("categories.parts.categories") },
          { value: "requests", label: t("categories.parts.requests", { count }) },
        ]}
      />
      {part === "categories" ? <CategoryTree /> : <RequestList />}
    </div>
  );
}

// --- дерево категорий ------------------------------------------------------------------------

interface Node extends CatalogCategory {
  children: Node[];
}

function buildTree(items: readonly CatalogCategory[]): Node[] {
  const byId = new Map<string, Node>(items.map((c) => [c.id, { ...c, children: [] }]));
  const roots: Node[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

function descendants(node: Node): Set<string> {
  const out = new Set<string>();
  const walk = (n: Node) => {
    for (const child of n.children) {
      out.add(child.id);
      walk(child);
    }
  };
  walk(node);
  return out;
}

/**
 * Список категорий в ERP кэшируется на 10 минут и правкой не сбрасывается, поэтому после изменения ответ кладётся прямо
 * в кэш запроса (без повторного чтения), а само чтение не повторяется при возврате в окно.
 */
const CATEGORY_QUERY = { query: { staleTime: 10 * 60 * 1000, refetchOnWindowFocus: false } };

function CategoryTree() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListCatalogCategories(CATEGORY_QUERY);
  const [editing, setEditing] = useState<{ node?: Node; parentId?: string | null } | null>(null);
  const [removing, setRemoving] = useState<Node | null>(null);
  const patchCache = (change: (items: CatalogCategory[]) => CatalogCategory[]) => {
    queryClient.setQueryData<CatalogCategoryList>(getListCatalogCategoriesQueryKey(), (list) =>
      list ? { items: change(list.items) } : list,
    );
  };
  const remove = useDeleteCatalogCategory({
    mutation: {
      onSuccess: (_data, { id }) => {
        patchCache((items) => items.filter((c) => c.id !== id));
        setRemoving(null);
        void message.success(t("categories.deleted"));
      },
    },
  });
  const add = (
    <Button
      type="primary"
      onClick={() => {
        setEditing({ parentId: null });
      }}
    >
      {t("categories.add")}
    </Button>
  );

  return (
    <ReadOnlyFence>
      <QueryGate query={query}>
        {({ items }) => {
          const roots = buildTree(items);
          return (
            <>
              {items.length > 0 ? <div>{add}</div> : null}
              {items.length === 0 ? (
                <div className="pf-co-hint">
                  <h3 className="pf-co-title">{t("categories.empty.title")}</h3>
                  <p>{t("categories.empty.text")}</p>
                  {add}
                </div>
              ) : (
                <CategoryNodes
                  nodes={roots}
                  root
                  onAdd={(node) => {
                    setEditing({ parentId: node.id });
                  }}
                  onEdit={(node) => {
                    setEditing({ node });
                  }}
                  onDelete={(node) => {
                    remove.reset();
                    setRemoving(node);
                  }}
                />
              )}
              {editing !== null ? (
                <CategoryModal
                  roots={roots}
                  node={editing.node}
                  parentId={editing.parentId}
                  onClose={() => {
                    setEditing(null);
                  }}
                  onSaved={(saved, created) => {
                    patchCache((list) =>
                      created ? [...list, saved] : list.map((c) => (c.id === saved.id ? saved : c)),
                    );
                    setEditing(null);
                    void message.success(t("saved"));
                  }}
                />
              ) : null}
              <ConfirmModal
                open={removing !== null}
                title={t("categories.deleteTitle", { name: removing?.name ?? "" })}
                okLabel={t("delete")}
                danger
                loading={remove.isPending}
                error={remove.error}
                items={[t("categories.consequence.delete"), t("categories.consequence.children")]}
                onOk={() => {
                  if (removing) remove.mutate({ id: removing.id });
                }}
                onCancel={() => {
                  setRemoving(null);
                }}
              />
            </>
          );
        }}
      </QueryGate>
    </ReadOnlyFence>
  );
}

function CategoryNodes({
  nodes,
  root = false,
  onAdd,
  onEdit,
  onDelete,
}: {
  nodes: Node[];
  root?: boolean;
  onAdd: (node: Node) => void;
  onEdit: (node: Node) => void;
  onDelete: (node: Node) => void;
}) {
  const { t } = useTranslation("company");
  return (
    <ul className={root ? "pf-co-tree pf-co-tree-root" : "pf-co-tree"}>
      {nodes.map((node) => (
        <li key={node.id}>
          <div className="pf-co-node">
            <span>{node.name}</span>
            <span className="pf-co-actions">
              <Button
                type="link"
                size="small"
                aria-label={t("categories.addChildNamed", { name: node.name })}
                onClick={() => {
                  onAdd(node);
                }}
              >
                {t("categories.addChild")}
              </Button>
              <Button
                type="link"
                size="small"
                aria-label={t("editNamed", { name: node.name })}
                onClick={() => {
                  onEdit(node);
                }}
              >
                {t("edit")}
              </Button>
              <Button
                type="link"
                size="small"
                danger
                aria-label={t("deleteNamed", { name: node.name })}
                onClick={() => {
                  onDelete(node);
                }}
              >
                {t("delete")}
              </Button>
            </span>
          </div>
          {node.children.length > 0 ? (
            <CategoryNodes
              nodes={node.children}
              onAdd={onAdd}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function flatten(nodes: Node[], depth = 0): { id: string; label: string }[] {
  return nodes.flatMap((n) => [
    { id: n.id, label: `${"— ".repeat(depth)}${n.name}` },
    ...flatten(n.children, depth + 1),
  ]);
}

interface CategoryValues {
  name: string;
  parent_id: string | null;
}

function CategoryModal({
  roots,
  node,
  parentId,
  onClose,
  onSaved,
}: {
  roots: Node[];
  node?: Node | undefined;
  parentId?: string | null | undefined;
  onClose: () => void;
  onSaved: (saved: CatalogCategory, created: boolean) => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<CategoryValues>();
  const create = useCreateCatalogCategory({
    mutation: {
      onSuccess: (saved) => {
        onSaved(saved, true);
      },
    },
  });
  const update = useUpdateCatalogCategory({
    mutation: {
      onSuccess: (saved) => {
        onSaved(saved, false);
      },
    },
  });
  const mutation = node ? update : create;
  const banned = useMemo(
    () => (node ? new Set([node.id, ...descendants(node)]) : new Set<string>()),
    [node],
  );
  const options = flatten(roots)
    .filter((o) => !banned.has(o.id))
    .map((o) => ({ value: o.id, label: o.label }));
  const initial: CategoryValues = {
    name: node?.name ?? "",
    parent_id: node ? node.parent_id : (parentId ?? null),
  };

  const submit = (values: CategoryValues) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in initial)
          .map((name) => ({
            name: name as keyof CategoryValues,
            errors: [t("categories.invalidField")],
          })),
      );
    };
    const data = { name: values.name.trim(), parent_id: values.parent_id ?? null };
    if (node) update.mutate({ id: node.id, data }, { onError });
    else create.mutate({ data }, { onError });
  };

  return (
    <FormModal
      open
      title={node ? t("categories.editTitle") : t("categories.addTitle")}
      formId={formId}
      submitLabel={t("save")}
      saving={mutation.isPending}
      error={
        mutation.error && errorFields(mutation.error).length === 0 ? mutation.error : undefined
      }
      onCancel={onClose}
    >
      <Form<CategoryValues>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={submit}
      >
        <Form.Item
          name="name"
          label={t("categories.name")}
          rules={[{ required: true, whitespace: true, message: t("required") }]}
        >
          <Input maxLength={255} autoComplete="off" />
        </Form.Item>
        <Form.Item name="parent_id" label={t("categories.parent")} style={{ marginBottom: 0 }}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={t("categories.topLevel")}
            options={options}
          />
        </Form.Item>
      </Form>
    </FormModal>
  );
}

// --- запросы на категории --------------------------------------------------------------------

function RequestList() {
  const { t } = useTranslation("company");
  const { date } = useFormat();
  const query = useListCategoryRequests();
  const [deciding, setDeciding] = useState<{
    row: CategoryRequest;
    action: "approve" | "reject";
  } | null>(null);
  return (
    <ReadOnlyFence>
      <QueryGate query={query}>
        {({ items }) => {
          const sorted = [...items].sort(
            (a, b) => Number(b.status === "pending") - Number(a.status === "pending"),
          );
          return (
            <>
              <ListTable<CategoryRequest>
                label={t("categories.parts.requestsPlain")}
                data={sorted}
                rowKey={(row) => row.id}
                empty={{
                  title: t("categories.requests.empty.title"),
                  text: t("categories.requests.empty.text"),
                }}
                columns={[
                  {
                    title: t("categories.requests.name"),
                    dataIndex: "proposed_name",
                    render: (value: string, row) => (
                      <>
                        <b>{value}</b>
                        {row.parent_name ? (
                          <div className="pf-hint">
                            {t("categories.requests.under", { name: row.parent_name })}
                          </div>
                        ) : null}
                      </>
                    ),
                  },
                  {
                    title: t("categories.requests.why"),
                    dataIndex: "justification",
                    responsive: ["md"],
                    render: (v?: string) => v ?? "—",
                  },
                  {
                    title: t("categories.requests.author"),
                    dataIndex: "requested_by",
                    responsive: ["md"],
                    render: (v?: string) => v ?? "—",
                  },
                  {
                    title: t("categories.requests.created"),
                    dataIndex: "created_at",
                    responsive: ["md"],
                    render: (value: string) => <span className="pf-num">{date(value)}</span>,
                  },
                  {
                    title: t("status"),
                    dataIndex: "status",
                    render: (value: CategoryRequest["status"], row) => (
                      <>
                        <StatusTag kind="categoryRequest" status={value}>
                          {t(`categories.requests.statuses.${value}`)}
                        </StatusTag>
                        {value === "approved" && row.resulting_category_name ? (
                          <div className="pf-hint">{row.resulting_category_name}</div>
                        ) : null}
                        {value === "rejected" && row.review_notes ? (
                          <div className="pf-hint">{row.review_notes}</div>
                        ) : null}
                      </>
                    ),
                  },
                  {
                    title: t("actions"),
                    key: "actions",
                    render: (_: unknown, row) =>
                      row.status === "pending" ? (
                        <span className="pf-co-actions">
                          <Button
                            type="link"
                            size="small"
                            aria-label={t("categories.requests.approveNamed", {
                              name: row.proposed_name,
                            })}
                            onClick={() => {
                              setDeciding({ row, action: "approve" });
                            }}
                          >
                            {t("categories.requests.approve")}
                          </Button>
                          <Button
                            type="link"
                            size="small"
                            danger
                            aria-label={t("categories.requests.rejectNamed", {
                              name: row.proposed_name,
                            })}
                            onClick={() => {
                              setDeciding({ row, action: "reject" });
                            }}
                          >
                            {t("categories.requests.reject")}
                          </Button>
                        </span>
                      ) : null,
                  },
                ]}
              />
              {deciding !== null ? (
                <DecisionModal
                  row={deciding.row}
                  action={deciding.action}
                  onClose={() => {
                    setDeciding(null);
                  }}
                />
              ) : null}
            </>
          );
        }}
      </QueryGate>
    </ReadOnlyFence>
  );
}

/** Решение по запросу: «Что произойдёт» перед кнопкой; одобрение — с выбором заведённой категории, отказ — с причиной. */
export function DecisionModal({
  row,
  action,
  onClose,
}: {
  row: CategoryRequest;
  action: "approve" | "reject";
  onClose: () => void;
}) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const categories = useListCatalogCategories(CATEGORY_QUERY);
  const items = categories.data?.items ?? [];
  const [categoryId, setCategoryId] = useState<string | null>(
    () => items.find((c) => c.name.toLowerCase() === row.proposed_name.toLowerCase())?.id ?? null,
  );
  const [reason, setReason] = useState("");
  const done = (text: string) => {
    void queryClient.invalidateQueries({ queryKey: getListCategoryRequestsQueryKey() });
    void queryClient.invalidateQueries({
      queryKey: getListCategoryRequestsQueryKey({ status: "pending" }),
    });
    void message.success(text);
    onClose();
  };
  const approve = useApproveCategoryRequest({
    mutation: {
      onSuccess: () => {
        done(t("categories.requests.approved"));
      },
    },
  });
  const reject = useRejectCategoryRequest({
    mutation: {
      onSuccess: () => {
        done(t("categories.requests.rejected"));
      },
    },
  });
  const mutation = action === "approve" ? approve : reject;
  const ready = action === "approve" ? categoryId !== null : reason.trim() !== "";
  const labelId = useId();

  return (
    <ConfirmModal
      open
      title={t(`categories.requests.${action}Title`, { name: row.proposed_name })}
      okLabel={t(`categories.requests.${action}`)}
      danger={action === "reject"}
      loading={mutation.isPending}
      error={mutation.error}
      items={[
        t(`categories.requests.consequence.${action}.status`),
        t(`categories.requests.consequence.${action}.notify`),
        ...(action === "approve" ? [t("categories.requests.consequence.approve.create")] : []),
      ]}
      onOk={() => {
        if (!ready) return;
        if (action === "approve" && categoryId)
          approve.mutate({ id: row.id, data: { category_id: categoryId } });
        if (action === "reject") reject.mutate({ id: row.id, data: { reason: reason.trim() } });
      }}
      onCancel={onClose}
    >
      {action === "approve" ? (
        <div>
          <label htmlFor={labelId} style={{ display: "block", marginBottom: 4 }}>
            {t("categories.requests.pick")}
          </label>
          <Select
            id={labelId}
            style={{ width: "100%" }}
            showSearch
            optionFilterProp="label"
            value={categoryId}
            onChange={setCategoryId}
            loading={categories.isPending}
            options={items.map((c) => ({ value: c.id, label: c.name }))}
          />
          <p className="pf-co-hint">{t("categories.requests.pickHint")}</p>
        </div>
      ) : (
        <div>
          <label htmlFor={labelId} style={{ display: "block", marginBottom: 4 }}>
            {t("categories.requests.reason")}
          </label>
          <Input.TextArea
            id={labelId}
            rows={3}
            value={reason}
            maxLength={1000}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
          {reason.trim() === "" ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 8 }}
              message={t("categories.requests.reasonRequired")}
            />
          ) : null}
        </div>
      )}
    </ConfirmModal>
  );
}
