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
}: {
  data: ArrayBuffer;
  name: string;
  /** MIME-тип; без него — PDF */
  type?: string;
  /** Своё скачивание (имя файла от сервера); без него — из полученных байт */
  onDownload?: () => void;
}) {
  return (
    <DocumentViewer
      data={data}
      name={name}
      {...(type ? { type } : {})}
      {...(onDownload ? { onDownload } : {})}
      mode="panel"
    />
  );
}
