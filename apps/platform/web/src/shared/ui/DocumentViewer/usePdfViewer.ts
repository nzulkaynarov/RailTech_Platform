import {
  AnnotationMode,
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentProxy,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  EventBus,
  PDFFindController,
  PDFLinkService,
  PDFViewer,
} from "pdfjs-dist/web/pdf_viewer.mjs";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { ViewerApi } from "./types";
import "pdfjs-dist/web/pdf_viewer.css";

GlobalWorkerOptions.workerSrc = workerUrl;

/** Перерисовка после смены ширины панели — не на каждый кадр перетаскивания. */
const RESIZE_DELAY_MS = 150;

interface Match {
  current: number;
  total: number;
}

export interface PdfViewerHandle {
  api: ViewerApi;
  /** Открытый документ — для миниатюр */
  pdf: PDFDocumentProxy | null;
}

/**
 * Готовые части pdf.js (`PDFViewer`, `EventBus`, `PDFFindController`, `PDFLinkService`): страницы рисуются по мере
 * прокрутки (предела на число страниц нет), поверх холста — текстовый слой для выделения, копирования и поиска.
 * Встроенный просмотрщик браузера (`iframe`, `object`) запрещён CSP Платформы (`object-src 'none'`), `eval` pdf.js не
 * нужен (`isEvalSupported: false`), рабочий поток грузится с того же адреса.
 *
 * Чёткость: `PDFViewer` рисует холст в физических пикселях экрана (`devicePixelRatio`), а на странице он занимает CSS-
 * ширину страницы — на экране 2× холст вдвое плотнее (тест `pdfv1-sharp-preview`).
 */
