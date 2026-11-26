import { Modal } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useMediaQuery } from "../../../app/shell/useViewport";
import { PageThumbs } from "./PageThumbs";
import { ViewerToolbar } from "./ViewerToolbar";
import type { ViewerApi } from "./types";
import { useFullRoute } from "./useFullRoute";
import { usePdfViewer } from "./usePdfViewer";
import "./document-viewer.css";

/** Предел «По ширине» на весь экран: лист не шире ~870 px (иначе на широком мониторе строки нечитаемо длинные) */
const FULL_MAX_FIT = 1.1;
export const PHONE_QUERY = "(max-width: 767px)";

export interface DocumentViewerProps {
  /** Байты файла: PDF или картинка */
  data: ArrayBuffer;
  /** Название для подписей и имя файла при скачивании */
  name: string;
  /** MIME-тип; без него — PDF */
  type?: string;
  /** `panel` — внутри карточки, формы, окна; `full` — слой на всё окно (его же открывает кнопка «На весь экран») */
  mode?: "panel" | "full";
  /** Для `mode="full"` напрямую: что делает «Свернуть» */
  onClose?: () => void;
  initialPage?: number;
  /** Своё скачивание (например, с именем файла от сервера); без него файл сохраняется из уже полученных байт */
  onDownload?: () => void;
  /** `false` — в панели нет своего «Скачать» (его уже даёт экран); на весь экран кнопка есть всегда */
  panelDownload?: boolean;
}

function extensionOf(type: string | undefined): string {
  if (type === "image/png") return ".png";
  if (type === "image/jpeg") return ".jpg";
  if (type === "image/webp") return ".webp";
  return ".pdf";
}

/** Скачать файл из уже полученных байт (имя берётся у просмотра: сервер отдаёт то же, что видно). */
function saveBytes(data: ArrayBuffer, type: string | undefined, name: string) {
  const url = URL.createObjectURL(new Blob([data], { type: type ?? "application/pdf" }));
  const link = document.createElement("a");
  link.href = url;
  const ext = extensionOf(type);
  link.download = name.toLowerCase().endsWith(ext) ? name : `${name}${ext}`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}

/**
 * Единый просмотр документа Платформы. В панели — лист и панель инструментов с кнопкой «На весь экран»; по кнопке
 * открывается слой на всё окно (окно по правилам модальных: фокус внутри, Esc закрывает, фокус возвращается на кнопку,
 * страница под слоем не прокручивается) с адресом `?view=full&page=N`. На телефоне (< 768) нажатие на лист открывает
 * слой сразу.
 */
export default function DocumentViewer(props: DocumentViewerProps) {
  const { mode = "panel" } = props;
  if (mode === "full") return <ViewerBody {...props} mode="full" />;
  return <PanelWithLayer {...props} />;
}

function PanelWithLayer(props: DocumentViewerProps) {
  const route = useFullRoute();
  const page = useRef(1);
  return (
    <>
      <ViewerBody
        {...props}
        mode="panel"
        onPage={(next) => {
          page.current = next;
        }}
        onFull={() => {
          route.openFull(page.current);
        }}
      />
      <Modal
        open={route.open}
        onCancel={route.close}
        footer={null}
        closable={false}
        destroyOnHidden
        width="100vw"
        title={<span className="pf-dv-sr">{props.name}</span>}
        className="pf-dv-modal"
        rootClassName="pf-dv-modal-root"
        keyboard
        maskClosable={false}
      >
        <ViewerBody
          {...props}
          mode="full"
          initialPage={route.page}
          onPage={route.setPage}
          onClose={route.close}
        />
      </Modal>
    </>
  );
}

function ViewerBody(
  props: DocumentViewerProps & {
    mode: "panel" | "full";
    onPage?: (page: number) => void;
    onFull?: () => void;
  },
) {
  return props.type?.startsWith("image/") ? <ImageSurface {...props} /> : <PdfSurface {...props} />;
}

function useChrome(mode: "panel" | "full") {
  const phone = useMediaQuery(PHONE_QUERY);
  return { phone, thumbsShown: mode === "full" && !phone };
}

type SurfaceProps = DocumentViewerProps & {
  mode: "panel" | "full";
  onPage?: (page: number) => void;
  onFull?: () => void;
};

function PdfSurface({
  data,
  name,
  type,
  mode,
  initialPage = 1,
  onDownload,
  panelDownload,
  onPage,
  onFull,
  onClose,
}: SurfaceProps) {
  const { t } = useTranslation("ui");
  const container = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const { phone, thumbsShown } = useChrome(mode);
  const { api, pdf } = usePdfViewer(
    container,
    inner,
    data,
    initialPage,
    mode === "full" ? FULL_MAX_FIT : Infinity,
    onPage,
    {
      page: (n) => t("documentViewer.thumbPage", { page: n }),
      canvas: (n, total) => t("documentViewer.pageLabel", { name, page: n, total }),
    },
  );
  return (
    <Frame
      mode={mode}
      name={name}
      api={api}
      phone={phone}
      onDownload={() => {
        (
          onDownload ??
          (() => {
            saveBytes(data, type, name);
          })
        )();
      }}
      onFull={onFull}
      onClose={onClose}
      showDownload={mode === "full" || panelDownload !== false}
      thumbs={
        thumbsShown && pdf && api.pages > 1 ? (
          <PageThumbs pdf={pdf} pages={api.pages} page={api.page} onGo={api.goTo} />
        ) : null
      }
      onStageClick={phone && mode === "panel" ? onFull : undefined}
    >
      <div
        ref={container}
        className="pf-dv-scroll"
        data-testid="pdf-pages"
        role="region"
        tabIndex={0}
        aria-label={t("documentViewer.region", { name })}
      >
        <div ref={inner} className="pdfViewer" />
      </div>
    </Frame>
  );
}

