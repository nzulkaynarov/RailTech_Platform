"""Staging ИИ-импорта лежит в бакете erp-temp, а не в `default_storage` (S0-1).

backend кладёт файл, воркер Celery читает его по ключу — общей файловой системы у них нет. В тестах бакет `erp-temp`
подменён отдельным каталогом, отличным от `default_storage`: тест, который по-прежнему писал бы в `default_storage`,
не нашёл бы свой файл в «бакете».
"""

import pytest
from django.core.files.storage import FileSystemStorage


@pytest.fixture(autouse=True)
def temp_bucket(tmp_path, monkeypatch):
    bucket = FileSystemStorage(location=str(tmp_path / "erp-temp"), base_url="/media/")
    monkeypatch.setattr("core.storage.get_temp_storage", lambda: bucket)
    return bucket
