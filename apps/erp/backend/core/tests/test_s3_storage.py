"""Файлы ERP — в S3 (RustFS), а не на диск контейнера (S0-1, волна 10).

Что проверяем: без S3 вне DEBUG ERP не стартует; бакеты и адреса файлов; наружу не уходит ни адрес RustFS, ни
подписанная ссылка; публичные картинки отдаёт Django по белому списку путей, приватные через /media недоступны.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from rest_framework.test import APIClient

from core import storage as storage_module

BACKEND_DIR = Path(__file__).resolve().parents[2]
SEAM_ENV = {
    "SERVICE_TOKEN_CRM_TO_ERP": "seam-a",
    "ERP_WEBHOOK_SECRET": "seam-b",
    "ERP_MCP_CONTEXT_KEY": "seam-c",
    "PLATFORM_SSO_SECRET": "seam-d",
}
S3_NAMES = ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")


def _start_django(extra_env: dict) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key not in S3_NAMES}
    env.update({"DJANGO_SETTINGS_MODULE": "core.settings", "DJANGO_SECRET_KEY": "x" * 50, **SEAM_ENV, **extra_env})
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_production_start_fails_without_s3():
    result = _start_django({"DJANGO_DEBUG": "False"})

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    for name in S3_NAMES:
        assert name in result.stderr


def test_production_start_fails_when_only_the_endpoint_is_set():
    result = _start_django({"DJANGO_DEBUG": "False", "MINIO_ENDPOINT": "http://rustfs:9000"})

    assert result.returncode != 0
    assert "MINIO_ACCESS_KEY" in result.stderr and "MINIO_SECRET_KEY" in result.stderr


def test_production_start_succeeds_with_s3():
    result = _start_django(
        {
            "DJANGO_DEBUG": "False",
            "MINIO_ENDPOINT": "http://rustfs:9000",
            "MINIO_ACCESS_KEY": "erp",
            "MINIO_SECRET_KEY": "erp-secret",
        }
    )

    assert result.returncode == 0, result.stderr


def test_debug_start_without_s3_uses_local_storage():
    result = _start_django({"DJANGO_DEBUG": "True"})

    assert result.returncode == 0, result.stderr


@pytest.fixture
def s3(settings):
    settings.MINIO_ENDPOINT = "http://rustfs:9000"
    settings.MINIO_ACCESS_KEY = "erp"
    settings.MINIO_SECRET_KEY = "erp-secret"
    settings.MINIO_PUBLIC_BUCKET = "erp-public"
    settings.MINIO_PRIVATE_BUCKET = "erp-private"
    settings.MINIO_TEMP_BUCKET = "erp-temp"


@pytest.mark.parametrize(
    ("getter", "bucket"),
    [
        (storage_module.get_private_storage, "erp-private"),
        (storage_module.get_public_storage, "erp-public"),
        (storage_module.get_temp_storage, "erp-temp"),
    ],
)
def test_buckets_and_internal_endpoint(s3, getter, bucket):
    backend = getter()

    assert backend.bucket_name == bucket
    assert backend.endpoint_url == "http://rustfs:9000"


@pytest.mark.parametrize(
    "getter", [storage_module.get_private_storage, storage_module.get_public_storage, storage_module.get_temp_storage]
)
def test_url_never_exposes_the_s3_address(s3, getter):
    url = getter().url("deals/7/quotes/ab cd.pdf")

    assert url == "/media/deals/7/quotes/ab%20cd.pdf"
    assert "rustfs" not in url and "X-Amz" not in url


def test_without_s3_in_debug_the_local_storage_is_used(settings):
    settings.MINIO_ENDPOINT = ""

    assert storage_module.get_private_storage() is storage_module.get_public_storage()
    assert isinstance(storage_module.get_private_storage(), FileSystemStorage)


def test_models_keep_the_buckets_they_had():
    from portal.models import PortalUpload
    from sales.models import Quote

    from accounts.models import CustomUser
    from catalog.models import ProductImage

    for model, field in ((Quote, "pdf_file"), (PortalUpload, "file")):
        assert model._meta.get_field(field)._storage_callable is storage_module.get_private_storage
    for model, field in ((CustomUser, "avatar"), (ProductImage, "image")):
        assert model._meta.get_field(field)._storage_callable is storage_module.get_public_storage


@pytest.fixture
def public_bucket(tmp_path):
    """Подмена `erp-public` каталогом на диске: тот же интерфейс storage.open(), без сети."""
    backend = FileSystemStorage(location=str(tmp_path), base_url="/media/")
    with patch("core.file_streaming.get_public_storage", return_value=backend):
        yield backend


def test_public_image_is_served_by_django(public_bucket):
    key = "products/12/images/0a1b2c.png"
    public_bucket.save(key, ContentFile(b"\x89PNG-bytes"))

    response = APIClient().get(f"/media/{key}")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"".join(response.streaming_content) == b"\x89PNG-bytes"


def test_missing_public_image_is_404(public_bucket):
    assert APIClient().get("/media/products/12/images/none.png").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "deals/5/quotes/x.pdf",
        "portal_uploads/2026/10/scan.pdf",
        "companies/3/documents/x.pdf",
    ],
)
def test_private_paths_are_not_reachable_via_media(public_bucket, path):
    public_bucket.save(path, ContentFile(b"secret"))

    assert APIClient().get(f"/media/{path}").status_code == 404


def test_default_storage_is_the_private_bucket_when_s3_is_configured():
    """Голый default_storage вне DEBUG не может писать на диск контейнера: он тоже в S3 (erp-private)."""
    code = (
        "import django; django.setup();"
        "from django.core.files.storage import default_storage as d;"
        "d._setup(); s = d._wrapped;"
        "print(type(s).__name__, s.bucket_name, s.url('x/y.pdf'))"
    )
    env = {key: value for key, value in os.environ.items() if key not in S3_NAMES}
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "core.settings",
            "DJANGO_SECRET_KEY": "x" * 50,
            "DJANGO_DEBUG": "False",
            "MINIO_ENDPOINT": "http://rustfs:9000",
            "MINIO_ACCESS_KEY": "erp",
            "MINIO_SECRET_KEY": "erp-secret",
            **SEAM_ENV,
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["DefaultPrivateStorage", "erp-private", "/media/x/y.pdf"]


def test_no_bare_default_storage_in_application_code():
    """Файлы идут через get_public_storage / get_private_storage / get_temp_storage. Голый `default_storage` (и
    FileSystemStorage) в прикладном коде — запись на диск одного контейнера: воркер Celery не найдёт файл backend'а."""
    import ast

    allowed = {BACKEND_DIR / "core" / "storage.py"}
    offenders = []
    for path in BACKEND_DIR.rglob("*.py"):
        parts = set(path.relative_to(BACKEND_DIR).parts)
        if path in allowed or "tests" in parts or "migrations" in parts or path.name.startswith("test_"):
            continue
        if path.name == "conftest.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            if {"default_storage", "FileSystemStorage"} & set(names):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")
    assert not offenders, offenders


def test_every_file_field_chooses_its_bucket_explicitly():
    """Поле файла без `storage=` уходило бы в default_storage, а не в нужный бакет."""
    from django.apps import apps
    from django.db.models import FileField

    chosen = {storage_module.get_private_storage, storage_module.get_public_storage, storage_module.get_temp_storage}
    missing = [
        f"{model._meta.label}.{field.name}"
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, FileField) and field._storage_callable not in chosen
    ]
    assert not missing, missing
