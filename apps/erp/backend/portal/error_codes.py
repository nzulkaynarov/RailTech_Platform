"""Перечень кодов `detail` портала — зеркало `ErrorCode` в `packages/contracts/openapi/erp-portal.yaml` (Q-17).

Портал отдаёт клиенту только эти коды: `portal_exception_handler` приводит любой другой текст (английские фразы
DRF, «JSON parse error …») к коду по HTTP-статусу, а тест `portal/tests/test_error_codes.py` сверяет кортеж с
контрактом и перебирает коды, которые встречаются в исходниках `portal/`. Новый код сначала попадает в контракт
(правило «контракт раньше кода»), потом сюда.
"""

ERROR_CODES = (
    "UNAUTHORIZED",
    "INVALID_INIT_DATA",
    "FORBIDDEN",
    "NOT_FOUND",
    "MAGIC_LINK_EXPIRED",
    "IDEMPOTENCY_KEY_REQUIRED",
    "UNSUPPORTED_MEDIA_TYPE",
    "TOO_MANY_REQUESTS",
    "VALIDATION_ERROR",
    "REASON_REQUIRED",
    "INN_INVALID",
    "REQUISITES_MANAGED_BY_CRM",
    "TEAM_MEMBER_EXISTS",
    "CONTACT_EMAIL_REQUIRED",
    "CONTACT_CHANNEL_REQUIRED",
    "INVALID_CHANNEL",
    "FILE_REQUIRED",
    "FILE_TOO_LARGE",
    "UPLOAD_NOT_FOUND",
    "QUOTE_FINALIZED",
    "QUOTE_EXPIRED",
    "QUOTE_CODE_INVALID",
    "CONTRACT_FINALIZED",
    "ACT_FINALIZED",
    "DELIVERY_LINE_NOT_ACCEPTABLE",
    "DOCUMENT_PENDING",
    "DELIVERY_FAILED",
    "CONFLICT",
)

#: Код по HTTP-статусу для ошибок, у которых своего кода нет (чужие исключения DRF и Django).
FALLBACK_BY_STATUS = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",  # метода нет у пути — для клиента это «такого эндпоинта нет»; в контракте 405 не описан
    406: "UNSUPPORTED_MEDIA_TYPE",
    409: "CONFLICT",
    410: "MAGIC_LINK_EXPIRED",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
}
