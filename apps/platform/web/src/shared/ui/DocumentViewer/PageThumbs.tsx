import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

const THUMB_WIDTH = 96;

/** Одна миниатюра: рисуется, когда попала в видимую часть списка (длинный документ не рисуется целиком). */
function Thumb({ pdf, number, current, onGo }: ThumbProps) {
  const { t } = useTranslation("ui");
  const canvas = useRef<HTMLCanvasElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const node = button.current;
    const target = canvas.current;
    if (!node || !target) return;
    let cancelled = false;
    const draw = async () => {
      const page = await pdf.getPage(number);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const ratio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
      const scale = (THUMB_WIDTH / base.width) * ratio;
      const viewport = page.getViewport({ scale });
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      target.style.width = `${String(THUMB_WIDTH)}px`;
      const context = target.getContext("2d");
      if (context) await page.render({ canvasContext: context, viewport }).promise;
    };
    const observer =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
              observer?.disconnect();
              void draw().catch(() => undefined);
            }
          });
    observer?.observe(node);
    return () => {
      cancelled = true;
      observer?.disconnect();
    };
  }, [pdf, number]);
  useEffect(() => {
    if (current)
      if (typeof button.current?.scrollIntoView === "function")
        button.current.scrollIntoView({ block: "nearest" });
  }, [current]);
  return (
    <button
      type="button"
      ref={button}
      className={current ? "pf-dv-thumb pf-dv-thumb-current" : "pf-dv-thumb"}
      aria-current={current ? "page" : undefined}
      aria-label={t("documentViewer.thumbPage", { page: number })}
      onClick={() => {
        onGo(number);
      }}
    >
      <canvas ref={canvas} aria-hidden="true" />
      <span>{number}</span>
    </button>
  );
}

interface ThumbProps {
  pdf: PDFDocumentProxy;
  number: number;
  current: boolean;
  onGo: (page: number) => void;
}

/** Миниатюры страниц слева (на весь экран; на телефоне их нет). */
export function PageThumbs({
  pdf,
  pages,
  page,
  onGo,
}: {
  pdf: PDFDocumentProxy;
  pages: number;
  page: number;
  onGo: (page: number) => void;
}) {
  const { t } = useTranslation("ui");
  return (
    <nav className="pf-dv-thumbs" aria-label={t("documentViewer.thumbs")}>
      <p className="pf-dv-thumbs-title">{t("documentViewer.thumbs")}</p>
      {Array.from({ length: pages }, (_, index) => (
        <Thumb
          key={index + 1}
          pdf={pdf}
          number={index + 1}
          current={page === index + 1}
          onGo={onGo}
        />
      ))}
    </nav>
  );
}
