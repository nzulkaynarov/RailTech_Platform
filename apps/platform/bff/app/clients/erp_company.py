"""Настройки своей компании в ERP для Admin · Компания (контракт BFF 0.8.0, tag `admin`).

Вызовы идут от имени сотрудника через `Authed.call` (токен ERP из сессии). Право на операцию решает
ERP (`settings.edit`, `settings.charge_templates`, администратор платформы); BFF проверяет раздел
каталога `company.settings`, находит id своей компании по профилю сотрудника в ERP и переводит
ответы и ошибки ERP в формат контракта.
"""

import base64
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from app.errors import PlatformError, backend_code, from_backend

Call = Callable[..., Awaitable[httpx.Response]]

API = "/api/v1/"
PAGE_SIZE = 200
MAX_PAGES = 25  # потолок обхода: 5000 строк на один справочник — заведомо больше любой настройки

COMPANY_NOT_SET_MESSAGE = (
    "Своя компания в ERP ещё не создана. Создайте её в мастере первого запуска и обновите страницу."
)

# Отказы ERP, которые для сотрудника не «ошибка полей», а конфликт с данными:
# код ERP -> (причина, текст).
_CONFLICTS: dict[str, tuple[str, str]] = {
    "LOOKUP_IN_USE": (
        "lookup_in_use",
        "Строка используется в документах и данных. Отключите её вместо удаления.",
    ),
    "CATEGORY_HAS_CHILDREN": (
        "category_has_children",
        "У категории есть подкатегории. Сначала перенесите или удалите их.",
    ),
    "CATEGORY_REQUEST_ALREADY_REVIEWED": (
        "already_reviewed",
        "Запрос уже рассмотрен. Обновите список.",
    ),
    "TEMPLATE_IN_USE": (
        "template_in_use",
        "По шаблону уже оформлены документы. Отключите его вместо удаления.",
    ),
    "DOC_PREFIX_TAKEN": (
        "doc_prefix_taken",
        "Такой префикс нумерации уже занят другой компанией. Выберите другой.",
    ),
}
# Код ERP -> поле контракта (`details.fields`), когда отказ относится к одному полю.
_FIELD_OF: dict[str, str] = {
    "INVALID_NUMBERING_PATTERN": "pattern",
    "DOC_PREFIX_TAKEN": "prefix",
    "BAD_CURRENCY": "default_cost_currency",
    "BAD_DELIVERY_BASIS": "default_delivery_basis",
    "BAD_PRICE_VISIBILITY": "catalog_price_visibility",
    "BAD_PUBLISH_THRESHOLD": "catalog_publish_threshold",
    "BAD_FX_RATE_MAX_AGE_DAYS": "fx_rate_max_age_days",
    "REASON_REQUIRED": "reason",
    "CATEGORY_REQUIRED": "category_id",
    "CATEGORY_REQUEST_NAME_REQUIRED": "name",
}
_CODE = re.compile(r"^[A-Z][A-Z0-9_]*(:.*)?$")

# Публичные логотипы компании и бланка в хранилище ERP (core/urls.py: `public-media`);
# других путей BFF не запрашивает.
_MEDIA_PATH = re.compile(r"^/media/companies/\d+/(?:logo|doc-profile/logo)/[^/]+$")
LOGO_IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
)
# Ссылки на эти логотипы в HTML образца документа: ERP строит их от своего адреса,
# а он для браузера внутренний.
_MEDIA_SRC = re.compile(r"""(src=["'])(?:https?://[^"'/\s]+)?(/media/[^"'\s>]+)(["'])""")
MAX_INLINE_IMAGES = 4
MAX_LOGO_FILE_BYTES = 5 * 1024 * 1024  # потолок файла логотипа, как у ERP
MAX_INLINE_BYTES = 2 * 1024 * 1024


def media_path(url: Any) -> str | None:
    """Путь `/media/...` логотипа из адреса ERP; любой другой путь — `None`."""
    if not isinstance(url, str) or not url:
        return None
    path = urlparse(url).path
    return path if _MEDIA_PATH.match(path) else None


def company_not_set() -> PlatformError:
    return PlatformError("COMPANY_NOT_SET", COMPANY_NOT_SET_MESSAGE, status_code=409, source="erp")


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _validation_fields(body: Any) -> list[str]:
    """Поля DRF-ошибки `{"поле": ["текст"]}`; `detail` и `non_field_errors` полями не считаются."""
    if not isinstance(body, dict):
        return []
    return sorted(k for k in body if k not in ("detail", "non_field_errors", "missing_blocks"))


def _missing_blocks(body: Any) -> list[dict[str, str]]:
    """Недостающие блоки договора из отказа ERP `TEMPLATE_MISSING_REQUIRED_BLOCKS`: `[{code, label}]`."""
    raw = body.get("missing_blocks") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        return []
    return [
        {"code": item["code"], "label": item["label"]}
        for item in raw[:20]
        if isinstance(item, dict)
        and isinstance(item.get("code"), str)
        and isinstance(item.get("label"), str)
    ]


