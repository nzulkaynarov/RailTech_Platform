"""Пароли, i18n, static/media, MinIO, auth-модель."""

import os

from django.utils.translation import gettext_lazy as _

from .database import *  # noqa: F401,F403 — последовательная композиция настроек

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "ru"

TIME_ZONE = "Asia/Tashkent"

USE_I18N = True

USE_TZ = True

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

LANGUAGES = [
    ("ru", _("Русский")),
    ("en", _("English")),
]


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# ─── MinIO / S3 Storage ───────────────────────────────────────────────────────
# When MINIO_ENDPOINT is set, file uploads go to MinIO buckets.
# When not set, falls back to local FileSystemStorage (MEDIA_ROOT).
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
MINIO_PUBLIC_BUCKET = os.environ.get("MINIO_PUBLIC_BUCKET", "railtech-public")
MINIO_PRIVATE_BUCKET = os.environ.get("MINIO_PRIVATE_BUCKET", "railtech-private")
MINIO_TEMP_BUCKET = os.environ.get("MINIO_TEMP_BUCKET", "railtech-temp")
# Domain used for public URLs (served via nginx proxy)
# e.g. "localhost/storage" or "cdn.railtech.uz"
MINIO_PUBLIC_DOMAIN = os.environ.get("MINIO_PUBLIC_DOMAIN", "")
# External endpoint for presigned URLs (accessible from browser, not Docker internal)
# e.g. "http://localhost:9000" — defaults to MINIO_ENDPOINT if not set
MINIO_EXTERNAL_ENDPOINT = os.environ.get("MINIO_EXTERNAL_ENDPOINT", "") or MINIO_ENDPOINT

# Auth
AUTH_USER_MODEL = "accounts.CustomUser"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Своя компания — компания-владелец ERP, единственный продавец (BUSINESS §3.3, M1-ERP-02 волна 3).
# Точка истины — `core.tenant.own_company_id()`. Пусто → единственная активная компания-продавец
# с активными участниками (dev, тесты, свежий стенд); несколько таких без настройки — ошибка конфигурации.
OWN_COMPANY_ID = int(os.environ["OWN_COMPANY_ID"]) if os.environ.get("OWN_COMPANY_ID", "").strip() else None
