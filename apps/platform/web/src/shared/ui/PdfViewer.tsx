import { GlobalWorkerOptions, getDocument } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import "./pdf-viewer.css";

GlobalWorkerOptions.workerSrc = workerUrl;

/** Предел страниц, которые рисуются сразу (длинные документы скачивают). */
const MAX_PAGES = 40;

/**
 * Просмотр PDF в Платформе (D2-3, общий с P4 — предпросмотр письма на бланке): страницы рисуются в `canvas` из полученных
 * байт. Встроенный просмотрщик браузера (`iframe`, `object`) запрещён политикой CSP Платформы (`object-src 'none'`), а файл
 * BFF отдаёт только вложением, поэтому чужой код в странице не исполняется. Модуль грузится лениво (`lazy`) — вместе с
 * первым открытием PDF.
 */
export default function PdfViewer({ data, name }: { data: ArrayBuffer; name: string }) {
  const { t } = useTranslation("ui");
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ pages: number; shown: number } | "error" | null>(null);

  useEffect(() => {
    const run = { cancelled: false };
    const container = host.current;
    if (!container) return;
    container.replaceChildren();
    const task = getDocument({
      data: new Uint8Array(data.slice(0)),
      isEvalSupported: false,
    });
    void (async () => {
      try {
        const pdf = await task.promise;
        const shown = Math.min(pdf.numPages, MAX_PAGES);
        for (let number = 1; number <= shown; number += 1) {
          if (run.cancelled) return;
          const page = await pdf.getPage(number);
          const base = page.getViewport({ scale: 1 });
          const width = Math.max(240, container.clientWidth - 18);
          const viewport = page.getViewport({ scale: Math.min(1.6, width / base.width) });
          const canvas = document.createElement("canvas");
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.setAttribute("role", "img");
          canvas.setAttribute(
            "aria-label",
            t("pdfViewer.page", { name, page: number, total: pdf.numPages }),
          );
          const context = canvas.getContext("2d");
          if (!context) throw new Error("canvas");
          container.appendChild(canvas);
          await page.render({ canvasContext: context, viewport }).promise;
        }
        if (!run.cancelled) setState({ pages: pdf.numPages, shown });
      } catch {
        if (!run.cancelled) setState("error");
      }
    })();
    return () => {
      run.cancelled = true;
      void task.destroy();
    };
  }, [data, name, t]);

  return (
    <div className="pf-doc-viewer">
      <div
        ref={host}
        className="pf-doc-viewer-pages"
        role="region"
        tabIndex={0}
        aria-label={t("pdfViewer.region", { name })}
        data-testid="pdf-pages"
      />
      {state === "error" ? (
        <p className="pf-hint" role="alert">
          {t("pdfViewer.error")}
        </p>
      ) : null}
      {state !== null && state !== "error" && state.pages > state.shown ? (
        <p className="pf-hint">
          {t("pdfViewer.truncated", { shown: state.shown, total: state.pages })}
        </p>
      ) : null}
    </div>
  );
}
