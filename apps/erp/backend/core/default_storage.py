"""`default_storage` Django при настроенном S3 — бакет `erp-private` (S0-1).

Включается в `core/settings/project.py` (`STORAGES["default"]`), когда задан MINIO_ENDPOINT, то есть всегда вне DEBUG:
голый `django.core.files.storage.default_storage` не может писать на диск контейнера (у backend и воркеров он свой, общего
тома нет). Выбран приватный бакет: всё, что не сказало явно «публичное» (`get_public_storage`) или «временное»
(`get_temp_storage`), по умолчанию закрыто. Модуль импортирует `storages` сразу, поэтому подключается только по строке
в настройках — при первом обращении к default_storage.
"""

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage

from core.storage import MediaUrlMixin, TrackedStorageMixin


class DefaultPrivateStorage(MediaUrlMixin, TrackedStorageMixin, S3Boto3Storage):
    def __init__(self, **kwargs):
        super().__init__(
            endpoint_url=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=settings.MINIO_PRIVATE_BUCKET,
            querystring_auth=False,
            file_overwrite=False,
            **kwargs,
        )
