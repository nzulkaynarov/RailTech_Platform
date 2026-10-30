import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Drawer, Input, Select, Skeleton } from "antd";
import type { TFunction } from "i18next";
import { Suspense, lazy, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { downloadFile } from "../../../shared/api/download";
import { ApiError } from "../../../shared/api/errors";
import type { TechDoc, TechDocKind } from "../../../shared/api/generated/model";
import {
  getDownloadTechDocQueryKey,
  getDownloadTechDocUrl,
  getListCatalogItemsQueryKey,
  getListTechDocsQueryKey,
  useDeleteTechDoc,
  useListCatalogItems,
  useListTechDocDealOptions,
  useListTechDocs,
  useUploadTechDoc,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormModal, PAGE_SIZE, Pager } from "../catalog/common";
import { useDebounced } from "../catalog/useDebounced";
import { errorFields } from "../catalog/errors";
import { queryLabels } from "../catalog/labels";

import "../catalog/catalog.css";

const PdfViewer = lazy(() => import("./PdfViewer"));

const KINDS: readonly TechDocKind[] = ["tz", "drawing", "certificate", "pnr", "other"];
const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx";

function sizeLabel(t: TFunction, bytes: number, language: string): string {
  const mb = bytes / (1024 * 1024);
  const kb = bytes / 1024;
  const fmt = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
  return mb >= 1
    ? t("docs.size.mb", { value: fmt.format(mb) })
    : t("docs.size.kb", { value: fmt.format(Math.max(kb, 0.1)) });
}

/**
 * Расчёт · Техдокументация (`/erp/docs`, SPEC-v3 §7.4, B-019 часть «ERP · Документация», D2-3): ТЗ, чертежи, сертификаты
 * и регламенты ПНР с привязкой к позиции номенклатуры и заявке, загрузка (до 20 МБ), просмотр PDF и изображений, скачивание.
 * «Отправить клиенту в чат» появится вместе с разделом «Чаты» (D3): кнопки нет, в карточке сказано словами.
 */
export function DocsScreen() {
  const { t, i18n } = useTranslation(["catalog", "modules"]);
  useDocumentTitle(t("modules:erp.sections.docs"));
  const { date } = useFormat();
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<TechDocKind | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);
  const q = useDebounced(text.trim());
  const searchId = useId();
  const kindId = useId();
  const productFilter = params.get("product_id");
  const dealFilter = params.get("deal_id");
  const opened = params.get("doc");
  const query = useListTechDocs({
    ...(q ? { q } : {}),
    ...(kind ? { kind } : {}),
    ...(productFilter ? { product_id: productFilter } : {}),
    ...(dealFilter ? { deal_id: dealFilter } : {}),
    page,
    page_size: PAGE_SIZE,
  });
  const setDoc = (id: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("doc", id);
        else next.delete("doc");
        return next;
      },
      { replace: true },
    );
  };
  const clearLinks = () => {
    setParams({}, { replace: true });
  };
  const columns: Column<TechDoc>[] = [
    {
      key: "title",
      title: t("catalog:docs.columns.title"),
      render: (row) => (
        <>
          <Button
            type="link"
            className="pf-cat-linkbtn"
            aria-label={t("catalog:docs.open", { title: row.title })}
            aria-current={opened === row.id ? "true" : undefined}
            onClick={() => {
              setDoc(row.id);
            }}
          >
            {row.title}
          </Button>
          <span className="pf-cat-sub">{row.original_name}</span>
        </>
      ),
    },
    {
      key: "kind",
      title: t("catalog:docs.columns.kind"),
      render: (row) => <StatusTag tone="blue">{t(`catalog:docKinds.${row.kind}`)}</StatusTag>,
    },
    {
      key: "link",
      title: t("catalog:docs.columns.link"),
      render: (row) => (
        <>
          {row.product ? (
            <Link className="pf-focusable" to={`/erp/catalog?part=items&item=${row.product.id}`}>
              {row.product.name}
            </Link>
          ) : null}
          {row.deal ? (
            <span className="pf-cat-sub">
              {row.deal.number} · {row.deal.title}
            </span>
          ) : null}
          {!row.product && !row.deal ? "—" : null}
        </>
      ),
    },
    {
      key: "size",
      title: t("catalog:docs.columns.size"),
      num: true,
      render: (row) => sizeLabel(t, row.size_bytes, i18n.language),
    },
    {
      key: "who",
      title: t("catalog:docs.columns.uploaded"),
      render: (row) => (
        <>
          {row.uploaded_by ?? "—"}
          <span className="pf-cat-sub">{date(row.created_at)}</span>
        </>
      ),
    },
  ];
  return (
    <div className="pf-cat">
      <PageHeader title={t("modules:erp.sections.docs")} subtitle={t("catalog:docs.subtitle")} />
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={searchId}>{t("catalog:docs.search")}</label>
          <Input
            id={searchId}
            type="search"
            allowClear
            value={text}
            style={{ width: 280 }}
            onChange={(event) => {
              setText(event.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="pf-cat-control">
          <label htmlFor={kindId}>{t("catalog:docs.filterKind")}</label>
          <Select
            id={kindId}
            allowClear
            placeholder={t("catalog:docs.anyKind")}
            style={{ width: 220 }}
            value={kind}
            onChange={(value: TechDocKind | undefined) => {
              setKind(value);
              setPage(1);
            }}
            options={KINDS.map((k) => ({ value: k, label: t(`catalog:docKinds.${k}`) }))}
          />
        </div>
        {productFilter || dealFilter ? (
          <Button onClick={clearLinks}>{t("catalog:docs.clearLinks")}</Button>
        ) : null}
        <span className="pf-cat-spacer" />
        {canEdit(me, "erp.stock") ? (
          <Button
            type="primary"
            onClick={() => {
              setUploading(true);
            }}
          >
            {t("catalog:docs.upload")}
          </Button>
        ) : null}
      </div>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("catalog:docs.empty.title")}
              text={
                q || kind || productFilter || dealFilter
                  ? t("catalog:docs.empty.filtered")
                  : t("catalog:docs.empty.text")
              }
            />
          ) : (
            <>
              <DataList
                label={t("catalog:docs.table")}
                rows={data.items}
                columns={columns}
                rowKey={(row) => row.id}
                selectedKey={opened}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {opened ? (
        <DocDrawer
          id={opened}
          docs={query.data?.items ?? []}
          onClose={() => {
            setDoc(null);
          }}
        />
      ) : null}
      {uploading ? (
        <UploadForm
          {...(productFilter ? { productId: productFilter } : {})}
          {...(dealFilter ? { dealId: dealFilter } : {})}
          onClose={() => {
            setUploading(false);
          }}
        />
      ) : null}
    </div>
  );
}

function useFileBytes(id: string, enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: getDownloadTechDocQueryKey(id),
    staleTime: 60_000,
    queryFn: async (): Promise<{ data: ArrayBuffer; type: string }> => {
      const response = await fetch(getDownloadTechDocUrl(id), { credentials: "same-origin" });
      if (!response.ok) {
        throw new ApiError(response.status, "HTTP_ERROR", `HTTP ${String(response.status)}`);
      }
      return {
        data: await response.arrayBuffer(),
        type: response.headers.get("content-type") ?? "",
      };
    },
  });
}

