"""Работа ERP в «Моих задачах» (D2-8, SPEC-v3 §1.2 п. 3, §4.1): расчёт, счета и платёжки, договор и
акт проекта.

BFF не решает, чья это работа и что ждёт: задания на расчёт «мои» по резолюции, состояние расчёта и
виз — ERP `GET /calc/tasks/?mine=1`; счета с платёжкой клиента и черновики к выставлению — доска ERP
`GET /finance/receivables/?tab=proofs|to_issue`; шаг договора и акта — проекты ERP
`GET /crm/projects/?step=CONTRACT|PAYMENT`. Вид строки попадает к сотруднику по секции `queue`
каталога (`calc_task` — `erp.calc`, `confirm_payment` и `issue_invoice` — `eds.payments`,
`issue_contract`, `attach_scan` и `issue_act` — `eds.projects`, все — полный). Одна строка — одно
действие над одним объектом: у роли, которая совмещает несколько видов, дублей нет. Каждая строка
ведёт на экран, где это действие делается.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.eds_payments import project_number as invoice_project_number
from app.eds_projects import project_number
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
        if allows(view.access, section, "full")
        for group in groups
    }


def _calc_action(task: dict[str, Any], mine: set[str]) -> str | None:
    """Что сделать с расчётом сейчас (состояние и визы — ERP); `None` — ход не за исполнителем
    (расчёт у директора, одобрен или отклонён)."""
    state = task.get("state")
    if state == "not_started":
        return "Начать расчёт по заявке"
    if state == "returned":
        return "Доработать расчёт по заявке"
    if state != "in_progress":
        return None
    raw_visas = task.get("visas")
    visas: dict[str, Any] = raw_visas if isinstance(raw_visas, dict) else {}
    if any(visas.get(group) == "waiting" for group in mine):
        return "Завизировать строки расчёта по заявке"
    states = [visas.get(group) for group in ("stock", "supply", "engineer")]
    if "done" in states and all(s in ("none", "done") for s in states):
        return "Отправить директору расчёт по заявке"
    return "Рассчитать заявку"


def calc_rows(snap: Snapshot, now: datetime, view: View, role_of: RoleOf) -> list[Work]:
    """Мои задания на расчёт: исполнителю по резолюции; «Завизировать» — если ждут визы строки зоны,
    которую даёт роль. Строка открывает расчёт заявки."""
    if not view.wants("calc_task") or not snap.calc_tasks:
        return []
    mine = _my_groups(view)
    role_id = role_of("calc_task")
    out: list[Work] = []
    for task in snap.calc_tasks:
        deal = task.get("deal")
        if not isinstance(deal, dict) or not isinstance(deal.get("id"), int):
            continue
        action = _calc_action(task, mine)
        if action is None:
            continue
        number = deal_number(deal)
        title = deal_title(deal)
        due_at = parse_deadline(task.get("due"))
        letter = task.get("letter_number")
        item = QueueItem(
            id=f"calc:{deal['id']}",
            role_id=role_id,
            kind="calc_task",
            title=f"{action} {number}",
            subtitle=join(
                str(deal.get("client_name") or "") or None,
                short(deal.get("title"), 70) or None,
                f"по письму {letter}" if isinstance(letter, str) and letter else None,
            ),
            due_label=due_label(due_at, now),
            due_at=due_at,
            object=calc_ref(number, title),
        )
        out.append((item, None))
    return out


def _invoice(raw: dict[str, Any]) -> tuple[int, str, str, str | None] | None:
    """(id, номер, ПР, клиент) строки доски ERP или `None` — строка битая."""
    invoice_id, number = raw.get("id"), raw.get("number")
    deal_id, year = raw.get("deal_id"), raw.get("deal_year")
    if not isinstance(invoice_id, int) or not isinstance(number, str) or not number:
        return None
    if not isinstance(deal_id, int) or not isinstance(year, int):
        return None
    client = str(raw.get("client_name") or "") or None
    return invoice_id, number, invoice_project_number(deal_id, year), client


def invoice_rows(snap: Snapshot, now: datetime, view: View, role_of: RoleOf) -> list[Work]:
    """Платёжки клиентов на подтверждение и счета-черновики к выставлению: строка открывает счёт в
    «Счетах и оплатах» с окном «Оплата». Срока у этой работы нет — бейдж «без срока»."""
    out: list[Work] = []
    if view.wants("confirm_payment"):
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
                title=f"Подтвердить оплату по счёту {number}",
                subtitle=join(
                    client,
                    money(raw.get("balance_due"), raw.get("currency")),
                    project,
                    f"платёжка {ago(received, now)}" if received else "платёжка получена",
                ),
                due_label="later",
                object=invoice_ref(invoice_id, number, client),
            )
            out.append((item, received))
    if view.wants("issue_invoice"):
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
                title=f"Выставить счёт {number}",
                subtitle=join(
                    client, money(raw.get("total_incl_vat"), raw.get("currency")), project
                ),
                due_label="later",
                object=invoice_ref(invoice_id, number, client),
            )
            out.append((item, None))
    return out


def _contract_step(row: RawRow) -> tuple[QueueItemKind, str, str] | None:
    """Шаг договора, который ждёт сотрудника: (вид, действие, подпись) или `None` — ход за
    клиентом или договор подписан."""
    contract = row.documents.contract
    if contract is None:
        if "no_contract" not in row.problems:
            return None
        return "issue_contract", "Сформировать проект договора по", "КП принято клиентом"
    if contract.status == "project" and not contract.sent_to_client:
        return (
            "issue_contract",
            f"Отправить клиенту проект договора {contract.number} по",
            ("проект не отправлен"),
        )
    if contract.status == "client_agreed":
        return (
            "issue_contract",
            f"Выставить у оператора договор {contract.number} по",
            ("клиент согласовал редакцию"),
        )
    if contract.status == "issued_at_operator":
        return (
            "attach_scan",
            f"Прикрепить скан подписанного договора {contract.number} по",
            ("договор выставлен у оператора"),
        )
    if contract.status == "rejected":
        return "issue_contract", f"Доработать договор {contract.number} по", "клиент отклонил"
    return None


def _act_step(row: RawRow) -> tuple[str, str] | None:
    """Акт к выпуску: заказчик вернул акт — выпустить заново; счета оплачены, акта нет — выпустить
    (выпуск по выставленному счёту и право решает ERP)."""
    act, invoice = row.documents.act, row.documents.invoice
    if act is not None and act.status == "returned":
        return f"Выпустить заново акт {act.number} по", "заказчик вернул акт"
    if act is None and row.client_status == "fulfilling" and invoice and invoice.status == "paid":
        return "Выпустить акт по", "счета оплачены"
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
    """Договор (сформировать, отправить, выставить у оператора, скан, доработать) и акт к выпуску:
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
        if step is None or not view.wants(step[0]):
            continue
        kind, action, why = step
        project = project_number(row.deal_id, row.created_at)
        contract = row.documents.contract
        client = row.company_name or None
        ref = (
            project_doc_ref("contract", contract.number, project, client, tab="contract")
            if contract is not None
            else project_doc_ref("project", project, project, client, tab="contract")
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
    if view.wants("issue_act"):
        role_id = role_of("issue_act")
        for row in _rows(snap.projects_payment):
            if row.step != "PAYMENT":
                continue
            act_step = _act_step(row)
            if act_step is None:
                continue
            action, why = act_step
            project = project_number(row.deal_id, row.created_at)
            client = row.company_name or None
            act = row.documents.act
            ref = (
                project_doc_ref("act", act.number, project, client, tab="act")
                if act is not None
                else project_doc_ref("project", project, project, client, tab="act")
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
