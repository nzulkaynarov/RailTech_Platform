"""Authenticated streaming of private file fields.

CRITICAL for prod: production runs WITHOUT MinIO (local FileSystemStorage), and
Django does NOT serve private MEDIA paths (only public avatars/logos via a regex;
`static()` is a no-op when DEBUG=False). So `file_field.url` (= /media/<private>)
returns 404 on prod. Every private document (contract/invoice/act PDF, signed
scan, KYC document) must therefore be downloaded through an authenticated view
that streams the bytes from whatever storage backend is configured — this works
identically with MinIO and with local storage. Mirrors the КП download_pdf action.
"""

from django.http import FileResponse, Http404


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
