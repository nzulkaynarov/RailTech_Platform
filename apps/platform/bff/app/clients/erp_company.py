"""Настройки своей компании в ERP для Admin · Компания (контракт BFF 0.7.0, tag `admin`).

Вызовы идут от имени сотрудника через `Authed.call` (токен ERP из сессии). Право на операцию решает
ERP (`settings.edit`, `settings.charge_templates`, администратор платформы); BFF проверяет раздел
каталога `company.settings`, находит id своей компании по профилю сотрудника в ERP и переводит
ответы и ошибки ERP в формат контракта.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.errors import PlatformError, backend_code, from_backend

Call = Callable[..., Awaitable[httpx.Response]]

API = "/api/v1/"
PAGE_SIZE = 200
MAX_PAGES = 25  # потолок обхода: 5000 строк на один справочник — заведомо больше любой настройки
SELLER_TYPE = "SUPPLIER"  # тип компании-продавца в ERP (accounts.constants.SELLER_COMPANY_TYPES)

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
    return sorted(k for k in body if k not in ("detail", "non_field_errors"))


def erp_error(response: httpx.Response) -> PlatformError:
    """Ответ ERP 4xx -> ошибка контракта (`source = erp`).

    400 у ERP — отказ проверки: 422 `VALIDATION_FAILED` с `details.reason` (код ERP в нижнем
    регистре) и `details.fields`; отказы «используется» и «уже рассмотрен» — 409 `CONFLICT`.
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
        """Id своей компании: основное членство сотрудника в ERP, иначе единственный продавец.

        Администратор (суперпользователь ERP) может работать без членства; тогда своя компания —
        единственная активная компания-продавец. Несколько кандидатов BFF не угадывает.
        """
        if self._company_id is not None:
            return self._company_id
        profile = await self.data("GET", "accounts/me/")
        found = _membership_company(profile if isinstance(profile, dict) else {})
        if found is None:
            sellers = rows_of(
                await self.data(
                    "GET",
                    "accounts/companies/",
                    params={"is_active": "true", "types__code": SELLER_TYPE, "page_size": 2},
                )
            )
            found = _int(sellers[0].get("id")) if len(sellers) == 1 else None
        if found is None:
            raise company_not_set()
        self._company_id = found
        return found

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
