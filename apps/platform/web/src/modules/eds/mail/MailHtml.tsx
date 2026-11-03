import { Button } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MAIL_SANDBOX, buildSrcDoc } from "./frameDoc";

const MIN_HEIGHT = 48;

/**
 * HTML письма в `iframe` (W18A-P2-4): `sandbox` без `allow-scripts`, `srcdoc` со строгим CSP, внешние картинки
 * по кнопке «Показать картинки». Ширина — по панели (таблицы рассылок ужимаются стилем фрейма; если письмо всё
 * равно шире — масштаб), высота — по содержимому: внутренней прокрутки нет, прокручивается страница.
 */
export function MailHtml({
  html,
  remoteImages,
  subject,
}: {
  html: string;
  remoteImages: number;
  subject: string;
}) {
  const { t, i18n } = useTranslation("letters");
  const [showImages, setShowImages] = useState(false);
  const [height, setHeight] = useState(MIN_HEIGHT);
  const frame = useRef<HTMLIFrameElement>(null);
  const quote = t("mail.view.quote");
  const missingImage = t("mail.view.missingImage");
  const srcDoc = useMemo(
    () => buildSrcDoc(html, showImages, { lang: i18n.language, quote, missingImage }),
    [html, showImages, i18n.language, quote, missingImage],
  );

  const fit = useCallback(() => {
    const el = frame.current;
    const doc = el?.contentDocument;
    if (!el || !doc?.body) return;
    const root = doc.documentElement;
    root.style.zoom = "";
    const width = el.clientWidth;
    if (width > 0 && root.scrollWidth > width + 1)
      root.style.zoom = String(width / root.scrollWidth);
    const next = Math.max(MIN_HEIGHT, Math.ceil(doc.body.getBoundingClientRect().height));
    setHeight((prev) => (prev === next ? prev : next));
  }, []);

  useEffect(() => {
    const el = frame.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [fit]);

  const onLoad = useCallback(() => {
    fit();
    const doc = frame.current?.contentDocument;
    // «…» у цитаты и поздно загруженные картинки меняют высоту; события не всплывают — слушаем в захвате.
    doc?.addEventListener("toggle", fit, true);
    doc?.addEventListener("load", fit, true);
  }, [fit]);

  return (
    <div className="pf-mail-html">
      {remoteImages > 0 && !showImages ? (
        <div className="pf-mail-images">
          <span className="pf-hint">{t("mail.view.imagesHidden")}</span>
          <Button
            size="small"
            onClick={() => {
              setShowImages(true);
            }}
          >
            {t("mail.view.showImages", { count: remoteImages })}
          </Button>
        </div>
      ) : null}
      <iframe
        ref={frame}
        className="pf-mail-frame"
        title={t("mail.view.frameTitle", { subject })}
        sandbox={MAIL_SANDBOX}
        srcDoc={srcDoc}
        style={{ height }}
        onLoad={onLoad}
      />
    </div>
  );
}
