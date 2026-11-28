"""Работа ERP в «Моих задачах» (D2-8, SPEC-v3 §1.2 п. 3, §4.1): расчёт, счета и платёжки, договор и
акт проекта.

BFF не решает, чья это работа и что ждёт: задания на расчёт «мои» по резолюции, состояние расчёта и
виз — ERP `GET /calc/tasks/?mine=1`; счета с платёжкой клиента и черновики к выставлению — доска ERP
`GET /finance/receivables/?tab=proofs|to_issue`; шаг договора и акта — проекты ERP
`GET /crm/projects/?step=CONTRACT|PAYMENT`. Вид строки попадает к сотруднику по секции `queue`
каталога (`calc_task` — `erp.calc`, `confirm_payment` и `issue_invoice` — `eds.payments`,
`issue_contract`, `attach_scan` и `issue_act` — `eds.projects`, все — полный). Одна строка — одно
действие над одним объектом: у роли, которая совмещает несколько видов, дублей нет. Каждая строка
ведёт на экран, где это действие делается. Системному директору исполнения нет — только решения
(`feeds/work_roles.py`, решение архитектора 2026-11-02).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.eds_payments import project_number as invoice_project_number
from app.eds_projects import project_number
from app.feeds.lang import tr
from app.feeds.models import QueueItem, QueueItemKind
from app.feeds.numbers import (
    calc_ref,
    deal_number,
    deal_title,
    invoice_ref,
    project_doc_ref,
)
from app.feeds.snapshot import Snapshot
from app.feeds.text import ago, due_label, join, money, parse_deadline, parse_dt, short
from app.feeds.work_roles import executor_access, wants_work
from app.rbac import View, allows
from app.schemas_eds_projects import RawRow

RoleOf = Callable[[QueueItemKind], str]
Work = tuple[QueueItem, datetime | None]

# Группы виз расчёта по зоне строки: товары — склад и снабжение, услуги — гл. инженер (D2-1).
_ZONE_GROUPS = {"erp.calc.goods": ("stock", "supply"), "erp.calc.services": ("engineer",)}


def _my_groups(view: View) -> set[str]:
    return {
        group
        for section, groups in _ZONE_GROUPS.items()
        if allows(executor_access(view), section, "full")
        for group in groups
    }


def _calc_action(task: dict[str, Any], mine: set[str]) -> str | None:
    """Что сделать с расчётом сейчас (состояние и визы — ERP); `None` — ход не за исполнителем
    (расчёт у директора, одобрен или отклонён)."""
    state = task.get("state")
    if state == "not_started":
        return tr(
            "Начать расчёт по заявке",
            "Ariza böyiça hisob-kitobni boşlaş",
            "Start the costing for request",
        )
    if state == "returned":
        return tr(
            "Доработать расчёт по заявке",
            "Ariza böyiça hisob-kitobni qayta işlaş",
            "Rework the costing for request",
        )
    if state != "in_progress":
        return None
    raw_visas = task.get("visas")
    visas: dict[str, Any] = raw_visas if isinstance(raw_visas, dict) else {}
    if any(visas.get(group) == "waiting" for group in mine):
        return tr(
            "Завизировать строки расчёта по заявке",
            "Ariza böyiça hisob-kitob qatorlarini vizalaş",
            "Visa the costing lines for request",
        )
    states = [visas.get(group) for group in ("stock", "supply", "engineer")]
    if "done" in states and all(s in ("none", "done") for s in states):
        return tr(
            "Отправить на утверждение расчёт по заявке",
            "Ariza böyiça hisob-kitobni tasdiqlaşga yuboriş",
            "Send the costing for approval for request",
        )
    return tr("Рассчитать заявку", "Arizani hisoblaş", "Cost request")


def _client_rejected(task: dict[str, Any]) -> bool:
    return task.get("state") == "rejected" and task.get("rejected_by") == "client"


def calc_rows(snap: Snapshot, now: datetime, view: View, role_of: RoleOf) -> list[Work]:
    """Мои задания на расчёт: исполнителю по резолюции; «Завизировать» — если ждут визы строки зоны,
    которую даёт роль. Строка открывает расчёт заявки."""
    if not wants_work(view, "calc_task") or not snap.calc_tasks:
        return []
    mine = _my_groups(view)
    # Решение после отказа клиента («Новая версия КП» или «Отказ по заявке», D26G-3) — менеджеру
    # заявки: роли с клиентами на полном доступе, а не снабженцу и гл. инженеру.
    decides = allows(executor_access(view), "crm.clients", "full")
    role_id = role_of("calc_task")
    out: list[Work] = []
    for task in snap.calc_tasks:
        deal = task.get("deal")
        if not isinstance(deal, dict) or not isinstance(deal.get("id"), int):
            continue
        rejected = _client_rejected(task)
        if rejected and not decides:
            continue
        action = (
            tr(
                "Клиент отклонил КП по заявке",
                "Mijoz ariza böyiça TTni rad etdi",
                "The client declined the quote for request",
            )
            if rejected
            else _calc_action(task, mine)
        )
        if action is None:
            continue
        number = deal_number(deal)
        title = deal_title(deal)
        due_at = parse_deadline(task.get("due"))
        letter = task.get("letter_number")
        reason = short(task.get("reject_reason"), 140) if rejected else None
        item = QueueItem(
            id=f"calc:{deal['id']}",
            role_id=role_id,
            kind="calc_task",
            title=f"{action} {number}",
            subtitle=join(
                (
                    tr(f"Причина: {reason}", f"Sabab: {reason}", f"Reason: {reason}")
                    if reason
                    else tr("Причина не указана", "Sabab körsatilmagan", "No reason given")
                )
                if rejected
                else None,
                str(deal.get("client_name") or "") or None,
                short(deal.get("title"), 70) or None,
                tr(f"по письму {letter}", f"{letter} xati böyiça", f"on letter {letter}")
                if isinstance(letter, str) and letter
                else None,
            ),
            due_label=due_label(due_at, now),
            due_at=due_at,
            object=calc_ref(number, title, is_test=bool(deal.get("is_test"))),
        )
        out.append((item, None))
    return out


def _invoice(raw: dict[str, Any]) -> tuple[int, str, str, str | None] | None:
    """(id, номер, ПР, клиент) строки доски ERP или `None` — строка битая."""
    invoice_id, number = raw.get("id"), raw.get("number")
    deal_id, deal_number = raw.get("deal_id"), raw.get("deal_number")
    if not isinstance(invoice_id, int) or not isinstance(number, str) or not number:
        return None
    if not isinstance(deal_id, int):
        return None
    client = str(raw.get("client_name") or "") or None
    project = invoice_project_number(deal_id, deal_number if isinstance(deal_number, str) else "")
    return invoice_id, number, project, client


def invoice_rows(snap: Snapshot, now: datetime, view: View, role_of: RoleOf) -> list[Work]:
    """Платёжки клиентов на подтверждение и счета-черновики к выставлению: строка открывает счёт в
    «Счетах и оплатах» с окном «Оплата». Срока у этой работы нет — бейдж «без срока»."""
    out: list[Work] = []
    if wants_work(view, "confirm_payment"):
        role_id = role_of("confirm_payment")
        for raw in snap.invoices_with_proofs:
            parsed = _invoice(raw)
            if parsed is None or raw.get("has_pending_proof") is not True:
                continue
            invoice_id, number, project, client = parsed
            received = parse_dt(raw.get("proof_received_at"))
            item = QueueItem(
                id=f"invoice:{invoice_id}:confirm",
                role_id=role_id,
                kind="confirm_payment",
                title=tr(
                    f"Подтвердить оплату по счёту {number}",
                    f"{number} hisob böyiça tölovni tasdiqlaş",
                    f"Confirm payment for invoice {number}",
                ),
                subtitle=join(
                    client,
                    money(raw.get("balance_due"), raw.get("currency")),
                    project,
                    tr(
                        f"платёжное поручение {ago(received, now)}",
                        f"tölov topşiriqnomasi {ago(received, now)}",
                        f"payment order {ago(received, now)}",
                    )
                    if received
                    else tr(
                        "платёжное поручение получено",
                        "tölov topşiriqnomasi olindi",
                        "payment order received",
                    ),
                ),
                due_label="later",
                object=invoice_ref(invoice_id, number, client),
            )
            out.append((item, received))
    if wants_work(view, "issue_invoice"):
        role_id = role_of("issue_invoice")
        for raw in snap.invoices_to_issue:
            parsed = _invoice(raw)
            if parsed is None or raw.get("display_status") != "draft":
                continue
            invoice_id, number, project, client = parsed
            item = QueueItem(
                id=f"invoice:{invoice_id}:issue",
                role_id=role_id,
                kind="issue_invoice",
                title=tr(
                    f"Выставить счёт {number}",
                    f"{number} hisobni çiqariş",
                    f"Issue invoice {number}",
                ),
                subtitle=join(
                    client, money(raw.get("total_incl_vat"), raw.get("currency")), project
                ),
                due_label="later",
                object=invoice_ref(invoice_id, number, client),
            )
            out.append((item, None))
    return out


#: Х-1: причины, при которых шаг за сотрудником — отправить договор «На подпись».
_VISAS_TO_REQUEST = {"visas_not_requested", "visas_declined", "visas_returned", "no_visa_holder"}
_BLOCKER_WHY = {
    "visas_not_requested": ("визы не запрошены", "vizalar söralmagan", "visas not requested"),
    "visas_declined": (
        "договор не принят на визы",
        "şartnoma vizaga qabul qilinmadi",
        "the contract was not accepted for visas",
    ),
    "visas_returned": ("виза возвращена", "viza qaytarilgan", "a visa was returned"),
    "no_visa_holder": (
        "некому поставить визу",
        "viza qöyadigan kişi yöq",
        "nobody can give a visa",
    ),
    "visas_pending": ("визы собираются", "vizalar yiğilmoqda", "visas are being collected"),
}


def _contract_step(row: RawRow) -> tuple[QueueItemKind, str, str] | None:
    """Шаг договора, который ждёт сотрудника: (вид, действие, подпись) или `None` — ход за
    клиентом или договор подписан."""
    contract = row.documents.contract
    if contract is None:
        if "no_contract" not in row.problems:
            return None
        return (
            "issue_contract",
            tr(
                "Сформировать проект договора по",
                "Şartnoma loyihasini tayyorlaş:",
                "Prepare the draft contract for",
            ),
            tr("КП принято клиентом", "Mijoz TTni qabul qildi", "the client accepted the quote"),
        )
    if contract.status == "project" and not contract.sent_to_client:
        # Х-1 и ДОК-10: шаг по факту единой проверки ERP (`send_blocker_code`), не по статусу.
        code = contract.send_blocker_code
        if code == "CONTRACT_DEVIATION_PENDING":
            return None  # ход за держателем «Право»: у отправителя строки нет
        if code == "CONTRACT_NEEDS_OUR_SIGNATURE":
            return (
                "issue_contract",
                tr(
                    f"Подписать от компании договор {contract.number} по",
                    f"{contract.number} şartnomani kompaniya nomidan imzolaş:",
                    f"Sign contract {contract.number} for the company —",
                ),
                tr(
                    "до отправки клиенту нужна наша подпись",
                    "mijozga yuborişdan oldin bizning imzo kerak",
                    "our signature is needed before it goes to the client",
                ),
            )
        if code is not None:
            return (
                "issue_contract",
                (
                    tr(
                        f"Отправить на визы договор {contract.number} по",
                        f"{contract.number} şartnomani vizaga yuboriş:",
                        f"Send contract {contract.number} for visas —",
                    )
                    if code in _VISAS_TO_REQUEST
                    else tr(
                        f"Ждёт виз договор {contract.number} по",
                        f"{contract.number} şartnoma vizalarni kutmoqda:",
                        f"Contract {contract.number} awaits visas —",
                    )
                ),
                tr(*_BLOCKER_WHY[code]),
            )
        return (
            "issue_contract",
            tr(
                f"Отправить клиенту проект договора {contract.number} по",
                f"{contract.number} şartnoma loyihasini mijozga yuboriş:",
                f"Send the draft of contract {contract.number} to the client —",
            ),
            tr("проект не отправлен", "loyiha yuborilmagan", "the draft has not been sent"),
        )
    if contract.status in ("client_agreed", "issued_at_operator"):
        # ДП-1: согласован — «Ожидает подписания»; сотрудник отмечает подпись сканом или заметкой
        return (
            "attach_scan",
            tr(
                f"Отметить подписанным договор {contract.number} по",
                f"{contract.number} şartnomani imzolangan deb belgilaş:",
                f"Mark contract {contract.number} as signed —",
            ),
            tr(
                "договор ожидает подписания",
                "şartnoma imzolaşni kutmoqda",
                "the contract awaits signing",
            ),
        )
    if contract.status == "rejected":
        return (
            "issue_contract",
            tr(
                f"Доработать договор {contract.number} по",
                f"{contract.number} şartnomani qayta işlaş:",
                f"Rework contract {contract.number} —",
            ),
            tr("клиент отклонил", "mijoz rad etdi", "the client declined"),
        )
    return None


def _act_step(row: RawRow) -> tuple[str, str] | None:
    """Акт к выпуску: заказчик вернул акт — выпустить заново; счета оплачены, акта нет — выпустить
    (выпуск по выставленному счёту и право решает ERP)."""
    act, invoice = row.documents.act, row.documents.invoice
    if act is not None and act.status == "returned":
        return (
            tr(
                f"Выпустить заново акт {act.number} по",
                f"{act.number} aktni qaytadan çiqariş:",
                f"Reissue act {act.number} —",
            ),
            tr("заказчик вернул акт", "buyurtmaçi aktni qaytardi", "the customer returned the act"),
        )
    # Акт — после доставки: блокер считает ERP (`not_delivered`), своего правила у очереди нет.
    paid = row.client_status == "fulfilling" and invoice is not None and invoice.status == "paid"
    if act is None and paid and row.act_blocker is None:
        return (
            tr("Выпустить акт по", "Aktni çiqariş:", "Issue the act for"),
            tr(
                "товар доставлен, счета оплачены",
                "tovar yetkazildi, hisoblar tölangan",
                "goods delivered, invoices paid",
            ),
        )
    return None


def _rows(raw: list[dict[str, Any]]) -> list[RawRow]:
    out: list[RawRow] = []
    for item in raw:
        try:
            out.append(RawRow.model_validate(item))
        except ValidationError:
            continue
    return out


def project_rows(snap: Snapshot, now: datetime, view: View, role_of: RoleOf) -> list[Work]:
    """Договор (сформировать, отправить, выставить в ЭДО, скан, доработать) и акт к выпуску:
    строка открывает проект на вкладке «Договор» или «Акт»."""
    del now
    out: list[Work] = []
    seen: set[str] = set()

    def add(item: QueueItem, since: datetime | None) -> None:
        if item.id not in seen:
            seen.add(item.id)
            out.append((item, since))

    for row in _rows(snap.projects_contract):
        if row.step != "CONTRACT":
            continue
        step = _contract_step(row)
        if step is None or not wants_work(view, step[0]):
            continue
        kind, action, why = step
        project = project_number(row)
        contract = row.documents.contract
        client = row.company_name or None
        ref = (
            project_doc_ref("contract", contract.number, project, client)
            if contract is not None
            else project_doc_ref("project", project, project, client)
        )
        item = QueueItem(
            id=f"project:{row.deal_id}:contract",
            role_id=role_of(kind),
            kind=kind,
            title=f"{action} {project}",
            subtitle=join(client, short(row.title, 70) or None, why),
            due_label="later",
            object=ref,
        )
        add(item, row.created_at)
    if wants_work(view, "issue_act"):
        role_id = role_of("issue_act")
        for row in _rows(snap.projects_payment):
            if row.step != "PAYMENT":
                continue
            act_step = _act_step(row)
            if act_step is None:
                continue
            action, why = act_step
            project = project_number(row)
            client = row.company_name or None
            act = row.documents.act
            ref = (
                project_doc_ref("act", act.number, project, client)
                if act is not None
                else project_doc_ref("project", project, project, client)
            )
            item = QueueItem(
                id=f"project:{row.deal_id}:act",
                role_id=role_id,
                kind="issue_act",
                title=f"{action} {project}",
                subtitle=join(client, short(row.title, 70) or None, why),
                due_label="later",
                object=ref,
            )
            add(item, row.created_at)
    return out
