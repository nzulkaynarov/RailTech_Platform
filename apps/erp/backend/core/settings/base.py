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

ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,erp.localhost",
).split(",")
