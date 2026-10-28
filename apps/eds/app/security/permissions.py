"""Коды прав EDS v1 (runbook волны 12 §2.2; `EdsPermission` в packages/contracts/openapi/eds.yaml): доменные коды,
`bus.manage` — «Журнал интеграций» шины (W13-A2, раздел `admin` каталога Платформы), `files.upload` — загрузка
своего файла (письмо директору к «Создать заявку», раздел `crm.clients` уровня `full`, D1-2b).

Права — данные: их вычисляет CRM из ролей Платформы по каталогу и публикует в `identity.user.*`
(`user.permissions.eds`); EDS хранит проекцию (`employees.permissions_eds`) и проверяет право на каждый запрос.
"""

from enum import StrEnum


class EdsPermission(StrEnum):
    LETTERS_READ = "letters.read"
    LETTERS_REGISTER = "letters.register"
    LETTERS_RESOLVE = "letters.resolve"
    MEMOS_CREATE = "memos.create"
    MEMOS_APPROVE = "memos.approve"
    APPROVALS_DECIDE = "approvals.decide"
    REGISTRY_READ = "registry.read"
    REGISTRY_EXPORT = "registry.export"
    PAYMENTS_CONFIRM = "payments.confirm"  # eds.payments full (решение архитектора, волна 12)
    BUS_MANAGE = "bus.manage"  # admin full: журнал шины и повторы (W13-A2)
    # crm.clients full: загрузить свой файл (письмо директору к «Создать заявку») и читать только свои файлы (D1-2b).
    FILES_UPLOAD = "files.upload"


KNOWN = frozenset(p.value for p in EdsPermission)


def known_permissions(codes: list[str]) -> list[str]:
    """Коды проекции, известные этой версии сервиса (неизвестные новые CRM хранятся, но не действуют)."""
    return sorted(c for c in set(codes) if c in KNOWN)
