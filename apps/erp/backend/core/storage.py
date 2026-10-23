"""
S3 storage backends for ERP (RustFS).

Architecture:
  - PublicStorage  -> erp-public  (product images, logos, avatars, category icons)
  - PrivateStorage -> erp-private (deals, quotes, invoices, acts, portal uploads, company documents)
  - TempStorage    -> erp-temp    (short-lived staging)

RustFS is NOT reachable from the browser. Hence no storage hands out an S3 address (presigned or not): `.url()` is
always the path under MEDIA_URL (as the old FileSystemStorage did). Public files are served by Django at `/media/*`
(`core.file_streaming.serve_public_media`), private ones — only through authenticated views that stream the bytes
(`core.file_streaming.stream_file_field`).

Without MINIO_ENDPOINT only DEBUG/tests are allowed (settings): then Django's default FileSystemStorage is used.
All file names are UUID-based to prevent collisions and information leakage.
"""

import asyncio
import functools
import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.encoding import filepath_to_uri

# Размер порции при отдаче объекта клиенту: память одного скачивания ограничена порцией, а не размером файла (S0-9).
STREAM_CHUNK_SIZE = 256 * 1024


class ObjectStream:
    """Тело объекта S3 для отдачи клиенту порциями: файл целиком в память или на диск не загружается.

    `S3Boto3StorageFile` при первом `read()` скачивает объект полностью (в `SpooledTemporaryFile` без предела в памяти),
    а Django под ASGI (daphne) складывает синхронный итератор ответа в список — файл в 50 МБ жил бы в памяти дважды.
    Здесь тело читается порциями `iter_chunks`, а `aiter_chunks` отдаёт их асинхронно (чтение блокирующее — идёт в потоке),
    поэтому ASGI-обработчик пишет порции клиенту по мере чтения."""

    def __init__(self, body, size, name=""):
        self._body = body
        self.size = size
        self.name = name

    def iter_chunks(self, chunk_size=STREAM_CHUNK_SIZE):
        return self._body.iter_chunks(chunk_size)

    async def aiter_chunks(self, chunk_size=STREAM_CHUNK_SIZE):
        chunks = iter(self.iter_chunks(chunk_size))
        try:
            while True:
                chunk = await asyncio.to_thread(next, chunks, None)
                if chunk is None:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(self.close)

    def close(self):
        self._body.close()


class TrackedStorageMixin:
    """Запись, чтение и удаление идут через `external_call("s3")` (M3-ERP-06): исход попадает в состояние сервиса S3
    (`/health` integration), а выключатель из центра внешних сервисов CRM останавливает обращения к хранилищу."""

    def open_stream(self, name):
        """Объект как `ObjectStream` (тело не загружается; размер — из ответа хранилища). Нет объекта — FileNotFoundError."""
        from botocore.exceptions import ClientError
        from storages.utils import clean_name

        from core.external_status import external_call

        key = self._normalize_name(clean_name(name))
        with external_call("s3", benign=(FileNotFoundError,)):
            try:
                response = self.bucket.Object(key).get()
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                    raise FileNotFoundError(name) from exc
                raise
        return ObjectStream(response["Body"], response["ContentLength"], name)

    def _save(self, name, content):
        from core.external_status import external_call

        with external_call("s3"):
            return super()._save(name, content)

    def _open(self, name, mode="rb"):
        from core.external_status import external_call

        # Нет такого файла (404) — ответ хранилища, а не его сбой.
        with external_call("s3", benign=(FileNotFoundError,)):
            return super()._open(name, mode)

    def delete(self, name):
        from core.external_status import external_call

        with external_call("s3"):
            return super().delete(name)


@functools.lru_cache(maxsize=1)
def _tracked_s3_storage():
    """`S3Boto3Storage` с отметками состояния сервиса (создаётся при первом обращении, как и сам импорт `storages`)."""
    from storages.backends.s3boto3 import S3Boto3Storage

    return type("TrackedS3Boto3Storage", (TrackedStorageMixin, S3Boto3Storage), {})


def _minio_is_configured():
    """Check if MinIO/S3 environment variables are set."""
    return bool(getattr(settings, "MINIO_ENDPOINT", None))


def _uuid_filename(instance, filename):
    """
    Generate a UUID-based filename preserving the original extension.
    Original filename is stored in the database, not in the S3 key.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"


# ────────────────────────────────────────────
# Upload path generators (used in model fields)
# ────────────────────────────────────────────


def product_image_path(instance, filename):
    """products/{product_id}/images/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"products/{instance.product_id}/images/{name}"


def product_document_path(instance, filename):
    """products/{product_id}/docs/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"products/{instance.product_id}/docs/{name}"


def company_logo_path(instance, filename):
    """companies/{company_id}/logo/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.pk}/logo/{name}"


def company_document_profile_logo_path(instance, filename):
    """companies/{company_id}/doc-profile/logo/{uuid}.{ext} — the branded logo the seller
    company puts on its own КП / contract documents (public bucket, like the avatar/logo)."""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/doc-profile/logo/{name}"


def user_avatar_path(instance, filename):
    """users/{user_id}/avatar/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"users/{instance.pk}/avatar/{name}"


def category_icon_path(instance, filename):
    """categories/{category_id}/icon/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"categories/{instance.pk}/icon/{name}"


