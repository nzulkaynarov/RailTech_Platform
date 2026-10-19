"""Базис: пути, .env, DEBUG/SECRET_KEY/ALLOWED_HOSTS (распил settings.py 919 строк).

BASE_DIR поднят на уровень выше — модуль теперь лежит в пакете core/settings/."""

import os
from pathlib import Path
from urllib.parse import urlsplit as _urlsplit

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# Пакет лежит на уровень глубже прежнего settings.py — parent добавлен.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR.parent / ".env")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/


# SECURITY WARNING: don't run with debug turned on in production!
# Explicit opt-in: only the literal "true" (any case) enables DEBUG. Previously
# `!= "False"` meant an empty string or "false" (lowercase) silently turned
# DEBUG ON in production.
DEBUG = os.environ.get("DJANGO_DEBUG", "False").strip().lower() == "true"

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-fallback-key-do-not-use-in-production"
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable is required in production.")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        "ALLOWED_HOSTS",
        "localhost,127.0.0.1,erp.localhost,cabinet.localhost,.localhost,cabinet.railtech.uz",
    ).split(",")
    if h.strip()
]

# Client Portal (Cabinet -> ERP, M2-ERP-01, M2-ERP-02)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("ERP_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")
CABINET_URL = os.environ.get("CABINET_URL", "http://cabinet.localhost")


def _origin_of(url: str) -> str:
    parts = _urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else url.rstrip("/")


# Единственный источник CORS на DEBUG=False (FIX-15, P-18): origin'ы Cabinet — `CABINET_ORIGIN` (через запятую, как у
# CRM: origin сравнивается со схемой и портом), по умолчанию — origin из CABINET_URL.
CABINET_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in (os.environ.get("CABINET_ORIGIN") or _origin_of(CABINET_URL)).split(",")
    if origin.strip()
]

# SameSite cookie сессии портала. `Lax` — веб; Telegram Mini App открывает Cabinet во фрейме чужого сайта,
# там нужен `None` (cookie уйдёт только с `Secure`, то есть по TLS) — задаётся при выкладке за TLS (FIX-15, C-12).
_SAMESITE_VALUES = {"lax": "Lax", "strict": "Strict", "none": "None"}
PORTAL_COOKIE_SAMESITE = _SAMESITE_VALUES.get(os.environ.get("PORTAL_COOKIE_SAMESITE", "Lax").strip().lower())
if PORTAL_COOKIE_SAMESITE is None:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("PORTAL_COOKIE_SAMESITE must be one of: Lax, Strict, None")
PORTAL_SESSION_COOKIE_NAME = "portal_session"
PORTAL_SESSION_MAX_AGE_DAYS = 14
# Загрузка клиента в `POST /portal/v1/uploads`: контракт — до 10 МБ (Q-14, FIX-21); ставка в МБ, в коде — байты.
PORTAL_UPLOAD_MAX_BYTES = int(os.environ.get("PORTAL_UPLOAD_MAX_MB", "10")) * 1024 * 1024
# Не больше стольких запросов magic-link в час на один адрес (FIX-14, P-10)
PORTAL_MAGIC_LINK_MAX_PER_HOUR = int(os.environ.get("PORTAL_MAGIC_LINK_MAX_PER_HOUR", "5"))
# Код акцепта КП из Cabinet уходит в Telegram, только если это явно включено (FIX-22): по умолчанию ERP в Telegram не
# пишет (бот принадлежит CRM), код идёт письмом через `EmailLog`. Нужен ещё `TELEGRAM_BOT_TOKEN`; QUESTIONS Q-FIX22-1.
PORTAL_ACCEPT_CODE_TELEGRAM = os.environ.get("PORTAL_ACCEPT_CODE_TELEGRAM", "").strip().lower() in ("1", "true", "yes")
