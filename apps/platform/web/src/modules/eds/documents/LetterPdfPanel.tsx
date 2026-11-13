import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Skeleton } from "antd";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { downloadFile } from "../../../shared/api/download";
import { ApiError } from "../../../shared/api/errors";
import type { EdsDocumentPdf } from "../../../shared/api/generated/model";
import {
  getDownloadEdsDocumentPdfQueryKey,
  getDownloadEdsDocumentPdfUrl,
  getGetEdsDocumentPdfQueryKey,
  requestEdsDocumentPdf,
  useGetEdsDocumentPdf,
} from "../../../shared/api/generated/platform-bff";
import { reasonText } from "./errors";

const PdfViewer = lazy(() => import("../../../shared/ui/PdfViewer"));

/** Опрос состояния PDF, пока воркер EDS его строит (B-094: рендер только в фоне). */
const POLL_MS = 1500;

function usePdfBytes(id: string | null, pdf: EdsDocumentPdf | undefined) {
  const client = useQueryClient();
  const ready = pdf?.status === "ready";
  const queryKey = getDownloadEdsDocumentPdfQueryKey(id ?? "");
  const version = `${pdf?.requested_at ?? ""}:${String(pdf?.final ?? false)}`;
  const seen = useRef(version);
  useEffect(() => {
    // Новый PDF (правки, регистрация) загружается заново, когда готов; пока он строится, на экране остаются прежние
    // страницы с пометкой «Обновляется» (пункт «Ш»: страницы от сервера без мигания).
    if (ready && seen.current !== version) {
      seen.current = version;
      void client.invalidateQueries({ queryKey });
    }
  }, [client, queryKey, ready, version]);
  return useQuery({
    enabled: Boolean(id) && ready,
    queryKey,
    staleTime: Infinity,
    gcTime: 0,
    queryFn: async (): Promise<ArrayBuffer> => {
      const response = await fetch(getDownloadEdsDocumentPdfUrl(id ?? ""), {
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new ApiError(response.status, "HTTP_ERROR", `HTTP ${String(response.status)}`);
      }
      return response.arrayBuffer();
    },
  });
}

export interface LetterPdfPanelProps {
  /** Сохранённый документ; `null` — форма ещё не сохранялась (тогда `prepare` создаст черновик) */
  documentId: string | null;
  /** Последний PDF из карточки документа: открыть без нового запроса */
  initial?: EdsDocumentPdf | null;
  /** Перед запросом PDF сохранить черновик формы; `null` — не сохранено (ошибку показала форма) */
  prepare?: () => Promise<string | null>;
  /** Можно ли запросить PDF (автор или делопроизводитель); иначе только показ готового */
  canBuild: boolean;
  subject: string;
  /** Уровень заголовка блока: 2 — на странице формы, 4 — в карточке документа */
  headingLevel?: 2 | 4;
  /**
   * Страницы строятся сами (пункт «Ш», ADR-0020 п. 4): через секунду после паузы в наборе — сохранить черновик и построить
   * PDF. `key` меняется с каждой правкой; `prepare` молча возвращает `null`, если форма ещё не заполнена.
   */
  auto?: { key: string; prepare: () => Promise<string | null> };
}

/** Пауза в наборе перед автоматическим построением страниц, мс */
export const AUTO_BUILD_MS = 1000;

/**
 * PDF письма на бланке (P4): «Показать PDF» → (сохранить черновик) → EDS ставит рендер в фоновый воркер → опрос до «готов»
 * или «ошибка с причиной» → страницы рисуются pdf.js (CSP Платформы запрещает встроенный просмотрщик). Тот же файл —
 * «Скачать PDF» и вложение письма адресату.
 */
export function LetterPdfPanel({
  documentId,
  initial,
  prepare,
  canBuild,
  subject,
  headingLevel = 2,
  auto,
}: LetterPdfPanelProps) {
  const Heading = headingLevel === 2 ? "h2" : "h4";
  const { t } = useTranslation("documents");
  const client = useQueryClient();
  const [id, setId] = useState<string | null>(documentId);
  const [requesting, setRequesting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [started, setStarted] = useState(Boolean(initial));
  const current = id ?? documentId;
  const status = useGetEdsDocumentPdf(current ?? "", {
    query: {
      enabled: Boolean(current) && started,
      ...(initial ? { initialData: initial } : {}),
      refetchInterval: (query) => (query.state.data?.status === "pending" ? POLL_MS : false),
    },
  });
  const pdf = status.data;
  const bytes = usePdfBytes(current, pdf);
  const name = t("preview.name", { subject: subject || "—" });

  const busy = useRef(false);
  const again = useRef(false);
  const build = async (quiet = false) => {
    if (busy.current) {
      again.current = true;
      return;
    }
    busy.current = true;
    setRequestError(null);
    setRequesting(true);
    try {
      const make = quiet ? autoRef.current?.prepare : prepare;
      const target = make ? await make() : current;
      if (!target) return;
      setId(target);
      const result = await requestEdsDocumentPdf(target);
      client.setQueryData(getGetEdsDocumentPdfQueryKey(target), result);
      setStarted(true);
    } catch (error) {
      setRequestError(t("preview.requestFailed", { reason: reasonText(t, error) }));
    } finally {
      busy.current = false;
      setRequesting(false);
      // Пока строился PDF, текст снова поменялся — строим ещё раз по последней версии.
      if (again.current) {
        again.current = false;
        void build(true);
      }
    }
  };

  const autoRef = useRef(auto);
  useEffect(() => {
    autoRef.current = auto;
  });
  // Открытый черновик с готовым PDF не перестраивается, пока его не правили.
  const builtKey = useRef(initial ? auto?.key : undefined);
  const autoKey = auto?.key;
  useEffect(() => {
    if (autoKey === undefined || autoKey === builtKey.current) return;
    const timer = window.setTimeout(() => {
      builtKey.current = autoKey;
      void build(true);
    }, AUTO_BUILD_MS);
    return () => {
      window.clearTimeout(timer);
    };
    // build — свежая функция на каждой отрисовке; запуск — только по смене текста
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoKey]);

  const stateLine = (() => {
    if (!pdf) return requesting ? <p role="status">{t("preview.pending")}</p> : null;
    if (pdf.status === "pending" || requesting || (bytes.isFetching && bytes.data)) {
      return <p role="status">{t(bytes.data ? "preview.updating" : "preview.pending")}</p>;
    }
    if (pdf.status === "failed") {
      return (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={
            pdf.error ? t("preview.failed", { error: pdf.error }) : t("preview.failedNoReason")
          }
        />
      );
    }
    return (
      <p role="status">
        {t(pdf.final ? "preview.readyFinal" : "preview.ready", { pages: pdf.pages ?? 1 })}
      </p>
    );
  })();

  return (
    <section className="pf-letter-pdf" aria-label={t("preview.title")}>
      <div className="pf-letter-pdf-head">
        <Heading className="pf-letter-pdf-title">{t("preview.title")}</Heading>
        <div className="pf-fp-row">
          {canBuild && !auto ? (
            <Button
              loading={requesting}
              disabled={pdf?.status === "pending"}
              onClick={() => {
                void build();
              }}
            >
              {pdf?.status === "failed"
                ? t("preview.retry")
                : pdf
                  ? t("preview.refresh")
                  : t("preview.show")}
            </Button>
          ) : null}
          {pdf?.status === "ready" && current ? (
            <Button
              type="link"
              onClick={() => {
                void downloadFile(getDownloadEdsDocumentPdfUrl(current), `${name}.pdf`).catch(
                  (error: unknown) => {
                    setRequestError(t("preview.requestFailed", { reason: reasonText(t, error) }));
                  },
                );
              }}
            >
              {t("preview.download")}
            </Button>
          ) : null}
        </div>
      </div>
      <p className="pf-hint">
        {pdf ? t("preview.hint") : t(auto ? "preview.emptyAuto" : "preview.empty")}
      </p>
      {requestError ? <Alert type="error" showIcon role="alert" message={requestError} /> : null}
      {stateLine}
      {pdf?.status === "ready" || (pdf?.status === "pending" && bytes.data) ? (
        // Ошибка — только когда показать нечего: перезапрос, попавший на стройку нового PDF, оставляет прежние страницы.
        bytes.isError && !bytes.data ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={t("preview.loadFailed")}
            action={
              <Button
                size="small"
                onClick={() => {
                  void bytes.refetch();
                }}
              >
                {t("preview.retry")}
              </Button>
            }
          />
        ) : bytes.data ? (
          <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} title={false} />}>
            <PdfViewer data={bytes.data} name={name} />
          </Suspense>
        ) : (
          <Skeleton active paragraph={{ rows: 6 }} title={false} />
        )
      ) : null}
    </section>
  );
}
