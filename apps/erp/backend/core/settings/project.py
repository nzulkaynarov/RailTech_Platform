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
    # Письма клиенту портала идут на языке контакта (ru/uz/en, FIX-23): каталог uz пока покрывает только их.
    ("uz", _("Oʻzbekcha")),
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

# ─── Файлы: S3 (RustFS) ───────────────────────────────────────────────────────────────────
# Все файлы ERP (PDF, сканы, загрузки портала, картинки каталога) лежат в бакетах RustFS: `erp-private` (по умолчанию),
# `erp-public` (только то, что открыто без входа: картинки, логотипы, аватары), `erp-temp`. Имена переменных
# MINIO_* исторические, хранилище — любое S3-совместимое. Адрес RustFS наружу не публикуется: браузер в него не ходит,
# файлы выдаёт сам Django (`core.file_streaming`, `core.storage.serve_public_media`).
# Без MINIO_ENDPOINT работает локальная файловая система (MEDIA_ROOT) — только при DJANGO_DEBUG=true (dev, тесты);
# вне DEBUG ERP без S3 не стартует: молча писать на диск контейнера нельзя (файлы пропадут при пересоздании).
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
MINIO_PUBLIC_BUCKET = os.environ.get("MINIO_PUBLIC_BUCKET", "erp-public")
MINIO_PRIVATE_BUCKET = os.environ.get("MINIO_PRIVATE_BUCKET", "erp-private")
MINIO_TEMP_BUCKET = os.environ.get("MINIO_TEMP_BUCKET", "erp-temp")

_MISSING_S3_SETTINGS = [
    name
    for name, value in (
        ("MINIO_ENDPOINT", MINIO_ENDPOINT),
        ("MINIO_ACCESS_KEY", MINIO_ACCESS_KEY),
        ("MINIO_SECRET_KEY", MINIO_SECRET_KEY),
    )
    if not value
]
if _MISSING_S3_SETTINGS and not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "S3 file storage is required when DJANGO_DEBUG is off (ERP does not write files to the local disk): "
        "set " + ", ".join(_MISSING_S3_SETTINGS)
    )

# Auth
AUTH_USER_MODEL = "accounts.CustomUser"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Своя компания — компания-владелец ERP, единственный продавец (BUSINESS §3.3, M1-ERP-02 волна 3).
# Точка истины — `core.tenant.own_company_id()`. Пусто → единственная активная компания-продавец
# с активными участниками (dev, тесты, свежий стенд); несколько таких без настройки — ошибка конфигурации.
OWN_COMPANY_ID = int(os.environ["OWN_COMPANY_ID"]) if os.environ.get("OWN_COMPANY_ID", "").strip() else None

# Курс на дату КП (M1-ERP-08): курс берётся с ближайшей прошедшей даты (ЦБ не публикует курс в
# выходные), но не старше стольких календарных дней; старее — «курса нет» (FX_RATE_MISSING блокирует
# отправку на согласование, PDF и отправку клиенту, пока ЦБ не обновит курс или финансист не задаст
# курс КП вручную). Политика курса переедет в «Настройки» ERP (M1-ERP-09).
FX_RATE_MAX_AGE_DAYS = int((os.environ.get("FX_RATE_MAX_AGE_DAYS") or "7").strip() or "7")