function DocDrawer({
  id,
  docs,
  onClose,
}: {
  id: string;
  docs: readonly TechDoc[];
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const { mobile } = useViewport();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const doc = docs.find((d) => d.id === id);
  const bytes = useFileBytes(id, doc?.previewable === true);
  const remove = useDeleteTechDoc({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListTechDocsQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
        void message.success(t("docs.deleted"));
        onClose();
      },
    },
  });
  const [confirming, setConfirming] = useState(false);
  const download = () => {
    void downloadFile(getDownloadTechDocUrl(id), doc?.original_name ?? "file").catch(() => {
      void message.error(t("docs.downloadError"));
    });
  };
  return (
    <Drawer
      open
      width={mobile ? "100%" : 760}
      onClose={onClose}
      title={doc?.title ?? t("docs.card")}
    >
      {!doc ? (
        <EmptyState level={3} compact title={t("docs.gone.title")} text={t("docs.gone.text")} />
      ) : (
        <div className="pf-cat">
          <DefinitionList
            items={[
              { label: t("docs.fields.kind"), value: t(`docKinds.${doc.kind}`) },
              {
                label: t("docs.fields.file"),
                value: `${doc.original_name} · ${sizeLabel(t, doc.size_bytes, i18n.language)}`,
              },
              {
                label: t("docs.fields.product"),
                value: doc.product ? (
                  <Link
                    className="pf-focusable"
                    to={`/erp/catalog?part=items&item=${doc.product.id}`}
                  >
                    {doc.product.name}
                  </Link>
                ) : undefined,
              },
              {
                label: t("docs.fields.deal"),
                value: doc.deal ? `${doc.deal.number} · ${doc.deal.title}` : undefined,
              },
              {
                label: t("docs.fields.uploaded"),
                value: `${doc.uploaded_by ?? "—"}, ${date(doc.created_at)}`,
              },
            ]}
          />
          <div className="pf-cat-actions">
            <Button type="primary" onClick={download}>
              {t("docs.download")}
            </Button>
            {canEdit(me, "erp.stock") ? (
              <Button
                danger
                onClick={() => {
                  setConfirming(true);
                }}
              >
                {t("docs.delete")}
              </Button>
            ) : null}
          </div>
          <p className="pf-cat-note">{t("docs.chatLater")}</p>
          <h3 className="pf-cat-section">{t("docs.preview")}</h3>
          {!doc.previewable ? (
            <p className="pf-cat-note">{t("docs.noPreview")}</p>
          ) : (
            <QueryState query={bytes} labels={queryLabels(t)} level={3} compact>
              {(file) =>
                doc.content_type === "application/pdf" ? (
                  <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} title={false} />}>
                    <PdfViewer data={file.data} name={doc.title} />
                  </Suspense>
                ) : (
                  <ImagePreview data={file.data} type={doc.content_type} name={doc.title} />
                )
              }
            </QueryState>
          )}
          {confirming ? (
            <FormModal
              title={t("docs.deleteTitle", { title: doc.title })}
              okLabel={t("docs.delete")}
              items={t("docs.deleteSteps", { returnObjects: true }) as string[]}
              loading={remove.isPending}
              error={remove.error}
              onOk={() => {
                remove.mutate({ id });
              }}
              onCancel={() => {
                setConfirming(false);
              }}
            >
              <p className="pf-cat-note">{t("docs.deleteText")}</p>
            </FormModal>
          ) : null}
        </div>
      )}
    </Drawer>
  );
}

