import { Alert, App, Button, Segmented, Select } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { canEdit } from "../../../app/access";
import { downloadFile } from "../../../shared/api/download";
import type {
  PriceImportJob,
  PriceImportMode,
  PriceImportReport,
  PriceImportRowNote,
  PriceImportStatus,
} from "../../../shared/api/generated/model";
import {
  getDownloadPriceImportTemplateUrl,
  getListCatalogItemsQueryKey,
  getListCatalogSuppliersQueryKey,
  useApplyCheckedPriceImport,
  useGetPriceImport,
  useListCatalogSuppliers,
  useStartPriceImport,
} from "../../../shared/api/generated/platform-bff";
import { DateField } from "../../../shared/ui/DateField";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FileField } from "../../../shared/ui/FileField";
import { FormField } from "../../../shared/ui/FormParts";
import { Sheet } from "../../../shared/ui/Sheet";
import { catalogErrorText } from "./errors";
import { SupplierForm } from "./supplierForms";
import { useDebounced } from "./useDebounced";

const POLL_MS = 1500;
const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPT: Record<PriceImportMode, string> = {
  xlsx: ".xlsx",
  ai: ".xlsx,.pdf,.png,.jpg,.jpeg",
};

/** Состояние загрузки: опрос раз в 1,5 с, пока идёт. */
function useImportStatus(job: PriceImportJob | null) {
  return useGetPriceImport(
    job?.job_id ?? "",
    { mode: job?.mode ?? "xlsx" },
    {
      query: {
        enabled: job !== null,
        refetchInterval: (query) => (query.state.data?.state === "running" ? POLL_MS : false),
      },
    },
  );
}

/**
 * Расчёт · Загрузка прайса поставщика (CAT-1): поставщик → файл → «Проверить» (ничего не пишет) → отчёт → «Применить».
 * Чужие и опубликованные карточки прайс не меняет: расхождения уходят на одобрение в карточку позиции. Второй способ —
 * любой файл (PDF, фото): строки предлагает ИИ, человек проверяет отчёт и применяет ровно эти строки.
 * Эталоны: SAP Ariba catalog upload, Odoo «Import vendor pricelist» (тестовый прогон), 1С «Загрузка прайс-листа».
 */
