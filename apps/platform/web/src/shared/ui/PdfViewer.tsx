import DocumentViewer from "./DocumentViewer/DocumentViewer";

/**
 * Просмотр PDF и картинок в Платформе — тонкая обёртка над единым `DocumentViewer` в виде панели (кнопка «На весь
 * экран» есть везде, где есть просмотр). Модуль грузится лениво (`lazy`) — вместе с первым открытием файла.
 */
export default function PdfViewer({
  data,
  name,
  type,
  onDownload,
  panelDownload,
}: {
  data: ArrayBuffer;
  name: string;
  /** MIME-тип; без него — PDF */
  type?: string;
  /** Своё скачивание (имя файла от сервера); без него — из полученных байт */
  onDownload?: () => void;
  /** `false` — в панели нет своего «Скачать» (его уже даёт экран) */
  panelDownload?: boolean;
}) {
  return (
    <DocumentViewer
      data={data}
      name={name}
      {...(type ? { type } : {})}
      {...(onDownload ? { onDownload } : {})}
      {...(panelDownload === false ? { panelDownload } : {})}
      mode="panel"
    />
  );
}
