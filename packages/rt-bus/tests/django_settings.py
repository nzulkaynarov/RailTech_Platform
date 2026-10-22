"""Настройки Django для тестов адаптера и для mypy (django-stubs). База — RT_BUS_TEST_DATABASE_URL (см. conftest)."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

_url = urlsplit(os.environ.get("RT_BUS_TEST_DATABASE_URL", "postgresql://rt:rt@localhost:5432/postgres"))

SECRET_KEY = "test-only-not-a-secret"
USE_TZ = True
TIME_ZONE = "UTC"
INSTALLED_APPS = ["rt_bus.django"]
MIDDLEWARE = ["rt_bus.django.middleware.CorrelationMiddleware"]
ROOT_URLCONF = "tests.django_urls"
ALLOWED_HOSTS = ["*"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("RT_BUS_TEST_DJANGO_DB", "rt_bus_dj"),
        "USER": _url.username or "rt",
        "PASSWORD": _url.password or "",
        "HOST": _url.hostname or "localhost",
        "PORT": str(_url.port or 5432),
    }
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
