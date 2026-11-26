import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Drawer, Skeleton } from "antd";
import { Suspense, lazy, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import { FileNotReadyError, downloadFile } from "../../api/download";
import { ApiError } from "../../api/errors";
import { DefinitionList, type DefinitionItem } from "../DefinitionList";

import { sniffType } from "./sniffType";

const PdfViewer = lazy(() => import("../PdfViewer"));

/** Ширина бокового окна по стандарту интерфейса (§6): 480 или 640. */
export const PEEK_WIDTH = 640;

const peekKey = (url: string) => ["document-peek", url] as const;

/**
 * «Открыть» из списка: тот же просмотр документа в боковом окне 640 (на телефоне — на весь экран), под ним «О документе»
 * тем, что уже знает список (вид, номер, дата, статус, контрагент). Файл берётся запросом с cookie сессии; имя при
 * скачивании даёт сервер. Word и Excel пока не показываются — «Скачать».
 */
export function DocumentPeek({
  url,
  title,
  fallbackName,
  about,
  onClose,
}: {
  url: string;
  title: string;
  /** Имя на случай, если сервер не прислал своё */
  fallbackName: string;
  about?: readonly DefinitionItem[];
  onClose: () => void;
}) {
  const { t } = useTranslation("ui");
  const { mobile } = useViewport();
  const file = useQuery({
    queryKey: peekKey(url),
    staleTime: 60_000,
    retry: false,
    queryFn: async (): Promise<ArrayBuffer> => {
      const response = await fetch(url, { credentials: "same-origin" });
      if (response.status === 202) throw new FileNotReadyError(2);
      if (!response.ok) {
        throw new ApiError(response.status, "HTTP_ERROR", `HTTP ${String(response.status)}`);
      }
      return response.arrayBuffer();
    },
  });
  const download = () => {
    void downloadFile(url, fallbackName);
  };
  const type = file.data ? sniffType(file.data) : null;
  let body: ReactNode;
  if (file.isPending) {
    body = <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  } else if (file.isError) {
    body = (
      <Alert
        type="warning"
        showIcon
        role="alert"
        message={t(
          file.error instanceof FileNotReadyError
            ? "documentViewer.notReady"
            : "documentViewer.error",
        )}
        action={
          <Button size="small" onClick={download}>
            {t("documentViewer.download")}
          </Button>
        }
      />
    );
  } else if (type === null) {
    body = (
      <div role="status">
        <p>{t("documentViewer.noPreview")}</p>
        <Button type="primary" onClick={download}>
          {t("documentViewer.download")}
        </Button>
      </div>
    );
  } else {
    body = (
      <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
        <PdfViewer
          data={file.data}
          name={title}
          type={type}
          onDownload={download}
          {...(about ? { about: <DefinitionList items={about} /> } : {})}
        />
      </Suspense>
    );
  }
  return (
    <Drawer
      open
      title={title}
      onClose={onClose}
      keyboard
      width={mobile ? "100%" : PEEK_WIDTH}
      styles={{ body: { padding: 16 } }}
      rootClassName="pf-dv-peek"
    >
      {body}
      {about && type === null && !file.isPending ? <DefinitionList items={about} /> : null}
    </Drawer>
  );
}
