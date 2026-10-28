"""Каталог прав EDS v1 (runbook волны 12 §2.2; `EdsPermission` в `openapi/eds.yaml`).

CRM вычисляет права EDS сотрудника из его ролей по каталогу `platform-rbac.yaml` (`backend.eds`,
сгенерированный `EDS_BACKEND`; функция — `platform_roles.eds_permissions_for`) и публикует их в
`identity.user.*` (`user.permissions.eds`). EDS своей модели ролей не имеет. Сверка снимка с
контрактом — `tests/unit/domain/test_eds_permissions.py`.
"""

from typing import Final

# Снимок `EdsPermission` — порядок как в `openapi/eds.yaml`.
EDS_PERMISSIONS: Final[tuple[str, ...]] = (
    "letters.read",
    "letters.register",
    "letters.resolve",
    "memos.create",
    "memos.approve",
    "approvals.decide",
    "registry.read",
    "registry.export",
    "payments.confirm",
    "bus.manage",
    "files.upload",
)