export function PriceImportPanel() {
  const { t } = useTranslation("catalog");
  const { me } = useAuth();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const suppliers = useListCatalogSuppliers({ ...(q ? { q } : {}), page: 1, page_size: 50 });
  const location = useLocation();
  const [supplier, setSupplier] = useState<{ id: string; name: string } | null>(
    (location.state as { supplier?: { id: string; name: string } } | null)?.supplier ?? null,
  );
  const { mobile } = useViewport();
  const [creating, setCreating] = useState(false);
  // Новый поставщик — формой секциями в боковом окне (§4.1a): окно открывается и закрывается вместе с формой.
  const openCreate = (open: boolean) => {
    setCreating(open);
    // на телефоне форма — лист на весь экран (`Sheet`), боковое окно каркаса не открываем
    if (mobile) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (open) {
          next.set("panel", "open");
          next.set("tab", "card");
        } else {
          next.delete("panel");
          next.delete("tab");
        }
        return next;
      },
      { replace: true },
    );
  };
  const [mode, setMode] = useState<PriceImportMode>("xlsx");
  const [files, setFiles] = useState<File[]>([]);
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [checkJob, setCheckJob] = useState<PriceImportJob | null>(null);
  const [applyJob, setApplyJob] = useState<PriceImportJob | null>(null);
  const ids = {
    supplier: useId(),
    mode: useId(),
    file: useId(),
    from: useId(),
    until: useId(),
    report: useId(),
  };

  // Проверка и применение — две загрузки: отчёт проверки нужен и после «Применить» (ИИ-строки, сравнение).
  const checkStatus = useImportStatus(checkJob);
  const applyStatus = useImportStatus(applyJob);
  const checked = checkStatus.data?.state === "done" ? checkStatus.data.report : null;
  const applied = applyStatus.data?.state === "done" ? applyStatus.data.report : null;
  const result = applyJob ? applyStatus.data : checkStatus.data;
  const report = applied ?? checked;

  const reset = () => {
    setCheckJob(null);
    setApplyJob(null);
  };
  const start = useStartPriceImport({
    mutation: {
      onSuccess: (job, variables) => {
        if (variables.params.check === false) setApplyJob(job);
        else setCheckJob(job);
      },
    },
  });
  const applyChecked = useApplyCheckedPriceImport({ mutation: { onSuccess: setApplyJob } });
  const running = (job: PriceImportJob | null, data: PriceImportStatus | undefined) =>
    job !== null && (data === undefined || data.state === "running");
  const pending =
    start.isPending ||
    applyChecked.isPending ||
    running(checkJob, checkStatus.data) ||
    running(applyJob, applyStatus.data);
  const error = start.error ?? applyChecked.error ?? checkStatus.error ?? applyStatus.error;

  const isApplied = applied !== null;
  useEffect(() => {
    if (!isApplied) return;
    void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListCatalogSuppliersQueryKey() });
  }, [isApplied, queryClient]);

  const file = files[0];
  const ready = supplier !== null && file !== undefined;
  const validity = {
    ...(from ? { valid_from: from } : {}),
    ...(until ? { valid_until: until } : {}),
  };
  const run = (check: boolean) => {
    if (!supplier || !file) return;
    if (!check && mode === "ai" && checked?.rows_token) {
      applyChecked.mutate({
        data: { supplier_id: supplier.id, rows_token: checked.rows_token, ...validity },
      });
      return;
    }
    start.mutate({
      data: { file },
      params: { supplier_id: supplier.id, mode, check, ...validity },
    });
  };

  if (!canEdit(me, "erp.stock")) {
    return <EmptyState title={t("import.noAccess.title")} text={t("import.noAccess.text")} />;
  }

  return (
    <div className="pf-cat pf-cat-import">
      <div className="pf-cat-form">
        <div className="pf-cat-form-row">
          <FormField id={ids.supplier} label={t("import.supplier")}>
            <Select
              id={ids.supplier}
              showSearch
              filterOption={false}
              placeholder={t("import.supplierPlaceholder")}
              value={supplier?.id}
              onSearch={setSearch}
              onChange={(value: string, option) => {
                const label = Array.isArray(option) ? "" : (option?.label ?? "");
                setSupplier({ id: value, name: label });
                reset();
              }}
              options={[
                ...(supplier && !suppliers.data?.items.some((s) => s.id === supplier.id)
                  ? [{ value: supplier.id, label: supplier.name }]
                  : []),
                ...(suppliers.data?.items ?? []).map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          </FormField>
          <div className="pf-cat-import-new">
            <Button
              onClick={() => {
                openCreate(true);
              }}
            >
              {t("import.newSupplier")}
            </Button>
          </div>
        </div>
        <FormField id={ids.mode} label={t("import.mode")} hint={t(`import.modeHint.${mode}`)}>
          <Segmented
            id={ids.mode}
            value={mode}
            onChange={(value) => {
              setMode(value as PriceImportMode);
              setFiles([]);
              reset();
            }}
            options={[
              { value: "xlsx", label: t("import.modes.xlsx") },
              { value: "ai", label: t("import.modes.ai") },
            ]}
          />
        </FormField>
        <FormField id={ids.file} label={t("import.file")}>
          <FileField
            id={ids.file}
            value={files}
            accept={ACCEPT[mode]}
            maxSize={MAX_BYTES}
            onChange={(next) => {
              setFiles(next);
              reset();
            }}
          />
        </FormField>
        <div>
          <Button
            type="link"
            className="pf-cat-linkbtn"
            onClick={() => {
              void downloadFile(getDownloadPriceImportTemplateUrl(), "price-template.xlsx").catch(
                () => {
                  void message.error(t("import.templateError"));
                },
              );
            }}
          >
            {t("import.template")}
          </Button>
        </div>
        <div className="pf-cat-form-row">
          <FormField id={ids.from} label={t("import.validFrom")}>
            <DateField
              id={ids.from}
              value={from}
              onChange={(value) => {
                setFrom(value);
                reset();
              }}
            />
          </FormField>
          <FormField id={ids.until} label={t("import.validUntil")} hint={t("import.validHint")}>
            <DateField
              id={ids.until}
              value={until}
              onChange={(value) => {
                setUntil(value);
                reset();
              }}
            />
          </FormField>
        </div>
        <div className="pf-cat-actions">
          <Button
            type={checked && !isApplied ? "default" : "primary"}
            disabled={!ready || pending}
            loading={pending && !checked}
            onClick={() => {
              reset();
              run(true);
            }}
          >
            {t("import.check")}
          </Button>
          <Button
            type={checked && !isApplied ? "primary" : "default"}
            disabled={!ready || !checked || isApplied || pending}
            loading={pending && checked !== null}
            onClick={() => {
              run(false);
            }}
          >
            {t("import.apply")}
          </Button>
        </div>
        {error ? (
          <Alert type="error" showIcon role="alert" message={catalogErrorText(t, error)} />
        ) : null}
        {result?.state === "failed" ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={t(`import.fileErrors.${result.error ?? "IMPORT_FAILED"}`, {
              defaultValue: t("import.fileErrors.IMPORT_FAILED"),
            })}
          />
        ) : null}
      </div>
      <section aria-live="polite" aria-labelledby={ids.report}>
        {report ? (
          <ImportReport
            id={ids.report}
            report={report}
            onPending={() => {
              setParams({ part: "items", proposals: "pending" });
            }}
          />
        ) : (
          <h2 id={ids.report} className="pf-sr-only">
            {t("import.reportTitle")}
          </h2>
        )}
      </section>
      {creating ? (
        <Sheet
          label={t("supplierForm.addTitle")}
          onClose={() => {
            openCreate(false);
          }}
        >
          <SupplierForm
            onClose={() => {
              openCreate(false);
            }}
            onSaved={(saved) => {
              openCreate(false);
              setSupplier({ id: saved.id, name: saved.name });
              reset();
            }}
          />
        </Sheet>
      ) : null}
    </div>
  );
}