def erp_error(response: httpx.Response) -> PlatformError:
    """Ответ ERP 4xx -> ошибка контракта (`source = erp`).

    400 у ERP — отказ проверки: 422 `VALIDATION_FAILED` с `details.reason` (код ERP в нижнем
    регистре) и `details.fields`, у `TEMPLATE_MISSING_REQUIRED_BLOCKS` — ещё `details.missing_blocks`
    (`[{code, label}]`); отказы «используется» и «уже рассмотрен» — 409 `CONFLICT`.
    403, 404, 409 и 429 переводит общий `from_backend`.
    """
    if response.status_code not in (400, 422):
        return from_backend("erp", response)
    body = _body(response)
    code = backend_code(response)
    details: dict[str, Any] = {"backend_status": response.status_code}
    if code is not None:
        details["backend_code"] = code
    erp_code = code.split(":", 1)[0] if code and _CODE.match(code) else None
    if erp_code in _CONFLICTS:
        reason, message = _CONFLICTS[erp_code]
        details["reason"] = reason
        if erp_code in _FIELD_OF:
            details["fields"] = [_FIELD_OF[erp_code]]
        return PlatformError("CONFLICT", message, status_code=409, source="erp", details=details)
    fields = _validation_fields(body)
    if erp_code is not None:
        details["reason"] = erp_code.lower()
        if erp_code in _FIELD_OF:
            fields = [_FIELD_OF[erp_code]]
    if fields:
        details["fields"] = fields
    if erp_code == "TEMPLATE_MISSING_REQUIRED_BLOCKS" and (blocks := _missing_blocks(body)):
        details["missing_blocks"] = blocks
    return PlatformError(
        "VALIDATION_FAILED",
        "Проверьте заполнение полей.",
        status_code=422,
        source="erp",
        details=details,
    )


def rows_of(data: Any) -> list[dict[str, Any]]:
    """Строки ответа списка: массив или страница DRF (`results`)."""
    if isinstance(data, dict):
        data = data.get("results", [])
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


class ErpCompany:
    """Один запрос Admin · Компания: вызовы ERP от имени сотрудника и своя компания (лениво)."""

    def __init__(self, call: Call) -> None:
        self._call = call
        self._company_id: int | None = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        response = await self._call(
            "erp",
            method,
            f"{API}{path}",
            json=json,
            params=params,
            content=content,
            content_type=content_type,
        )
        if response.status_code >= 400:
            raise erp_error(response)
        return response

    async def data(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        return (await self.request(method, path, json=json, params=params)).json()

    async def pages(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Все строки списка ERP: страницы DRF обходятся до конца, массив отдаётся как есть."""
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            query = {"page": page, "page_size": PAGE_SIZE, **(params or {})}
            data = await self.data("GET", path, params=query)
            rows.extend(rows_of(data))
            if not (isinstance(data, dict) and data.get("next")):
                break
        return rows

    async def company_id(self) -> int:
        """Id своей компании: `own_company_id` из `setup/status/` ERP (core.tenant).

        Администратор ERP (суперпользователь) работает без членства: профиль сотрудника не годится.
        Ответ без поля (старая ERP) — основное членство сотрудника из `accounts/me/`. `null` — своей
        компании ещё нет: 409 `COMPANY_NOT_SET`.
        """
        if self._company_id is not None:
            return self._company_id
        status = await self.data("GET", "setup/status/")
        if isinstance(status, dict) and "own_company_id" in status:
            found = _int(status["own_company_id"])
        else:
            profile = await self.data("GET", "accounts/me/")
            found = _membership_company(profile if isinstance(profile, dict) else {})
        if found is None:
            raise company_not_set()
        self._company_id = found
        return found

    async def media(self, url: Any) -> httpx.Response | None:
        """Файл логотипа по адресу из ответа ERP (только публичные пути логотипов) или `None`."""
        path = media_path(url)
        if path is None:
            return None
        # Только файлы своей компании: чужой `companies/<id>/...` BFF не запрашивает.
        own = await self.company_id()
        if not path.startswith(f"/media/companies/{own}/"):
            return None
        response = await self._call("erp", "GET", path)
        if response.status_code != 200 or len(response.content) > MAX_LOGO_FILE_BYTES:
            return None
        if (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
            not in LOGO_IMAGE_TYPES
        ):
            return None
        return response

    async def inline_logos(self, html: str) -> str:
        """Образец документа: логотипы ERP — данными в самом HTML (CSP чужих не пускает)."""
        replaced: dict[str, str] = {}
        for match in _MEDIA_SRC.finditer(html):
            path = match.group(2)
            if path in replaced or len(replaced) >= MAX_INLINE_IMAGES:
                continue
            file = await self.media(path)
            if file is None or len(file.content) > MAX_INLINE_BYTES:
                continue
            mime = file.headers["content-type"].split(";")[0].strip().lower()
            replaced[path] = f"data:{mime};base64,{base64.b64encode(file.content).decode('ascii')}"
        return _MEDIA_SRC.sub(
            lambda m: (
                f"{m.group(1)}{replaced[m.group(2)]}{m.group(3)}"
                if m.group(2) in replaced
                else m.group(0)
            ),
            html,
        )

    async def company_path(self, suffix: str = "") -> str:
        return f"accounts/companies/{await self.company_id()}/{suffix}"


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _membership_company(profile: dict[str, Any]) -> int | None:
    primary = profile.get("primary_company")
    if isinstance(primary, dict) and (found := _int(primary.get("id"))) is not None:
        return found
    memberships = [
        m for m in profile.get("memberships") or [] if isinstance(m, dict) and m.get("is_active")
    ]
    memberships.sort(key=lambda m: not m.get("is_primary"))
    return _int(memberships[0].get("company")) if memberships else None