export function usePdfViewer(
  container: RefObject<HTMLDivElement | null>,
  viewerEl: RefObject<HTMLDivElement | null>,
  data: ArrayBuffer,
  initialPage: number,
  /** Предел масштаба в режиме «По ширине»: на широком экране лист не растягивается во всю ширину */
  maxFit: number,
  onPage: ((page: number) => void) | undefined,
  labels: { page: (page: number) => string; canvas: (page: number, total: number) => string },
): PdfViewerHandle {
  const viewer = useRef<PDFViewer | null>(null);
  const bus = useRef<EventBus | null>(null);
  const fitRef = useRef(true);
  const maxFitRef = useRef(maxFit);
  const onPageRef = useRef(onPage);
  const labelRef = useRef(labels);
  useEffect(() => {
    onPageRef.current = onPage;
    maxFitRef.current = maxFit;
    labelRef.current = labels;
  });
  const fitWidth = (target: PDFViewer) => {
    target.currentScaleValue = "page-width";
    if (target.currentScale > maxFitRef.current) target.currentScale = maxFitRef.current;
  };
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [status, setStatus] = useState<ViewerApi["status"]>("loading");
  const [page, setPage] = useState(initialPage);
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(1);
  const [fitted, setFitted] = useState(true);
  const [query, setQuery] = useState("");
  const [match, setMatch] = useState<Match>({ current: 0, total: 0 });

  useEffect(() => {
    const host = container.current;
    const inner = viewerEl.current;
    if (!host || !inner) return;
    let cancelled = false;
    const eventBus = new EventBus();
    const linkService = new PDFLinkService({ eventBus });
    const findController = new PDFFindController({ linkService, eventBus });
    const pdfViewer = new PDFViewer({
      container: host,
      viewer: inner,
      eventBus,
      linkService,
      findController,
      textLayerMode: 1,
      annotationMode: AnnotationMode.DISABLE,
      maxCanvasPixels: 4096 * 4096,
    });
    linkService.setViewer(pdfViewer);
    viewer.current = pdfViewer;
    bus.current = eventBus;
    fitRef.current = true;

    eventBus.on("pagesinit", () => {
      if (cancelled) return;
      fitWidth(pdfViewer);
      const target = Math.min(Math.max(1, initialPage), pdfViewer.pagesCount);
      if (target > 1) pdfViewer.currentPageNumber = target;
      setPages(pdfViewer.pagesCount);
      setPage(pdfViewer.currentPageNumber);
      setStatus("ready");
    });
    eventBus.on("pagechanging", (event: { pageNumber: number }) => {
      setPage(event.pageNumber);
      onPageRef.current?.(event.pageNumber);
    });
    eventBus.on("scalechanging", (event: { scale: number }) => {
      setScale(event.scale);
    });
    const onMatches = (event: { matchesCount?: Match }) => {
      if (event.matchesCount) setMatch({ ...event.matchesCount });
    };
    eventBus.on("updatefindmatchescount", onMatches);
    eventBus.on("updatefindcontrolstate", onMatches);
    // Подписи по-русски: pdf.js ставит английское «Page N». Холст — картинка с названием файла, текст под ним — текстовый слой.
    eventBus.on("pagerendered", (event: { pageNumber: number; source: { div: HTMLElement } }) => {
      event.source.div.setAttribute("aria-label", labelRef.current.page(event.pageNumber));
      const canvas = event.source.div.querySelector("canvas");
      canvas?.setAttribute("role", "img");
      canvas?.setAttribute(
        "aria-label",
        labelRef.current.canvas(event.pageNumber, pdfViewer.pagesCount),
      );
    });

    const task = getDocument({ data: new Uint8Array(data.slice(0)), isEvalSupported: false });
    void task.promise.then(
      (doc) => {
        if (cancelled) return;
        pdfViewer.setDocument(doc);
        linkService.setDocument(doc, null);
        setPdf(doc);
      },
      () => {
        if (!cancelled) setStatus("error");
      },
    );

    let timer: ReturnType<typeof setTimeout> | undefined;
    let width = host.clientWidth;
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (Math.abs(host.clientWidth - width) < 2) return;
            width = host.clientWidth;
            clearTimeout(timer);
            timer = setTimeout(() => {
              if (cancelled || !fitRef.current || pdfViewer.pagesCount === 0) return;
              fitWidth(pdfViewer);
            }, RESIZE_DELAY_MS);
          });
    observer?.observe(host);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      observer?.disconnect();
      viewer.current = null;
      bus.current = null;
      try {
        pdfViewer.setDocument(null as never);
      } catch {
        // уже уничтожен
      }
      inner.replaceChildren();
      setPdf(null);
      setStatus("loading");
      setQuery("");
      setMatch({ current: 0, total: 0 });
      void task.destroy();
    };
    // ratio читается PDFViewer из window.devicePixelRatio при каждой отрисовке
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, container, viewerEl]);

  const fit = useCallback(() => {
    const current = viewer.current;
    if (!current) return;
    fitRef.current = true;
    setFitted(true);
    fitWidth(current);
  }, []);
  const manual = useCallback((change: (current: PDFViewer) => void) => {
    const current = viewer.current;
    if (!current) return;
    fitRef.current = false;
    setFitted(false);
    change(current);
  }, []);
  const find = useCallback((text: string, again = false, backwards = false) => {
    setQuery(text);
    if (!text) setMatch({ current: 0, total: 0 });
    bus.current?.dispatch("find", {
      source: window,
      type: again ? "again" : "",
      query: text,
      caseSensitive: false,
      entireWord: false,
      highlightAll: true,
      findPrevious: backwards,
      matchDiacritics: false,
    });
  }, []);

  const api: ViewerApi = {
    status,
    pages,
    page,
    percent: Math.round(scale * 100),
    fitted,
    fit,
    actual: () => {
      manual((current) => {
        current.currentScaleValue = "1";
      });
    },
    zoomIn: () => {
      manual((current) => {
        current.increaseScale({ steps: 1 });
      });
    },
    zoomOut: () => {
      manual((current) => {
        current.decreaseScale({ steps: 1 });
      });
    },
    goTo: (target) => {
      const current = viewer.current;
      if (current) current.currentPageNumber = Math.min(Math.max(1, target), current.pagesCount);
    },
    search: {
      query,
      current: match.current,
      total: match.total,
      find: (text) => {
        find(text);
      },
      next: () => {
        find(query, true, false);
      },
      prev: () => {
        find(query, true, true);
      },
      clear: () => {
        find("");
      },
    },
  };
  return { api, pdf };
}
