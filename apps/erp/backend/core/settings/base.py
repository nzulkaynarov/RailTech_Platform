"""Базис: пути, .env, DEBUG/SECRET_KEY/ALLOWED_HOSTS (распил settings.py 919 строк).

BASE_DIR поднят на уровень выше — модуль теперь лежит в пакете core/settings/."""

import os
from pathlib import Path

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
PORTAL_SESSION_COOKIE_NAME = "portal_session"
PORTAL_SESSION_MAX_AGE_DAYS = 14