function ImageSurface({
  data,
  name,
  type,
  mode,
  onDownload,
  panelDownload,
  onFull,
  onClose,
}: SurfaceProps) {
  const { t } = useTranslation("ui");
  const { phone } = useChrome(mode);
  const url = useMemo(() => URL.createObjectURL(new Blob([data], { type })), [data, type]);
  useEffect(
    () => () => {
      URL.revokeObjectURL(url);
    },
    [url],
  );
  const [scale, setScale] = useState<number | "fit">("fit");
  const [natural, setNatural] = useState(0);
  const [status, setStatus] = useState<ViewerApi["status"]>("loading");
  const current = scale === "fit" ? 1 : scale;
  const api: ViewerApi = {
    status,
    pages: 1,
    page: 1,
    percent: scale === "fit" ? 100 : Math.round(scale * 100),
    fitted: scale === "fit",
    fit: () => {
      setScale("fit");
    },
    actual: () => {
      setScale(1);
    },
    zoomIn: () => {
      setScale(Math.min(5, current * 1.25));
    },
    zoomOut: () => {
      setScale(Math.max(0.1, current / 1.25));
    },
    goTo: () => undefined,
    search: null,
  };
  return (
    <Frame
      mode={mode}
      name={name}
      api={api}
      phone={phone}
      onDownload={() => {
        (
          onDownload ??
          (() => {
            saveBytes(data, type, name);
          })
        )();
      }}
      onFull={onFull}
      onClose={onClose}
      showDownload={mode === "full" || panelDownload !== false}
      thumbs={null}
      onStageClick={phone && mode === "panel" ? onFull : undefined}
    >
      <div
        className="pf-dv-scroll pf-dv-image-scroll"
        data-testid="image-pages"
        role="region"
        tabIndex={0}
        aria-label={t("documentViewer.region", { name })}
      >
        <img
          src={url}
          alt={name}
          className="pf-dv-image"
          style={
            scale === "fit"
              ? undefined
              : { width: `${String(natural * scale)}px`, maxWidth: "none" }
          }
          onLoad={(event) => {
            setNatural(event.currentTarget.naturalWidth);
            setStatus("ready");
          }}
          onError={() => {
            setStatus("error");
          }}
        />
      </div>
    </Frame>
  );
}

function Frame({
  mode,
  name,
  api,
  phone,
  onDownload,
  onFull,
  onClose,
  showDownload,
  thumbs,
  onStageClick,
  children,
}: {
  mode: "panel" | "full";
  name: string;
  api: ViewerApi;
  phone: boolean;
  onDownload: () => void;
  onFull?: (() => void) | undefined;
  onClose?: (() => void) | undefined;
  showDownload: boolean;
  thumbs: React.ReactNode;
  onStageClick?: (() => void) | undefined;
  children: React.ReactNode;
}) {
  const { t } = useTranslation("ui");
  const root = useRef<HTMLDivElement>(null);
  // Клавиши: + и − масштаб, 0 — по ширине, ← → страницы, Ctrl F — поиск (в слое на весь экран и в панели в фокусе)
  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea")) return;
    const key = event.key;
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "f" && api.search) {
      event.preventDefault();
      root.current?.querySelector<HTMLInputElement>(".pf-dv-search input")?.focus();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (key === "+" || key === "=") api.zoomIn();
    else if (key === "-" || key === "_") api.zoomOut();
    else if (key === "0") api.fit();
    else if (key === "ArrowRight") api.goTo(api.page + 1);
    else if (key === "ArrowLeft") api.goTo(api.page - 1);
    else return;
    event.preventDefault();
  };
  return (
    <div
      ref={root}
      className={`pf-dv pf-dv-${mode}`}
      data-testid={mode === "full" ? "dv-layer" : "dv-panel"}
      onKeyDown={onKeyDown}
    >
      {mode === "full" ? (
        <div className="pf-dv-head">
          <div className="pf-dv-name">
            <strong>{name}</strong>
            <span>{api.pages > 0 ? t("documentViewer.pagesCount", { count: api.pages }) : ""}</span>
          </div>
        </div>
      ) : null}
      <ViewerToolbar
        api={api}
        mode={mode}
        phone={phone}
        onDownload={onDownload}
        onFull={onFull}
        onClose={onClose}
        showDownload={showDownload}
      />
      <div className="pf-dv-body">
        {thumbs}
        <div className="pf-dv-stage" onClick={onStageClick} data-state={api.status}>
          {children}
        </div>
      </div>
      {api.status === "error" ? (
        <p className="pf-hint" role="alert">
          {t("documentViewer.error")}
        </p>
      ) : null}
    </div>
  );
}
