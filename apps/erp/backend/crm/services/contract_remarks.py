"""ДП-1: замечания контрагента к редакции договора — получить, показать разбор, согласовать, решить (владелец 2026-11-25).

Путь: контрагент в Кабинете жмёт «Есть замечания» (одно окно: комментарий + при желании своя редакция DOCX/XLSX) →
система считает, что изменилось (`contract_compare`), и пишет замечания → ответственным приходит уведомление с кратким
разбором → каждый отвечает «Согласен» / «Не согласен» (решений «по каждому пункту» нет) → все согласны: принята редакция
контрагента, договор «Согласован» (PENDING_MANAGER, у нас «Ожидает подписания»); есть разногласие: решает директор —
держатель права `contract.sign` («чей голос решающий» — это право, назначается как остальные права сотрудника): принять
редакцию контрагента или ответить своей (текст ответа обязателен).

Кто отвечает за договор (и должен ответить): автор КП, держатели `contract.approve_template` («Право») и `contract.sign`
(директор). Статус договора не заводит новых кодов: пока замечания открыты — договор остаётся «у контрагента»
(PENDING_CLIENT), факт открытых замечаний — строка `ContractRemark` без `resolution`.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple
from urllib.parse import quote as url_quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.validators import assert_content_matches_extension

from ..constants import ContractStatusCode as S
from ..models import ActivityLog, Contract, ContractRemark, ContractRemarkVote
from . import contract_compare

COMMENT_MAX = 4000
REMARK_EXTENSIONS = frozenset({".docx", ".xlsx"})
DECIDE_PERMISSION = "contract.sign"
REVIEW_PERMISSIONS = ("contract.approve_template", DECIDE_PERMISSION)


# ── Кто отвечает ───────────────────────────────────────────────────────────────────────────────────────────────────


def _holders(permission: str) -> list:
    from accounts.models import CustomUser as User
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    company_id = own_company_id()
    users = User.objects.filter(
        is_active=True, memberships__company_id=company_id, memberships__is_active=True
    ).distinct()
    return [u for u in users if member_has_permission(u, company_id, permission)]


def deciders(contract) -> list:
    """Директор: тот, чей голос решает при разногласии — держатели `contract.sign`."""
    return _holders(DECIDE_PERMISSION)


def reviewers(contract) -> list:
    """Все, кто отвечает за договор: автор КП и держатели прав «Право» и подписи, по одному разу."""
    people, seen = [], set()
    author = getattr(contract.quote, "prepared_by", None) if contract.quote_id else None
    candidates = ([author] if author is not None and author.is_active else []) + [
        u for permission in REVIEW_PERMISSIONS for u in _holders(permission)
    ]
    for user in candidates:
        if user.pk not in seen:
            seen.add(user.pk)
            people.append(user)
    return people


def open_remark(contract) -> Optional[ContractRemark]:
    return contract.remarks.filter(resolution="").first()


def edition_of(contract) -> int:
    """Номер нашей редакции для контрагента: первая, плюс по одной на каждый наш встречный ответ."""
    return 1 + contract.remarks.filter(resolution=ContractRemark.COUNTERED).count()


def tally(remark) -> dict:
    votes = list(remark.votes.select_related("user"))
    return {
        "votes": votes,
        "agree": sum(1 for v in votes if v.agree),
        "disagree": sum(1 for v in votes if not v.agree),
    }


def awaiting(remark, contract) -> list:
    """Кто ещё не ответил."""
    done = {v.user_id for v in remark.votes.all()}
    return [u for u in reviewers(contract) if u.pk not in done]


# ── Получить замечания ─────────────────────────────────────────────────────────────────────────────────────────────


def load_upload(company, upload_id, deal):
    """Своя редакция из `PortalUpload` компании: DOCX или XLSX, сигнатура совпадает с расширением, до лимита портала.

    Чужая или неизвестная загрузка — `UPLOAD_NOT_FOUND`, неподходящий файл — `FILE_INVALID`."""
    import uuid

    from portal.models import PortalUpload

    try:
        key = uuid.UUID(str(upload_id))
    except ValueError:
        return None, None, "UPLOAD_NOT_FOUND"
    upload = PortalUpload.objects.filter(upload_id=key, company=company).first()
    if upload is None or (upload.deal_id is not None and upload.deal_id != deal.pk):
        return None, None, "UPLOAD_NOT_FOUND"
    name = upload.name or ""
    if (
        os.path.splitext(name)[1].lower() not in REMARK_EXTENSIONS
        or upload.size_bytes > settings.PORTAL_UPLOAD_MAX_BYTES
    ):
        return None, None, "FILE_INVALID"
    try:
        with upload.file.open("rb") as stream:
            content = stream.read()
        assert_content_matches_extension(ContentFile(content, name=name), label="Contract")
        contract_compare.check_archive(content)  # до python-docx: архив-бомба не разбирается вовсе
    except (OSError, ValidationError, contract_compare.HostileFile):
        return None, None, "FILE_INVALID"
    return ContentFile(content, name=name), name, None


def submit_remark(
    contract_id: int, *, contact, comment: str, upload_id=None
) -> Tuple[Optional[ContractRemark], Optional[str]]:
    """«Есть замечания» из Кабинета. Коды: `CONTRACT_NOT_FOUND`, `MEMBER_REQUIRED_FOR_ACTION` (не наш контакт или без права
    действовать), `CONTRACT_REMARK_NOT_ALLOWED` (договор не у контрагента), `REMARK_OPEN` (прежние ещё на согласовании),
    `COMMENT_REQUIRED`, `UPLOAD_NOT_FOUND`, `FILE_INVALID`.

    Файл читается и сравнивается ДО блокировки строки договора: разбор тяжёлый и не должен держать чужие записи; под
    блокировкой только проверка состояния и запись."""
    from .contracts import portal_contact_may_sign

    contract = (
        Contract.objects.select_related("deal__company", "status", "quote", "currency").filter(pk=contract_id).first()
    )
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if not portal_contact_may_sign(contact, contract):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if contract.status_code != S.PENDING_CLIENT:
        return None, "CONTRACT_REMARK_NOT_ALLOWED"
    comment = (comment or "").strip()
    if not comment or len(comment) > COMMENT_MAX:
        return None, "COMMENT_REQUIRED"
    content, name, analysis = None, "", {"items": [], "summary": dict(contract_compare.EMPTY_SUMMARY)}
    if upload_id:
        content, name, error = load_upload(contract.deal.company, upload_id, contract.deal)
        if error:
            return None, error
        analysis = contract_compare.compare_upload(contract, content, name)
        content.seek(0)
    return _store_remark(contract_id, contact, comment, content, name, analysis)


@transaction.atomic
def _store_remark(contract_id, contact, comment, content, name, analysis):
    from .contracts import portal_contact_may_sign

    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if not portal_contact_may_sign(contact, contract):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if contract.status_code != S.PENDING_CLIENT:
        return None, "CONTRACT_REMARK_NOT_ALLOWED"
    if open_remark(contract) is not None:
        return None, "REMARK_OPEN"
    who = (getattr(contact, "name", "") or "").strip()
    try:
        with transaction.atomic():
            remark = ContractRemark.objects.create(
                contract=contract,
                edition=edition_of(contract),
                comment=comment,
                file=content,
                file_name=name,
                author_name=who,
                summary={**analysis["summary"], "comparable": analysis.get("comparable", False)},
                items=analysis["items"],
            )
    except IntegrityError:
        return None, "REMARK_OPEN"
    _journal(contract, None, "contract.remark_received", "Получены замечания контрагента", contact=contact)
    _notify_reviewers(contract, remark)
    return remark, None


def _link(contract) -> str:
    return f"/eds/projects/{url_quote(contract.deal.number or f'D-{contract.deal_id}', safe='')}"


def _notify_reviewers(contract, remark) -> None:
    from notifications.services import notify_user

    summary = remark.summary or {}
    parts = []
    for key, word in (("changed", "изменены"), ("added", "добавлены"), ("removed", "удалены")):
        points = summary.get(key) or []
        if points:
            parts.append(f"{word} п. {', '.join(points)}")
    brief = "; ".join(parts) or (remark.comment[:160])
    for person in reviewers(contract):
        notify_user(
            user=person,
            title=f"Замечания к договору {contract.number}",
            message=f"{remark.author_name or 'Контрагент'}: {brief}. Ответьте «Согласен» или «Не согласен».",
            link=_link(contract),
            deal=contract.deal,
            type_code="INFO",
            event_code="contract.remark_received",
            event_params={"number": contract.number, "brief": brief},
        )


def _journal(contract, actor, event_code: str, action: str, *, contact=None, **params) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code=event_code,
        event_params={"number": contract.number, "deal_id": contract.deal_id, **params},
        user=actor,
        contact=contact,
        level="INFO",
        entity_type="contract",
        entity_id=contract.id,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )


# ── Ответы ответственных и решение ─────────────────────────────────────────────────────────────────────────────────


def _locked(contract_id: int):
    return (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "status", "quote")
        .filter(pk=contract_id)
        .first()
    )


@transaction.atomic
def vote(contract_id: int, user, *, agree: bool, comment: str = "") -> Tuple[Optional[Contract], Optional[str]]:
    """Ответ «Согласен» / «Не согласен» (повтор — заменяет прежний). Все согласны — редакция контрагента принята.

    Коды: `CONTRACT_NOT_FOUND`, `REMARK_NOT_OPEN`, `REMARK_FORBIDDEN` (не отвечает за этот договор),
    `COMMENT_REQUIRED` (несогласие без слов)."""
    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    remark = open_remark(contract)
    if remark is None or contract.status_code != S.PENDING_CLIENT:
        return None, "REMARK_NOT_OPEN"
    if user is None or user.pk not in {u.pk for u in reviewers(contract)}:
        return None, "REMARK_FORBIDDEN"
    comment = (comment or "").strip()
    if not agree and not comment:
        return None, "COMMENT_REQUIRED"
    ContractRemarkVote.objects.update_or_create(
        remark=remark, user=user, defaults={"agree": agree, "comment": comment[:COMMENT_MAX]}
    )
    _journal(
        contract,
        user,
        "contract.remark_voted",
        "Ответ по замечаниям контрагента",
        agree=agree,
        **({"comment": comment[:200]} if comment else {}),
    )
    if not awaiting(remark, contract) and tally(remark)["disagree"] == 0:
        _accept(contract, remark, None)
    elif tally(remark)["disagree"] and not awaiting(remark, contract):
        _notify_deciders(contract)
    return contract, None


def _notify_deciders(contract) -> None:
    from notifications.services import notify_user

    for person in deciders(contract):
        notify_user(
            user=person,
            title=f"Разногласие по договору {contract.number}",
            message="Ответственные не пришли к согласию по замечаниям контрагента — решение за вами.",
            link=_link(contract),
            deal=contract.deal,
            type_code="INFO",
            event_code="contract.remark_dispute",
            event_params={"number": contract.number},
        )


@transaction.atomic
def decide(contract_id: int, user, *, accept: bool, text: str = "") -> Tuple[Optional[Contract], Optional[str]]:
    """Решение директора: принять редакцию контрагента или ответить своей (`text` обязателен).

    Держатель права `contract.sign` закрывает замечания в любой момент: не дожидаясь ответов остальных (кто-то мог не
    ответить) и без разногласия. Коды: `CONTRACT_NOT_FOUND`, `REMARK_NOT_OPEN`, `REMARK_DECISION_FORBIDDEN` (нет права
    `contract.sign`), `COMMENT_REQUIRED` (ответ контрагенту)."""
    from .contract_flow import may

    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    remark = open_remark(contract)
    if remark is None or contract.status_code != S.PENDING_CLIENT:
        return None, "REMARK_NOT_OPEN"
    if user is None or not may(user, DECIDE_PERMISSION):
        return None, "REMARK_DECISION_FORBIDDEN"
    text = (text or "").strip()
    if not accept and not text:
        return None, "COMMENT_REQUIRED"
    if accept:
        _accept(contract, remark, user)
    else:
        _counter(contract, remark, user, text)
    return contract, None


def _accept(contract, remark, actor) -> None:
    """Принята редакция контрагента: договор «Согласован» (у нас «Ожидает подписания»), клиент видит «выставим на подпись»."""
    from notifications.services import notify_user

    from . import contract_flow
    from .contracts import _contract_seller_recipient

    now = timezone.now()
    remark.resolution = ContractRemark.ACCEPTED
    remark.resolved_at = now
    remark.resolved_by = actor
    remark.save(update_fields=["resolution", "resolved_at", "resolved_by"])
    contract.status = contract_flow._status_row(S.PENDING_MANAGER)
    contract.client_signed_at = now
    contract.save(update_fields=["status", "client_signed_at", "updated_at"])
    _journal(contract, actor, "contract.remark_accepted", "Принята редакция контрагента", file=bool(remark.file))
    from portal.services import notice_sources

    notice_sources.contract_awaiting_signature(contract)  # клиенту: «Договор будет выставлен на подписание»
    contract_flow.publish_current_status(contract, actor)
    recipient = _contract_seller_recipient(contract)
    if recipient is not None:
        notify_user(
            user=recipient,
            title=f"Договор {contract.number} ожидает подписания",
            message="Принята редакция контрагента. Когда договор будет подписан, отметьте это в карточке.",
            link=_link(contract),
            deal=contract.deal,
            type_code="INFO",
            event_code="contract.remark_accepted",
            event_params={"number": contract.number},
        )


def _counter(contract, remark, actor, text: str) -> None:
    remark.resolution = ContractRemark.COUNTERED
    remark.response = text[:COMMENT_MAX]
    remark.resolved_at = timezone.now()
    remark.resolved_by = actor
    remark.save(update_fields=["resolution", "response", "resolved_at", "resolved_by"])
    _journal(contract, actor, "contract.remark_countered", "Ответ контрагенту: наша редакция", comment=text[:200])
    from portal.services import notice_sources

    notice_sources.contract_remark_answered(contract, text)  # клиенту: «Наш ответ на ваши замечания»
