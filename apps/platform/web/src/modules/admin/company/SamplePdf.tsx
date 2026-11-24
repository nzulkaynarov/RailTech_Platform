import { useQuery } from "@tanstack/react-query";
import { Segmented } from "antd";
import { Suspense, lazy, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type {
  DocumentSampleIn,
  DocumentSampleInLanguage,
} from "../../../shared/api/generated/model";
import {
  getDownloadDocumentSampleQueryKey,
  getDownloadDocumentSampleUrl,
  requestDocumentSample,
  useGetDocumentSample,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { companyErrorText } from "./errors";

const PdfViewer = lazy(() => import("../../../shared/ui/PdfViewer"));

const LANGUAGES: DocumentSampleInLanguage[] = ["ru", "en", "uz"];
const DEBOUNCE_MS = 400;
const POLL_MS = 1000;

function uiLanguage(language: string): DocumentSampleInLanguage {
  const base = language.slice(0, 2);
  return LANGUAGES.find((value) => value === base) ?? "ru";
}

/**
 * Образец документа — настоящий PDF (ДОК-14): тот же генератор, что печатает рабочий документ, на бланке компании
 * (несохранённые правки уходят в запрос), с следующим номером схемы и на выбранном языке. Запрос — после паузы ввода,
 * опрос, пока воркер строит; прежние страницы остаются на экране, пока готовятся новые. Просмотрщик — общий `PdfViewer`.
 */
export function SamplePdf({
  request,
  title,
  onWarnings,
}: {
  /** Что показать: вид бланка либо вид и текст шаблона; язык подставляет сам образец */
  request: Omit<DocumentSampleIn, "language">;
  title: string;
  /** Подстановки текста, которых нет в каталоге, — когда образец готов */
  onWarnings?: (codes: string[]) => void;
}) {
  const { t, i18n } = useTranslation("company");
  const [language, setLanguage] = useState<DocumentSampleInLanguage>(uiLanguage(i18n.language));
  const [id, setId] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const key = JSON.stringify({ ...request, language });

  useEffect(() => {
    // Ответ на устаревший запрос (правка успела смениться) не показывается: позже ушедший запрос всегда новее.
    let stale = false;
    const timer = window.setTimeout(() => {
      requestDocumentSample(JSON.parse(key) as DocumentSampleIn)
        .then((answer) => {
          if (stale) return;
          setFailed(null);
          setId(answer.id);
        })
        .catch((error: unknown) => {
          if (!stale) setFailed(companyErrorText(t, error));
        });
    }, DEBOUNCE_MS);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [key, t]);

  const state = useGetDocumentSample(id ?? "", {
    query: {
      enabled: Boolean(id),
      refetchInterval: (query) => (query.state.data?.status === "pending" ? POLL_MS : false),
    },
  });
  const ready = state.data?.status === "ready";
  const bytes = useQuery({
    enabled: Boolean(id) && ready,
    queryKey: getDownloadDocumentSampleQueryKey(id ?? ""),
    staleTime: Infinity,
    queryFn: async (): Promise<ArrayBuffer> => {
      const response = await fetch(getDownloadDocumentSampleUrl(id ?? ""), {
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new ApiError(response.status, "HTTP_ERROR", `HTTP ${String(response.status)}`);
      }
      return response.arrayBuffer();
    },
  });

  // Пока строится новый образец, на экране прежний.
  const [shown, setShown] = useState<ArrayBuffer | null>(null);
  if (bytes.data && bytes.data !== shown) setShown(bytes.data);

  const warnings = ready ? state.data?.warnings : undefined;
  const warningsKey = (warnings ?? []).join("|");
  useEffect(() => {
    if (ready) onWarnings?.(warningsKey === "" ? [] : warningsKey.split("|"));
  }, [ready, warningsKey, onWarnings]);

  const error = failed ?? (state.data?.status === "failed" ? t("sample.failed") : null);
  const pending = Boolean(id) && !ready && state.data?.status !== "failed";
  return (
    <div className="pf-co-sample">
      <Segmented<DocumentSampleInLanguage>
        aria-label={t("sample.language")}
        size="small"
        value={language}
        onChange={setLanguage}
        options={LANGUAGES.map((value) => ({ value, label: value.toUpperCase() }))}
      />
      <div aria-busy={pending ? "true" : "false"}>
        {error ? <ErrorNote message={error} /> : null}
        {shown ? (
          <Suspense fallback={null}>
            <PdfViewer data={shown} name={title} />
          </Suspense>
        ) : (
          <div className="pf-co-preview">
            <p className="pf-co-hint pf-co-preview-empty" role="status">
              {error ? t("preview.empty") : t("preview.loading")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
