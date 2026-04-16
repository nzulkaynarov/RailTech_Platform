"""
Custom S3/MinIO storage backends for RailTech B2B Ecosystem.

Architecture:
  - PublicStorage  -> railtech-public  (product images, logos, avatars)
  - PrivateStorage -> railtech-private (KYC, deals, quotes, imports)

When MINIO_ENDPOINT is not set, falls back to Django's default FileSystemStorage.
All file names are UUID-based to prevent collisions and information leakage.
"""

import uuid
from django.conf import settings
from django.core.files.storage import default_storage


def _minio_is_configured():
    """Check if MinIO/S3 environment variables are set."""
    return bool(getattr(settings, 'MINIO_ENDPOINT', None))


def _uuid_filename(instance, filename):
    """
    Generate a UUID-based filename preserving the original extension.
    Original filename is stored in the database, not in the S3 key.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
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
    """companies/{company_id}/kyc/{uuid}.{ext}"""
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
    if instance.message_id:
        return f"deals/{instance.message.deal_id}/chat/{name}"
    if instance.company_id:
        return f"companies/{instance.company_id}/documents/{name}"
    if instance.product_id:
        return f"products/{instance.product_id}/attachments/{name}"
    return f"attachments/{name}"


def quote_pdf_path(instance, filename):
    """deals/{deal_id}/quotes/{uuid}.pdf"""
    name = _uuid_filename(instance, filename)
    return f"deals/{instance.deal_id}/quotes/{name}"


def import_source_path(instance, filename):
    """sourcing/imports/{task_id}/{uuid}.{ext}"""
    name = _uuid_filename(instance, filename)
    return f"sourcing/imports/{instance.pk}/{name}"


# ────────────────────────────────────────────
# Storage backend instances (lazy, configured in settings.py)
# ────────────────────────────────────────────

def get_public_storage():
    """Return the public storage backend (for product images, logos, etc.)."""
    if _minio_is_configured():
        from storages.backends.s3boto3 import S3Boto3Storage
        return S3Boto3Storage(
            endpoint_url=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=settings.MINIO_PUBLIC_BUCKET,
            querystring_auth=False,
            custom_domain=settings.MINIO_PUBLIC_DOMAIN,
            file_overwrite=False,
        )
    return default_storage


def get_private_storage():
    """
    Return the private storage backend (for KYC, deals, imports, etc.).

    Uses MINIO_EXTERNAL_ENDPOINT for presigned URL generation so URLs
    are accessible from the browser (e.g. localhost:9000), while file
    operations use the Docker-internal MINIO_ENDPOINT (e.g. minio:9000).
    """
    if _minio_is_configured():
        from storages.backends.s3boto3 import S3Boto3Storage

        external = getattr(settings, 'MINIO_EXTERNAL_ENDPOINT', '') or settings.MINIO_ENDPOINT
        internal = settings.MINIO_ENDPOINT

        class PrivateS3Storage(S3Boto3Storage):
            """Rewrites presigned URLs to use external endpoint."""

            def url(self, name, parameters=None, expire=None, http_method=None):
                raw_url = super().url(
                    name, parameters=parameters, expire=expire, http_method=http_method,
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
