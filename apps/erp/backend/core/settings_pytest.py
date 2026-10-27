"""Настройки только для pytest (`DJANGO_SETTINGS_MODULE` в pytest.ini). Прод и стенд их не видят: `core.settings` не тронут.

Что меняется относительно `core.settings` (W14-S1, скорость тестов):

* ``PASSWORD_HASHERS`` — MD5. Тесты создают сотни пользователей, а PBKDF2 (по умолчанию 1 млн итераций) стоит ~0,3 с на пароль.
  Ни один тест не проверяет алгоритм хеша; нужен именно этот алгоритм — ``@override_settings(PASSWORD_HASHERS=[…])`` в тесте.
* Параллельный прогон (pytest-xdist, воркеры ``gw0``, ``gw1`` …): у каждого воркера свои базы Redis и свой ``MEDIA_ROOT``.
  ``cache.clear()`` в Redis — это ``FLUSHDB``: на общей базе один воркер стирал бы троттлинг-счётчики, блокировки входа и
  одноразовые метки соседа. Воркер ``gwN`` берёт базы ``3·N + k`` (``k`` = исходный номер базы из ``REDIS_*_URL``: кэш 0,
  брокер Celery 1, Channels 2); без xdist (``N = 0``) номера прежние. Redis тестового набора поднят с ``--databases 1024``
  (scripts/test_backend_local.sh). Базы Postgres ``test_*_gwN`` разводит сам pytest-django.
* ``TEST['TEMPLATE']`` — если задан ``ERP_TEST_DB_TEMPLATE``, тестовые базы клонируются из уже мигрированной шаблонной базы
  (её строит scripts/test_backend_local.sh один раз на набор миграций), а не мигрируются с нуля в каждом воркере.
"""

import os
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit

from core.settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

_match = re.fullmatch(r"gw(\d+)", os.environ.get("PYTEST_XDIST_WORKER", ""))
WORKER_INDEX = int(_match.group(1)) if _match else 0


def _redis_url_for_worker(url: str) -> str:
    """``redis://host:6379/<db>`` → тот же адрес с базой ``3·N + <db>`` (N — номер воркера xdist)."""
    parts = urlsplit(url)
    db = int(parts.path.lstrip("/") or 0)
    return urlunsplit(parts._replace(path=f"/{3 * WORKER_INDEX + db}"))


CACHES = {
    alias: (
        {**config, "LOCATION": _redis_url_for_worker(config["LOCATION"])}
        if str(config.get("LOCATION", "")).startswith("redis")
        else dict(config)
    )
    for alias, config in CACHES.items()  # noqa: F405
}
CELERY_BROKER_URL = _redis_url_for_worker(CELERY_BROKER_URL)  # noqa: F405
CELERY_RESULT_BACKEND = _redis_url_for_worker(CELERY_RESULT_BACKEND)  # noqa: F405
for _layer in CHANNEL_LAYERS.values():  # noqa: F405
    _layer["CONFIG"]["hosts"] = [_redis_url_for_worker(host) for host in _layer["CONFIG"]["hosts"]]

# Файлы, которые тесты кладут через default_storage (DEBUG → локальная файловая система), — в каталог воркера в /tmp
# контейнера, а не в общий backend/media: фиксированные имена файлов у двух воркеров не сталкиваются, а смонтированный
# каталог проекта не засоряется.
if not MINIO_ENDPOINT:  # noqa: F405
    MEDIA_ROOT = os.path.join(tempfile.gettempdir(), f"rt-erp-test-media-gw{WORKER_INDEX}")

if os.environ.get("ERP_TEST_DB_TEMPLATE"):
    for _db in DATABASES.values():  # noqa: F405
        _db["TEST"] = {**_db.get("TEST", {}), "TEMPLATE": os.environ["ERP_TEST_DB_TEMPLATE"]}
