import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import "./pdf-viewer.css";

GlobalWorkerOptions.workerSrc = workerUrl;

/** Предел страниц, которые рисуются сразу (длинные документы скачивают). */
const MAX_PAGES = 40;
/** Предел плотности холста: экран 2× рисуется вдвое плотнее, выше 3× разница не видна, а память растёт. */
const MAX_PIXEL_RATIO = 3;
/** Перерисовка после изменения ширины панели — не на каждый кадр перетаскивания. */
const RESIZE_DELAY_MS = 150;

/**
 * Просмотр PDF в Платформе (D2-3, общий с P4 — предпросмотр письма на бланке): страницы рисуются в `canvas` из полученных
 * байт. Встроенный просмотрщик браузера (`iframe`, `object`) запрещён политикой CSP Платформы (`object-src 'none'`), а файл
 * BFF отдаёт только вложением, поэтому чужой код в странице не исполняется. Модуль грузится лениво (`lazy`) — вместе с
 * первым открытием PDF.
 *
 * Чёткость: холст рисуется в физических пикселях экрана (`devicePixelRatio`), а на странице занимает ширину панели в CSS-
 * пикселях. Иначе на экране 2× браузер растягивает картинку вдвое, и документ выглядит размытым, как скан. При изменении
 * ширины панели страницы перерисовываются под новую ширину.
 */
export default function PdfViewer({ data, name }: { data: ArrayBuffer; name: string }) {
  const { t } = useTranslation("ui");
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ pages: number; shown: number } | "error" | null>(null);

  useEffect(() => {
    const container = host.current;
    if (!container) return;
    const task = getDocument({
      data: new Uint8Array(data.slice(0)),
      isEvalSupported: false,
    });
    let pdf: PDFDocumentProxy | null = null;
    let run = { cancelled: false };
    let drawnWidth = 0;

    const draw = async (current: { cancelled: boolean }) => {
      if (!pdf) return;
      const width = Math.max(240, container.clientWidth - 18);
      drawnWidth = container.clientWidth;
      const ratio = Math.min(MAX_PIXEL_RATIO, Math.max(1, window.devicePixelRatio || 1));
      const shown = Math.min(pdf.numPages, MAX_PAGES);
      const canvases: HTMLCanvasElement[] = [];
      for (let number = 1; number <= shown; number += 1) {
        if (current.cancelled) return;
        const page = await pdf.getPage(number);
        const base = page.getViewport({ scale: 1 });
        const scale = width / base.width;
        const viewport = page.getViewport({ scale: scale * ratio });
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${String(Math.floor(base.width * scale))}px`;
        canvas.setAttribute("role", "img");
        canvas.setAttribute(
          "aria-label",
          t("pdfViewer.page", { name, page: number, total: pdf.numPages }),
        );
        const context = canvas.getContext("2d");
        if (!context) throw new Error("canvas");
        await page.render({ canvasContext: context, viewport }).promise;
        canvases.push(canvas);
      }
      // прежние страницы остаются на экране, пока готовятся новые: без мигания при перерисовке
      if (!current.cancelled) {
        container.replaceChildren(...canvases);
        setState({ pages: pdf.numPages, shown });
      }
    };

    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (!pdf || Math.abs(container.clientWidth - drawnWidth) < 2) return;
            clearTimeout(timer);
            timer = setTimeout(() => {
              run.cancelled = true;
              run = { cancelled: false };
              const next = run;
              void draw(next).catch(() => {
                if (!next.cancelled) setState("error");
              });
            }, RESIZE_DELAY_MS);
          });

    container.replaceChildren();
    void (async () => {
      try {
        pdf = await task.promise;
        await draw(run);
        observer?.observe(container);
      } catch {
        if (!run.cancelled) setState("error");
      }
    })();
    return () => {
      run.cancelled = true;
      clearTimeout(timer);
      observer?.disconnect();
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
