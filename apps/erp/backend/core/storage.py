"""
Custom S3/MinIO storage backends for ERP Ecosystem.

Architecture:
  - PublicStorage  -> erp-public  (product images, logos, avatars)
  - PrivateStorage -> erp-private (deals, quotes, imports, company documents)

When MINIO_ENDPOINT is not set, falls back to Django's default FileSystemStorage.
All file names are UUID-based to prevent collisions and information leakage.
"""

import functools
import uuid

from django.conf import settings
from django.core.files.storage import default_storage


class TrackedStorageMixin:
    """Запись, чтение и удаление идут через `external_call("s3")` (M3-ERP-06): исход попадает в состояние сервиса S3
    (`/health` integration), а выключатель из центра внешних сервисов CRM останавливает обращения к хранилищу."""

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
# Storage backend instances (lazy, configured in settings.py)
# ────────────────────────────────────────────


def get_public_storage():
    """Return the public storage backend (for product images, logos, etc.)."""
    if _minio_is_configured():
        S3Boto3Storage = _tracked_s3_storage()

        # Match URL scheme to environment: https in production, http in dev.
        # Heuristic: if MINIO_PUBLIC_DOMAIN targets localhost or 127.0.0.1, we
        # are in dev and TLS is not terminated, so emit http. Otherwise https.
        public_domain = settings.MINIO_PUBLIC_DOMAIN or ""
        is_local = any(h in public_domain for h in ("localhost", "127.0.0.1"))
        url_protocol = "http:" if is_local else "https:"
        return S3Boto3Storage(
            endpoint_url=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=settings.MINIO_PUBLIC_BUCKET,
            querystring_auth=False,
            custom_domain=settings.MINIO_PUBLIC_DOMAIN,
            url_protocol=url_protocol,
            file_overwrite=False,
        )
    return default_storage


def get_private_storage():
    """
    Return the private storage backend (for deals, imports, company documents, etc.).

    Uses MINIO_EXTERNAL_ENDPOINT for presigned URL generation so URLs
    are accessible from the browser (e.g. localhost:9000), while file
    operations use the Docker-internal MINIO_ENDPOINT (e.g. minio:9000).
    """
    if _minio_is_configured():
        S3Boto3Storage = _tracked_s3_storage()

        external = getattr(settings, "MINIO_EXTERNAL_ENDPOINT", "") or settings.MINIO_ENDPOINT
        internal = settings.MINIO_ENDPOINT

        class PrivateS3Storage(S3Boto3Storage):
            """Rewrites presigned URLs to use external endpoint."""

            def url(self, name, parameters=None, expire=None, http_method=None):
                raw_url = super().url(
                    name,
                    parameters=parameters,
                    expire=expire,
                    http_method=http_method,
                )
                if internal != external and internal in raw_url:
                    return raw_url.replace(internal, external, 1)
                return raw_url

        return PrivateS3Storage(
            endpoint_url=internal,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=settings.MINIO_PRIVATE_BUCKET,
            querystring_auth=True,
            querystring_expire=900,  # 15 minutes
            file_overwrite=False,
        )
    return default_storage


def get_temp_storage():
    """
    Return the temp storage backend — short-lived uploads (Excel staging, image previews)
    that are later promoted to public/private or purged by lifecycle rules.
    """
    if _minio_is_configured():
        S3Boto3Storage = _tracked_s3_storage()

        external = getattr(settings, "MINIO_EXTERNAL_ENDPOINT", "") or settings.MINIO_ENDPOINT
        internal = settings.MINIO_ENDPOINT
        temp_bucket = getattr(settings, "MINIO_TEMP_BUCKET", "") or "erp-temp"

        class TempS3Storage(S3Boto3Storage):
            def url(self, name, parameters=None, expire=None, http_method=None):
                raw_url = super().url(
                    name,
                    parameters=parameters,
                    expire=expire,
                    http_method=http_method,
                )
                if internal != external and internal in raw_url:
                    return raw_url.replace(internal, external, 1)
                return raw_url

        return TempS3Storage(
            endpoint_url=internal,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=temp_bucket,
            querystring_auth=True,
            querystring_expire=3600,  # 1 hour
            file_overwrite=False,
        )
    return default_storage