function ImagePreview({ data, type, name }: { data: ArrayBuffer; type: string; name: string }) {
  const img = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const objectUrl = URL.createObjectURL(new Blob([data], { type }));
    const element = img.current;
    if (element) element.src = objectUrl;
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [data, type]);
  return <img ref={img} className="pf-doc-viewer-image" alt={name} />;
}

function UploadForm({
  productId,
  dealId,
  onClose,
}: {
  productId?: string;
  dealId?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<TechDocKind>("tz");
  const [title, setTitle] = useState("");
  const [product, setProduct] = useState<string | undefined>(productId);
  const [deal, setDeal] = useState<string | undefined>(dealId);
  const [productQuery, setProductQuery] = useState("");
  const [dealQuery, setDealQuery] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const products = useListCatalogItems({
    ...(productQuery.trim() ? { q: productQuery.trim() } : {}),
    page_size: 20,
  });
  const deals = useListTechDocDealOptions(dealQuery.trim() ? { q: dealQuery.trim() } : {});
  const ids = { file: useId(), kind: useId(), title: useId(), product: useId(), deal: useId() };
  const mutation = useUploadTechDoc({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListTechDocsQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  const pick = (selected: File | null) => {
    setProblem(null);
    if (selected && selected.size > MAX_BYTES) {
      setProblem(t("errors.reason.file_too_large"));
      setFile(null);
      return;
    }
    if (selected && !ACCEPT.split(",").some((ext) => selected.name.toLowerCase().endsWith(ext))) {
      setProblem(t("errors.reason.file_type_not_allowed"));
      setFile(null);
      return;
    }
    setFile(selected);
    if (selected && title === "") setTitle(selected.name.replace(/\.[^.]+$/, ""));
  };
  return (
    <FormModal
      title={t("docs.form.title")}
      okLabel={t("docs.form.ok")}
      items={t("docs.form.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={file === null || (!product && !deal)}
      onOk={() => {
        if (!file) return;
        mutation.mutate({
          data: {
            file,
            kind,
            ...(title.trim() ? { title: title.trim() } : {}),
            ...(product ? { product_id: product } : {}),
            ...(deal ? { deal_id: deal } : {}),
          },
        });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.file} label={t("docs.form.file")} hint={t("docs.form.fileHint")}>
        <input
          id={ids.file}
          type="file"
          accept={ACCEPT}
          aria-invalid={fields.includes("file") || problem !== null}
          onChange={(event) => {
            pick(event.target.files?.[0] ?? null);
          }}
        />
      </FormField>
      {problem ? (
        <p className="pf-cat-note" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="pf-cat-form-row">
        <FormField id={ids.kind} label={t("docs.form.kind")}>
          <Select
            id={ids.kind}
            value={kind}
            onChange={setKind}
            options={KINDS.map((k) => ({ value: k, label: t(`docKinds.${k}`) }))}
          />
        </FormField>
        <FormField id={ids.title} label={t("docs.form.name")}>
          <Input
            id={ids.title}
            value={title}
            maxLength={255}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.product} label={t("docs.form.product")} hint={t("docs.form.linkHint")}>
        <Select
          id={ids.product}
          allowClear
          showSearch
          filterOption={false}
          placeholder={t("docs.form.productPlaceholder")}
          value={product}
          status={fields.includes("product_id") ? "error" : undefined}
          onSearch={setProductQuery}
          onChange={(value: string | undefined) => {
            setProduct(value);
          }}
          options={(products.data?.items ?? []).map((i) => ({
            value: i.id,
            label: `${i.name} · ${i.sku}`,
          }))}
        />
      </FormField>
      <FormField id={ids.deal} label={t("docs.form.deal")}>
        <Select
          id={ids.deal}
          allowClear
          showSearch
          filterOption={false}
          placeholder={t("docs.form.dealPlaceholder")}
          value={deal}
          onSearch={setDealQuery}
          onChange={(value: string | undefined) => {
            setDeal(value);
          }}
          options={(deals.data?.items ?? []).map((d) => ({
            value: String(d.erp_deal_id),
            label: `${d.number} · ${d.title}`,
          }))}
        />
      </FormField>
    </FormModal>
  );
}