def manufacturer_logo_path(instance, filename):
    """manufacturers/{company_id}/logo/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"manufacturers/{instance.pk}/logo/{name}"


def kyc_document_path(instance, filename):
    """companies/{company_id}/kyc/{uuid}.{ext}

    KYC removed in M1-ERP-02 (wave 1c); kept only because historical migrations reference it.
    """
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/kyc/{name}"


def deal_attachment_path(instance, filename):
    """
    Route attachment to the correct folder based on which FK is set.
    Falls back to generic 'attachments/' prefix.
    """
    name = _uuid_filename(instance, filename)
    if instance.deal_id:
        return f"deals/{instance.deal_id}/attachments/{name}"
    if instance.quote_id:
        return f"deals/{instance.quote.deal_id}/quotes/{name}"
    if instance.company_id:
        return f"companies/{instance.company_id}/documents/{name}"
    if instance.product_id:
        return f"products/{instance.product_id}/attachments/{name}"
    return f"attachments/{name}"


def quote_pdf_path(instance, filename):
    """deals/{deal_id}/quotes/{uuid}.pdf"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/quotes/{name}"


def contract_pdf_path(instance, filename):
    """deals/{deal_id}/contracts/{uuid}.pdf"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/contracts/{name}"


def contract_signed_path(instance, filename):
    """deals/{deal_id}/contracts/signed/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/contracts/signed/{name}"


def invoice_pdf_path(instance, filename):
    """deals/{deal_id}/invoices/{uuid}.pdf"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/invoices/{name}"


def act_pdf_path(instance, filename):
    """deals/{deal_id}/acts/{uuid}.pdf"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/acts/{name}"


def payment_proof_path(instance, filename):
    """deals/{deal_id}/payments/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.invoice.deal_id}/payments/{name}"


def payment_receipt_path(instance, filename):
    """deals/{deal_id}/payments/receipts/{uuid}.pdf (D2a: квитанция об оплате)"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.invoice.deal_id}/payments/receipts/{name}"


def fulfillment_pdf_path(instance, filename):
    """deals/{deal_id}/fulfillment/{uuid}.pdf (D2b: накладная на отгрузку)"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/fulfillment/{name}"


def generated_document_pdf_path(instance, filename):
    """companies/{company_id}/generated/{uuid}.pdf

    A template-based document («Документы 2.0») may not be tied to a deal, so it is
    filed under its owning company rather than a deal folder.
    """
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/generated/{name}"


def import_source_path(instance, filename):
    """sourcing/imports/{task_id}/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"sourcing/imports/{instance.pk}/{name}"


# Role applications removed in M1-ERP-02 (wave 1c); the three path helpers below are kept only
# because historical migrations reference them.


def company_application_contract_path(instance, filename):
    """companies/{company_id}/applications/{pk}/contract/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/applications/{instance.pk or 'new'}/contract/{name}"


def company_application_nda_path(instance, filename):
    """companies/{company_id}/applications/{pk}/nda/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/applications/{instance.pk or 'new'}/nda/{name}"


def company_application_partnership_path(instance, filename):
    """companies/{company_id}/applications/{pk}/partnership/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/applications/{instance.pk or 'new'}/partnership/{name}"


def company_document_path(instance, filename):
    """companies/{company_id}/documents/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"companies/{instance.company_id}/documents/{name}"


def temp_upload_path(instance, filename):
    """temp/{uuid}.{ext} — short-lived staging before promotion to private bucket"""
    name = _uuid_filename(instance, filename)
    return f"temp/{name}"


# ────────────────────────────────────────────
# Storage backend instances (lazy, configured in settings)
# ────────────────────────────────────────────


class MediaUrlMixin:
    """`url()` — путь под MEDIA_URL, а не адрес в S3: RustFS снаружи недоступен, подписанные ссылки хранилища
    наружу не выдаются (в браузер файл попадает только через Django). Так же отвечал FileSystemStorage."""

    def url(self, name, parameters=None, expire=None, http_method=None):
        return settings.MEDIA_URL + filepath_to_uri(name)


def _s3_storage(bucket_name):
    S3Boto3Storage = _tracked_s3_storage()
    storage_class = type("MediaUrlS3Storage", (MediaUrlMixin, S3Boto3Storage), {})
    return storage_class(
        endpoint_url=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        bucket_name=bucket_name,
        querystring_auth=False,
        file_overwrite=False,
    )


def get_public_storage():
    """Public storage backend (product images, logos, avatars): bucket erp-public, served by Django at /media/*."""
    if _minio_is_configured():
        return _s3_storage(settings.MINIO_PUBLIC_BUCKET)
    return default_storage


def get_private_storage():
    """Private storage backend (deals, imports, company documents, portal uploads): bucket erp-private."""
    if _minio_is_configured():
        return _s3_storage(settings.MINIO_PRIVATE_BUCKET)
    return default_storage


def get_temp_storage():
    """
    Temp storage backend — short-lived uploads (Excel staging, image previews, wizard files)
    that are later promoted to public/private or purged by lifecycle rules.
    """
    if _minio_is_configured():
        return _s3_storage(getattr(settings, "MINIO_TEMP_BUCKET", "") or "erp-temp")
    return default_storage
