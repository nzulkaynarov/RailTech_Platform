"""Выдача файлов из хранилища: только через Django, адрес S3 (RustFS) браузеру не показывается.

Хранилище файлов ERP — RustFS (бакеты erp-private / erp-public), снаружи он недоступен. Поэтому:
  - приватные документы (PDF договора/счёта/акта, подписанный скан, документ компании, загрузка портала) отдаёт
    аутентифицированное представление: `stream_file_field` читает байты из S3 и отдаёт потоком; `file_field.url`
    (= /media/<приватный путь>) не открывается нигде — это 404, как и раньше;
  - публичные картинки (аватары, логотипы, фото товаров, иконки категорий) отдаёт `serve_public_media` на
    `/media/*` доменов ERP и Cabinet по белому списку путей (core/urls.py).
"""

import mimetypes

from django.http import FileResponse, Http404

from core.storage import get_public_storage


def stream_file_field(file_field, *, content_type="application/pdf"):
    """Return a FileResponse streaming `file_field`, or raise Http404 if empty.

    The calling view must have already authorized access (e.g. via get_object()
    on a tenant-scoped queryset), so this only handles the byte streaming.
    """
    if not file_field:
        raise Http404("File not generated yet")
    return FileResponse(
        file_field.open("rb"),
        content_type=content_type,
        as_attachment=True,
        filename=file_field.name.split("/")[-1],
    )


def serve_public_media(request, path):
    """Public display asset (`erp-public`) by key; the URL pattern in core/urls.py whitelists the prefixes.

    Keys carry a UUID and never change, so the response may be cached; the type is taken from the extension and the
    browser must not guess another one (an SVG uploaded as a logo cannot run script from this domain).
    """
    storage = get_public_storage()
    try:
        handle = storage.open(path, "rb")
    except (FileNotFoundError, ValueError) as exc:
        raise Http404("No such file") from exc
    response = FileResponse(handle, content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
    size = getattr(handle, "size", None)
    if isinstance(size, int):
        response["Content-Length"] = str(size)
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response
