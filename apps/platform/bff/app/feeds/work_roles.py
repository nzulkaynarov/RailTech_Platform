"""Чья очередь у исполнения ERP (D2-8): роли «вида» без роли «решающего».

Решение архитектора 2026-11-02 (PR #357; SPEC-v3 §4.1, роли пилота DECISIONS 2026-10-29 и
2026-11-01): в «Моих задачах» директора — только решения (резолюция, одобрение КП, служебки).
Строки исполнения — задания на расчёт, платёжки, счета к выставлению, договор и акт — роли
«решающего» не приходят, хотя её разделы `erp.calc` и `eds.projects` полные: решающий
контролирует исполнение через сами разделы.

ЕВ-5а (отчёт 2026-11-22, §4.3 строка 1): «решающий» — признак набора прав, а не названия роли.
Роль решающая, когда держит оба раздела одобрения полным уровнем: одобрение КП (`eds.drafts`) и
согласование служебок (`eds.memo.approve`). В каталоге это только системный DIRECTOR, но созданная
администратором роль (заместитель по зоне) с теми же двумя разделами получает то же поведение.
У сотрудника с такой ролью и второй ролью (например, менеджер-универсал) строки исполнения — по
второй роли. Названия и код роли в этом файле не используются.
"""

from app.feeds.models import QueueItemKind
from app.rbac import Access, RoleMatrix, View, allows, clean_access, merge
from app.rbac_generated import QUEUE

# Виды исполнения ERP, которых нет в очереди роли «решающего».
EXECUTION_KINDS: frozenset[str] = frozenset(
    {
        "calc_task",
        "confirm_payment",
        "issue_invoice",
        "issue_contract",
        "attach_scan",
        "issue_act",
        "order_shortage",
        "ship_project",
    }
)
# Разделы одобрения: держатель обоих — «решающий», у него в очереди только решения.
DECIDER_SECTIONS: tuple[str, ...] = ("eds.drafts", "eds.memo.approve")


def is_decider_role(role: RoleMatrix) -> bool:
    access = clean_access(role.access)
    return all(allows(access, section, "full") for section in DECIDER_SECTIONS)


def executor_roles(view: View) -> tuple[RoleMatrix, ...]:
    return tuple(r for r in view.roles if not is_decider_role(r))


def executor_access(view: View) -> Access:
    """Объединённая матрица ролей исполнения (визы зон расчёта считаются по ней)."""
    return merge(executor_roles(view))


def wants_work(view: View, kind: QueueItemKind) -> bool:
    """Вид исполнения положен роли «вида», кроме роли «решающего»; прочие — `view.wants`."""
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
