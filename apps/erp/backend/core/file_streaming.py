"""Выдача файлов из хранилища: только через Django, адрес S3 (RustFS) браузеру не показывается.

Хранилище файлов ERP — RustFS (бакеты erp-private / erp-public), снаружи он недоступен. Поэтому:
  - приватные документы (PDF договора/счёта/акта, подписанный скан, документ компании, документ товара, загрузка портала)
    отдаёт аутентифицированное представление: `stream_file_field` читает байты из S3 и отдаёт потоком; `file_field.url`
    (= /media/<приватный путь>) не открывается нигде — это 404, как и раньше;
  - публичные картинки (аватары, логотипы, фото товаров, иконки категорий) отдаёт `serve_public_media` на
    `/media/*` доменов ERP и Cabinet по белому списку путей (core/urls.py).

Отдача идёт порциями (S0-9): тело объекта S3 читается `ObjectStream.aiter_chunks` и уходит клиенту по мере чтения, файл
целиком не попадает ни в память, ни на диск. Хранилище без `open_stream` (локальная файловая система в DEBUG и в тестах)
отдаёт `FileResponse`, как раньше.
"""

import mimetypes

from django.http import FileResponse, Http404, StreamingHttpResponse
from django.utils.http import content_disposition_header

from core.storage import get_public_storage


class ObjectStreamResponse(StreamingHttpResponse):
    """Ответ с телом объекта S3 порциями; `Content-Length` — размер из ответа хранилища, `Content-Disposition` — как у
    `FileResponse`. Закрытие ответа (в том числе обрыв соединения клиентом) закрывает и тело объекта."""

    def __init__(self, stream, *, content_type, as_attachment=False, filename=None):
        super().__init__(stream.aiter_chunks(), content_type=content_type)
        self._resource_closers.append(stream.close)
        self["Content-Length"] = str(stream.size)
        if as_attachment or filename:
            self["Content-Disposition"] = content_disposition_header(as_attachment, filename)


def storage_file_response(storage, name, *, content_type, as_attachment=False, filename=None):
    """Ответ с файлом `name` из `storage`; нет файла — FileNotFoundError (вызывающий решает, это 404 или сбой)."""
    if hasattr(storage, "open_stream"):
        return ObjectStreamResponse(
            storage.open_stream(name), content_type=content_type, as_attachment=as_attachment, filename=filename
        )
    handle = storage.open(name, "rb")
    response = FileResponse(handle, content_type=content_type, as_attachment=as_attachment, filename=filename)
    size = getattr(handle, "size", None)
    if isinstance(size, int) and "Content-Length" not in response:
        response["Content-Length"] = str(size)
    return response


def stream_file_field(file_field, *, content_type="application/pdf"):
    """Return a response streaming `file_field` (attachment), or raise Http404 if empty or gone from the storage.

    The calling view must have already authorized access (e.g. via get_object()
    on a tenant-scoped queryset), so this only handles the byte streaming.
    """
    if not file_field:
        raise Http404("File not generated yet")
    try:
        return storage_file_response(
            file_field.storage,
            file_field.name,
            content_type=content_type,
            as_attachment=True,
            filename=file_field.name.split("/")[-1],
        )
    except FileNotFoundError as exc:
        raise Http404("File is missing in the storage") from exc


def serve_public_media(request, path):
    """Public display asset (`erp-public`) by key; the URL pattern in core/urls.py whitelists the prefixes.

    Keys carry a UUID and never change, so the response may be cached; the type is taken from the extension and the
    browser must not guess another one (an SVG uploaded as a logo cannot run script from this domain).
    """
    try:
        response = storage_file_response(
            get_public_storage(), path, content_type=mimetypes.guess_type(path)[0] or "application/octet-stream"
        )
    except (FileNotFoundError, ValueError) as exc:
        raise Http404("No such file") from exc
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response
