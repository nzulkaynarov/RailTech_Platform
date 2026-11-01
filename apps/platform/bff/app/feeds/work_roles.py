"""Чья очередь у исполнения ERP (D2-8): роли «вида» без системной роли DIRECTOR.

Решение архитектора 2026-11-02 (PR #357; SPEC-v3 §4.1, роли пилота DECISIONS 2026-10-29 и
2026-11-01): в «Моих задачах» директора — только решения (резолюция, одобрение КП, служебки).
Строки исполнения — задания на расчёт, платёжки, счета к выставлению, договор и акт — системной
роли DIRECTOR не приходят, хотя её разделы `erp.calc` и `eds.projects` полные: директор
контролирует исполнение через сами разделы. У роли из шаблона и у созданной администратором роли с
теми же разделами строки есть — по каталогу; у сотрудника с директором и второй ролью (например,
менеджер-универсал) — по второй роли. Код системной роли в коде допустим (CONVENTIONS.md §2 п. 6).
"""

from app.feeds.models import QueueItemKind
from app.rbac import Access, RoleMatrix, View, allows, clean_access, merge
from app.rbac_generated import QUEUE

# Виды исполнения ERP, которых нет в очереди системного директора.
EXECUTION_KINDS: frozenset[str] = frozenset(
    {"calc_task", "confirm_payment", "issue_invoice", "issue_contract", "attach_scan", "issue_act"}
)
_DECIDER_ONLY = "DIRECTOR"


def _is_system_director(role: RoleMatrix) -> bool:
    return bool(getattr(role, "system", False)) and getattr(role, "code", None) == _DECIDER_ONLY


def executor_roles(view: View) -> tuple[RoleMatrix, ...]:
    return tuple(r for r in view.roles if not _is_system_director(r))


def executor_access(view: View) -> Access:
    """Объединённая матрица ролей исполнения (визы зон расчёта считаются по ней)."""
    return merge(executor_roles(view))


def wants_work(view: View, kind: QueueItemKind) -> bool:
    """Вид исполнения положен роли «вида», кроме системного директора; прочие — `view.wants`."""
    if kind not in EXECUTION_KINDS:
        return view.wants(kind)
    return any(_gives(role, kind) for role in executor_roles(view))


def work_role_id(view: View, kind: QueueItemKind) -> str:
    """`QueueItem.role_id` строки исполнения — первая роль исполнения, которая её даёт."""
    for role in executor_roles(view):
        if _gives(role, kind):
            return str(role.id)
    return ""


def _gives(role: RoleMatrix, kind: QueueItemKind) -> bool:
    resource, level = QUEUE[kind]
    return allows(clean_access(role.access), resource, level)