function ImportReport({
  id,
  report,
  onPending,
}: {
  id: string;
  report: PriceImportReport;
  onPending: () => void;
}) {
  const { t } = useTranslation("catalog");
  const stats: [string, number][] = [
    ["itemsCreated", report.items_created],
    ["itemsMatched", report.items_matched],
    ["offersCreated", report.offers_created],
    ["offersUpdated", report.offers_updated],
    ["proposals", report.proposal_count],
    ["errors", report.error_count],
  ];
  return (
    <div className="pf-cat-report">
      <h2 id={id} className="pf-cat-section">
        {report.checked ? t("import.reportChecked") : t("import.reportApplied")}
      </h2>
      {report.ai_used ? <p className="pf-cat-note">{t("import.aiNote")}</p> : null}
      <dl className="pf-cat-stats">
        {stats.map(([key, value]) => (
          <div key={key} className="pf-cat-stat">
            <dt>{t(`import.stats.${key}`)}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {report.unpublishable > 0 ? (
        <p className="pf-cat-note">{t("import.unpublishable", { count: report.unpublishable })}</p>
      ) : null}
      {report.proposals.length > 0 ? (
        <>
          <h3 className="pf-cat-section">{t("import.proposalsTitle")}</h3>
          <p className="pf-cat-note">{t("import.proposalsNote")}</p>
          <div
            className="pf-fp-scroll"
            role="region"
            tabIndex={0}
            aria-label={t("import.proposalsTitle")}
          >
            <table className="pf-cat-offers">
              <caption className="pf-sr-only">{t("import.proposalsTitle")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("import.row")}</th>
                  <th scope="col">{t("import.item")}</th>
                  <th scope="col">{t("import.field")}</th>
                  <th scope="col">{t("proposals.current")}</th>
                  <th scope="col">{t("proposals.proposed")}</th>
                </tr>
              </thead>
              <tbody>
                {report.proposals.map((p) => (
                  <tr key={`${String(p.row)}-${p.field}`}>
                    <td className="pf-col-num">{p.row}</td>
                    <td>{p.product_name}</td>
                    <td>{t(`proposalField.${p.field}`)}</td>
                    <td>{p.current || "—"}</td>
                    <td>{p.proposed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!report.checked ? (
            <Button className="pf-cat-linkbtn" type="link" onClick={onPending}>
              {t("import.openPending")}
            </Button>
          ) : null}
        </>
      ) : null}
      <RowNotes title={t("import.errorsTitle")} notes={report.errors} total={report.error_count} />
      <RowNotes
        title={t("import.warningsTitle")}
        notes={report.warnings}
        total={report.warning_count}
      />
    </div>
  );
}

function RowNotes({
  title,
  notes,
  total,
}: {
  title: string;
  notes: PriceImportRowNote[];
  total: number;
}) {
  const { t } = useTranslation("catalog");
  if (notes.length === 0) return null;
  return (
    <>
      <h3 className="pf-cat-section">{title}</h3>
      {total > notes.length ? (
        <p className="pf-cat-note">{t("import.shown", { shown: notes.length, total })}</p>
      ) : null}
      <div className="pf-fp-scroll" role="region" tabIndex={0} aria-label={title}>
        <table className="pf-cat-offers">
          <caption className="pf-sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">{t("import.row")}</th>
              <th scope="col">{t("import.reason")}</th>
            </tr>
          </thead>
          <tbody>
            {notes.map((note) => (
              <tr key={`${String(note.row)}-${note.code}`}>
                <td className="pf-col-num">{note.row}</td>
                <td>
                  {t(`import.codes.${note.code}`, {
                    value: note.value,
                    defaultValue: t("import.codes.DEFAULT", { value: note.value }),
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
