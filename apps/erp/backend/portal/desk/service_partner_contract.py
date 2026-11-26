"""Договор кандидата в партнёры без тупика (ПД-1, владелец 2026-11-25): подготовка, согласование, шаги кандидата.

Путь: «Подготовить договор» (утверждённый шаблон библиотеки либо свой файл) → согласование (шаблон без отступлений —
не нужно; свой файл или отступление — решение держателя зоны «Право», как у договоров клиентов, ДОК-10) → отправка
(`service_partner_applications.send_contract`) → кандидат читает, соглашается или возвращает с замечанием, загружает скан
подписанного → сотрудник подтверждает (`approve_application`).

Факты, из которых карточка выводит «что дальше»: `contract_source`, `contract_file`, `contract_approval`,
`candidate_returned_at`, `signed_scan`. Статусов заявки не прибавилось.
"""

from __future__ import annotations

import os
from datetime import date

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from documents.models.documents import DocumentTemplate
from parties.models import (
    PartnerApplication,
    PartnerApplicationDocument,
    PartnerApplicationStatus,
    PartnerContractApproval,
    PartnerContractSource,
)
from portal.desk.service import AccessError
from portal.services import partner_contract as contract_service

from catalog.desk.audit import record
from core.validators import validate_contract_upload, validate_scan_upload

MAX_NOTE = 4000
#: Содержимое файла по расширению — для скачивания; сам файл мы не разбираем.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# ── Что мешает отправить ───────────────────────────────────────────────────────────────────────────────────────────


def send_blocker(app: PartnerApplication) -> str | None:
    """ОДНА проверка «можно ли отправить договор кандидату» (`None` — можно): код причины или ничего.

    Её читают и отправка (`send_contract` отвечает этим кодом), и карточка заявки (`contract_blocker`)."""
    if not (app.contract_source and (app.contract_file or app.contract_pdf)):
        return "CONTRACT_NOT_PREPARED"
    if app.contract_approval == PartnerContractApproval.REQUESTED:
        return "CONTRACT_APPROVAL_PENDING"
    if app.contract_approval == PartnerContractApproval.RETURNED:
        return "CONTRACT_APPROVAL_RETURNED"
    return None


def current_document(app: PartnerApplication):
    """Файл договора, который видит кандидат: новый путь (`contract_file`), иначе прежний PDF."""
    return app.contract_file or app.contract_pdf or None


def read_file(field) -> tuple[bytes, str, str]:
    """(содержимое, content-type, имя) файла поля; нет файла — `NOT_FOUND`."""
    if not field:
        raise AccessError("NOT_FOUND", 404)
    try:
        field.open("rb")
        try:
            data = field.read()
        finally:
            field.close()
    except (OSError, ValueError):
        raise AccessError("NOT_FOUND", 404) from None
    name = os.path.basename(field.name)
    return data, CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream"), name


# ── Параметры для карточки ─────────────────────────────────────────────────────────────────────────────────────────


def _holders() -> list:
    """Все, кто отвечает за договор: держатели «Права» и подписи (то же правило, что `contract_remarks.reviewers`, ДП-1)."""
    from crm.services import contract_remarks as remarks

    people: dict = {}
    for permission in remarks.REVIEW_PERMISSIONS:
        for holder in remarks._holders(permission):
            people.setdefault(holder.pk, holder)
    return list(people.values())


def four_eyes_on() -> bool:
    """Правило компании «решение по своему договору — другим держателем «Права»» (по умолчанию включено)."""
    from parties.models.company_settings import CompanySettings

    company = contract_service._own_company_or_none()
    row = CompanySettings.objects.filter(company=company).first() if company is not None else None
    return True if row is None else row.contract_four_eyes


def _others(user) -> list:
    return [h for h in _holders() if h.pk != getattr(user, "pk", None)]


def approver_names(exclude=None) -> list[str]:
    """Кто решает: держатели права утверждать договоры (зона «Право») своей компании — именами.

    Подготовивший договор из списка исключается, если есть другие держатели (правило «четыре глаза»)."""
    holders = _holders()
    if exclude is not None and any(h.pk != exclude.pk for h in holders):
        holders = [h for h in holders if h.pk != exclude.pk]
    return sorted({(h.get_full_name() or h.email).strip() for h in holders})


def _is_requester(app, user) -> bool:
    return app.contract_approval_requested_by_id is not None and app.contract_approval_requested_by_id == getattr(
        user, "pk", None
    )


def _directors(holders: list) -> list:
    """Директор — тот, чей голос решает при разногласии: держатель права подписи (`contract_remarks.DECIDE_PERMISSION`).

    Нет такого среди ответственных — решающими считаются все они (иначе разногласие некому разрешить)."""
    from crm.services import contract_remarks as remarks

    sign_ids = {u.pk for u in remarks._holders(remarks.DECIDE_PERMISSION)}
    directors = [h for h in holders if h.pk in sign_ids]
    return directors or list(holders)


def _needed_voters(app) -> list:
    """Кто должен согласовать: все ответственные за договор (держатели «Права»); подготовивший — не сам себе, пока есть другие."""
    holders = _holders()
    requester = app.contract_approval_requested_by
    if requester is not None and four_eyes_on():
        others = [h for h in holders if h.pk != requester.pk]
        if others:
            return others
    return holders


def _votes(app) -> list[dict]:
    return list(app.contract_approval_votes or [])


def _disagreement(app) -> bool:
    """Кто-то из ответственных, кроме директора, вернул договор: решает директор."""
    if app.contract_approval != PartnerContractApproval.REQUESTED:
        return False
    director_ids = {d.pk for d in _directors(_holders())}
    return any(v["decision"] == "return" and v["user_id"] not in director_ids for v in _votes(app))


def _resolve(app) -> str:
    """Итог по голосам: `approve`, `return` или пусто (ждём остальных или директора). Порядок голосов — по времени.

    Все согласны — согласован. Директор вернул — возвращён. Кто-то другой вернул — разногласие: решает голос директора,
    поданный ПОСЛЕ него (директор решает, а не складывается с остальными)."""
    director_ids = {d.pk for d in _directors(_holders())}
    votes = _votes(app)
    admin_votes = [v for v in votes if v.get("admin")]
    if admin_votes:  # администратор решает сам (как и в правиле «четырёх глаз»: его решение — «от имени»)
        return admin_votes[-1]["decision"]
    for v in votes:
        if v["user_id"] in director_ids and v["decision"] == "return":
            return "return"
    first_other_return = next(
        (i for i, v in enumerate(votes) if v["decision"] == "return" and v["user_id"] not in director_ids), None
    )
    if first_other_return is not None:
        later = [v for v in votes[first_other_return + 1 :] if v["user_id"] in director_ids]
        return "approve" if later else ""
    approved = {v["user_id"] for v in votes if v["decision"] == "approve"}
    needed = {u.pk for u in _needed_voters(app)}
    return "approve" if needed <= approved else ""


def _may_vote(user) -> bool:
    """Голос у тех, кто отвечает за договор (держатели «Права» и подписи); администратор — всегда."""
    from crm.services.contract_templates import is_approver

    return is_approver(user) or user.pk in {h.pk for h in _holders()}


def decision_state(app, viewer) -> tuple[bool, bool]:
    """(может решить, нужно подтверждение самостоятельного решения) — по правилу компании и составу держателей."""
    holder = viewer is not None and _may_vote(viewer)
    if not holder or app.contract_approval != PartnerContractApproval.REQUESTED:
        return bool(holder), False
    if _disagreement(app) and viewer.pk not in {d.pk for d in _directors(_holders())}:
        return False, False  # разногласие: решает директор
    if not _is_requester(app, viewer) or getattr(viewer, "is_superuser", False) or not four_eyes_on():
        return True, False
    if _others(viewer):
        return False, False
    return True, True


# ── Пакет базовых документов (ОСН-1) ───────────────────────────────────────────────────────────────────────────────────


def package_plan() -> list[dict]:
    """Что войдёт в пакет кандидата: роли из настройки компании и утверждённый шаблон каждой (`template` пуст — нет)."""
    from crm.services.contract_templates import base_template, partner_base_roles

    company = contract_service._own_company_or_none()
    if company is None:
        return []
    return [{"role": role, "template": base_template(company, role)} for role in partner_base_roles(company)]


def package_options() -> dict:
    """Пакет для «Подготовить договор»: роли, шаблон каждой или отметка «нет утверждённого шаблона» (с названием роли)."""
    from documents.models.documents import BaseRole

    plan = package_plan()
    roles = [
        {
            "base_role": item["role"],
            "role_name": str(BaseRole(item["role"]).label),
            "template_id": item["template"].id if item["template"] else None,
            "name": item["template"].name if item["template"] else None,
            "edition": item["template"].edition if item["template"] else None,
            "languages": contract_service.template_languages(item["template"]) if item["template"] else [],
        }
        for item in plan
    ]
    return {"roles": roles, "ready": bool(roles) and all(r["template_id"] for r in roles)}


def package_facts(app: PartnerApplication) -> list[dict]:
    return [
        {
            "id": row.id,
            "base_role": row.base_role,
            "title": row.title,
            "number": row.number,
            "template_edition": row.template_edition,
            "has_candidate_file": bool(row.candidate_file),
            "candidate_remark": row.candidate_remark,
            "valid_from": row.valid_from,
            "valid_until": row.valid_until,
            "confidentiality_years": row.confidentiality_years,
            "trade_secret_indefinite": row.trade_secret_indefinite,
            "from_archive": row.from_archive,
        }
        for row in app.package_documents.all()
    ]


def package_document(app: PartnerApplication, doc_id) -> PartnerApplicationDocument:
    try:
        row = app.package_documents.filter(pk=int(doc_id)).first()
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise AccessError("NOT_FOUND", 404)
    return row


def contract_options(user) -> dict:
    """Что сотрудник может выбрать при «Подготовить договор»: утверждённые партнёрские шаблоны и умолчание из настроек."""
    from crm.services.contract_templates import is_approver

    default_id = contract_service.default_partner_template_id()
    templates = [
        {
            "id": t.id,
            "name": t.name,
            "edition": t.edition,
            "languages": contract_service.template_languages(t),
            "is_default": t.id == default_id,
        }
        for t in contract_service.offered_partner_templates()
    ]
    return {
        "templates": templates,
        "default_template_id": default_id if any(t["id"] == default_id for t in templates) else None,
        "deviations_allowed": contract_service.deviations_allowed(),
        "approvers": approver_names(),
        "can_decide": is_approver(user),
        "package": package_options(),
    }


def contract_facts(app: PartnerApplication, *, viewer=None) -> dict:
    """Договорная часть карточки заявки — по фактам заявки."""
    template = app.contract_template
    requested_by = app.contract_approval_requested_by
    decided_by = app.contract_approval_decided_by
    return {
        "contract_source": app.contract_source,
        "contract_template_id": app.contract_template_id,
        "contract_template_name": template.name if template else None,
        "contract_template_edition": template.edition if template else None,
        "contract_language": app.contract_language,
        "contract_deviation_text": app.contract_deviation_text,
        "contract_approval": app.contract_approval,
        "contract_approval_requested_by": _name(requested_by),
        "contract_approval_decided_by": _name(decided_by),
        "contract_approval_note": app.contract_approval_note,
        "contract_blocker": send_blocker(app) if _awaits_sending(app) else None,
        "candidate_returned_at": app.candidate_returned_at,
        "has_signed_scan": bool(app.signed_scan),
        "signed_scan_at": app.signed_scan_at,
        "can_decide_contract": decision_state(app, viewer)[0],
        "decision_needs_confirmation": decision_state(app, viewer)[1],
        "contract_approvers": (
            approver_names(exclude=requested_by) if app.contract_approval == PartnerContractApproval.REQUESTED else []
        ),
        "contract_votes": [
            {"name": v["name"], "decision": v["decision"], "note": v.get("note", "")} for v in _votes(app)
        ],
        "contract_waiting_for": _waiting_for(app),
        "contract_disagreement": _disagreement(app),
        "has_candidate_file": bool(app.candidate_file),
        "signed_note": app.signed_note,
        "contract_valid_from": app.contract_valid_from,
        "contract_valid_until": app.contract_valid_until,
        "contract_last_notice_date": app.contract_last_notice_date,
        "contract_renewal_mode": app.contract_renewal_mode,
        "package": package_facts(app),
    }


def _awaits_sending(app) -> bool:
    """Договор ждёт отправки: заявка подана либо кандидат вернул его с замечаниями (новая редакция — ответственным)."""
    return app.status == PartnerApplicationStatus.SUBMITTED or (
        app.status == PartnerApplicationStatus.CONTRACT_SENT and app.candidate_returned_at is not None
    )


def _waiting_for(app) -> list[str]:
    """Кто ещё не высказался (имена); при разногласии — директор, который решает."""
    if app.contract_approval != PartnerContractApproval.REQUESTED:
        return []
    if _disagreement(app):
        return sorted({_name(d) or "" for d in _directors(_holders())})
    voted = {v["user_id"] for v in _votes(app)}
    return sorted({_name(u) or "" for u in _needed_voters(app) if u.pk not in voted})


def _name(user) -> str | None:
    if user is None:
        return None
    return (user.get_full_name() or user.email).strip()


# ── Подготовка договора ────────────────────────────────────────────────────────────────────────────────────────────


def _render_template_contract(app, template, language, number, contract_date, notes: str = "") -> bytes:
    try:
        return contract_service.render_partner_contract_pdf(
            app, template, language, number=number, date=contract_date, notes=notes
        )
    except contract_service.PartnerContractUnfilled as exc:
        raise AccessError("CONTRACT_TEMPLATE_UNFILLED") from exc
    except contract_service.PartnerContractRenderError:
        raise AccessError("CONTRACT_RENDER_FAILED") from None


@transaction.atomic
def prepare_contract(pk: int, data: dict, upload, user) -> PartnerApplication:
    """«Подготовить договор»: из утверждённого шаблона (`template_id` или умолчание настроек) либо своим файлом.

    Шаблон без отступлений — договор готов к отправке. Свой файл или текст отступления — запрос держателю «Право»;
    отправить, пока он не решил, нельзя. Ни шаблона, ни файла — `CONTRACT_TEMPLATE_REQUIRED` (когда в библиотеке нет
    утверждённых партнёрских шаблонов — `NO_APPROVED_PARTNER_TEMPLATE`): встроенного образца нет."""
    app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    if app.status == PartnerApplicationStatus.SUBMITTED:
        pass
    elif app.status == PartnerApplicationStatus.CONTRACT_SENT and app.candidate_returned_at:
        pass  # кандидат вернул с замечанием: готовим новую версию
    else:
        raise AccessError("CONTRACT_ALREADY_SENT")

    language = (data.get("language") or app.language or "ru").lower()
    if language not in contract_service.LANGUAGES:
        raise AccessError("CONTRACT_LANGUAGE_INVALID")
    deviation = (data.get("deviation_text") or "").strip()
    if len(deviation) > MAX_NOTE:
        raise AccessError("DEVIATION_TEXT_TOO_LONG")

    number = (data.get("contract_number") or "").strip() or app.contract_number
    if not number:
        number = contract_service.generate_partner_contract_number(app.pk)
    contract_date = data.get("contract_date") or app.contract_date or timezone.localdate()
    if not isinstance(contract_date, date):
        raise AccessError("CONTRACT_DATE_INVALID")

    package = bool(data.get("package"))
    built: list[tuple[dict, str, bytes]] = []
    if package:
        # ОСН-1: пакет — только из утверждённых базовых шаблонов, без отступлений и без своего файла
        if upload is not None or deviation:
            raise AccessError("PACKAGE_NO_DEVIATION")
        plan = package_plan()
        if not plan:
            raise AccessError("NO_PACKAGE_ROLES")
        if any(item["template"] is None for item in plan):
            raise AccessError("NO_APPROVED_BASE_TEMPLATE")
        primary = next((i for i in plan if i["role"] == "partnership"), plan[0])
        template = primary["template"]
        for index, item in enumerate(plan):
            doc_number = number if item is primary else f"{number}/{index + 1}"
            pdf = _render_template_contract(app, item["template"], language, doc_number, contract_date)
            built.append((item, doc_number, pdf))
        source, deviation_text = PartnerContractSource.TEMPLATE, ""
        primary_pdf = next(pdf for item, _, pdf in built if item is primary)
        app.contract_file.save(f"Partner_Contract_{number}.pdf", ContentFile(primary_pdf), save=False)
    elif upload is not None:
        if not contract_service.deviations_allowed():
            raise AccessError("CONTRACT_DEVIATIONS_DISABLED")
        try:
            validate_contract_upload(upload)
        except ValidationError:
            raise AccessError("CONTRACT_FILE_INVALID") from None
        source, template, deviation_text = PartnerContractSource.UPLOAD, None, deviation
        app.contract_file.save(upload.name, upload, save=False)
    else:
        template = _chosen_template(data.get("template_id"))
        if language not in contract_service.template_languages(template):
            raise AccessError("CONTRACT_LANGUAGE_INVALID")  # на этом языке у шаблона нет текста
        if deviation and not contract_service.deviations_allowed():
            raise AccessError("CONTRACT_DEVIATIONS_DISABLED")
        source, deviation_text = PartnerContractSource.TEMPLATE, deviation
        pdf = _render_template_contract(app, template, language, number, contract_date)
        app.contract_file.save(f"Partner_Contract_{number}.pdf", ContentFile(pdf), save=False)

    now = timezone.now()
    app.contract_source = source
    app.contract_template = template
    app.contract_language = language
    app.contract_deviation_text = deviation_text
    app.contract_number = number
    app.contract_date = contract_date
    needs_approval = source == PartnerContractSource.UPLOAD or bool(deviation_text)
    app.contract_approval = PartnerContractApproval.REQUESTED if needs_approval else ""
    app.contract_approval_requested_by = user if needs_approval else None
    app.contract_approval_requested_at = now if needs_approval else None
    app.contract_approval_decided_by = None
    app.contract_approval_decided_at = None
    app.contract_approval_note = ""
    app.contract_approval_votes = []
    # Новая версия: прежняя отправка, возврат кандидата и скан к ней не относятся
    app.status = PartnerApplicationStatus.SUBMITTED
    app.contract_draft_sent_at = None
    app.candidate_returned_at = None
    app.signed_scan = None
    app.signed_scan_at = None
    app.save()
    # Новая подготовка заменяет прежний пакет целиком, но ответ кандидата по роли (его файл и замечание) не теряется
    kept = {
        old.base_role: (old.candidate_file.name, old.candidate_remark)
        for old in app.package_documents.all()
        if old.candidate_file or old.candidate_remark
    }
    app.package_documents.all().delete()
    for position, (item, doc_number, pdf) in enumerate(built):
        tpl = item["template"]
        row = PartnerApplicationDocument(
            application=app,
            base_role=item["role"],
            template=tpl,
            template_edition=tpl.edition,
            title=tpl.name,
            number=doc_number,
            position=position,
        )
        row.file.save(f"{item['role']}_{doc_number.replace('/', '-')}.pdf", ContentFile(pdf), save=False)
        carried = kept.get(item["role"])
        if carried:
            row.candidate_file.name, row.candidate_remark = carried
        row.save()

    record(
        user,
        entity="partner_application",
        instance=app,
        event="contract_prepared",
        action="Договор кандидата подготовлен",
        before=None,
        after={
            "source": source,
            "template": template.pk if template else None,
            "language": language,
            "approval": app.contract_approval,
            **({"package": [item["role"] for item, _, _ in built]} if built else {}),
        },
        detail=app.company_name,
    )
    if needs_approval:
        _notify_holders(app)
    return app


def _chosen_template(template_id) -> DocumentTemplate:
    offered = contract_service.offered_partner_templates()
    if not offered:
        raise AccessError("NO_APPROVED_PARTNER_TEMPLATE")
    wanted = template_id or contract_service.default_partner_template_id()
    if not wanted:
        raise AccessError("CONTRACT_TEMPLATE_REQUIRED")
    chosen = next((t for t in offered if t.id == wanted), None)
    if chosen is None:
        raise AccessError("CONTRACT_TEMPLATE_NOT_OFFERED")
    return chosen


# ── Решение держателя «Право» ──────────────────────────────────────────────────────────────────────────────────────


def _notify_holders(app: PartnerApplication) -> None:
    from core.tenant import own_company_id
    from crm.services.contract_templates import _holders_to_notify
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    info = NotificationType.objects.filter(code="INFO").first()
    what = "Свой файл договора" if app.contract_source == PartnerContractSource.UPLOAD else "Отступление от шаблона"
    for holder in _holders_to_notify(own_company_id()):
        notif = Notification.objects.create(
            user=holder,
            type=info,
            title="Договор кандидата в партнёры ждёт решения",
            message=f"{app.company_name}: {what.lower()}. {app.contract_deviation_text[:160]}".strip(),
            link="/crm/clients?kind=applications",
            event_code="partner_contract.approval_requested",
            event_params={"application_id": app.pk},
        )
        push_notification_ws(notif)


@transaction.atomic
def decide_contract(pk: int, data: dict, user) -> PartnerApplication:
    """Голос ответственного за договор (держатель права утверждать договоры): `approve` или `return` (с замечанием).

    ПК-1: договор согласован, когда согласились все ответственные; при разногласии решает директор (его голос после
    возражения). По каждому пункту решений нет — один голос и одно слово."""
    if not _may_vote(user):
        raise AccessError("CONTRACT_DECISION_FORBIDDEN", 403)
    app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    if app.contract_approval != PartnerContractApproval.REQUESTED:
        raise AccessError("CONTRACT_APPROVAL_NOT_REQUESTED")
    # Четыре глаза — правило компании: подготовивший сам не решает, пока есть другой держатель; единственный держатель
    # решает с подтверждением, суперпользователь — «от имени»; оба случая в журнале на уровне WARNING
    self_approval = _is_requester(app, user)
    if self_approval and four_eyes_on() and not getattr(user, "is_superuser", False):
        if _others(user):
            raise AccessError("SELF_APPROVAL_NOT_ALLOWED", 403)
        if not data.get("confirm_self"):
            raise AccessError("SELF_DECISION_CONFIRMATION_REQUIRED")
    if _disagreement(app) and user.pk not in {d.pk for d in _directors(_holders())}:
        raise AccessError("CONTRACT_DIRECTOR_DECIDES", 403)
    decision = data.get("decision")
    note = (data.get("note") or "").strip()
    if decision not in ("approve", "return"):
        raise AccessError("CONTRACT_DECISION_INVALID")
    if decision == "return" and not note:
        raise AccessError("CONTRACT_RETURN_NOTE_REQUIRED")
    now = timezone.now()
    votes = [v for v in _votes(app) if v["user_id"] != user.pk]  # новый голос того же человека заменяет прежний
    votes.append(
        {
            "user_id": user.pk,
            "name": _name(user) or "",
            "decision": decision,
            "note": note[:1000],
            "at": now.isoformat(),
            "admin": bool(getattr(user, "is_superuser", False)),
        }
    )
    app.contract_approval_votes = votes
    was_disagreement = False
    outcome = _resolve(app)
    if outcome:
        approved = outcome == "approve"
        app.contract_approval = PartnerContractApproval.APPROVED if approved else PartnerContractApproval.RETURNED
        app.contract_approval_decided_by = user
        app.contract_approval_decided_at = now
        returning = [v for v in votes if v["decision"] == "return"]
        app.contract_approval_note = ("" if approved else (returning[-1]["note"] if returning else note))[:1000]
        if approved and app.contract_source == PartnerContractSource.TEMPLATE and app.contract_deviation_text:
            # Одобренное отступление входит в текст договора, как у клиентов (ДОК-10): PDF пересобирается с ним
            pdf = _render_template_contract(
                app,
                app.contract_template,
                app.contract_language or "ru",
                app.contract_number,
                app.contract_date or timezone.localdate(),
                notes=app.contract_deviation_text,
            )
            app.contract_file.save(f"Partner_Contract_{app.contract_number}.pdf", ContentFile(pdf), save=False)
    else:
        was_disagreement = _disagreement(app)
    app.save()
    state = app.contract_approval
    record(
        user,
        entity="partner_application",
        instance=app,
        event=(
            "contract_approved"
            if outcome == "approve"
            else "contract_returned" if outcome == "return" else "contract_vote"
        ),
        action=(
            "Договор кандидата согласован"
            if outcome == "approve"
            else "Договор кандидата возвращён на доработку" if outcome == "return" else "Голос по договору кандидата"
        ),
        before=None,
        after={
            "approval": state,
            "vote": decision,
            "note": note[:1000],
            **({"on_behalf": "решение от имени: подготовивший и решающий — одно лицо"} if self_approval else {}),
        },
        level="WARNING" if self_approval else "INFO",
        detail=app.company_name,
    )
    if was_disagreement:
        _notify_director(app, user, note)
    return app


def _notify_director(app: PartnerApplication, who, note: str) -> None:
    """Разногласие: решает директор — ему уведомление с тем, кто и что возразил."""
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    info = NotificationType.objects.filter(code="INFO").first()
    for director in _directors(_holders()):
        if director.pk == getattr(who, "pk", None):
            continue
        notif = Notification.objects.create(
            user=director,
            type=info,
            title="Разногласие по договору кандидата в партнёры",
            message=f"{app.company_name}: {_name(who)} возразил(а) — {note[:160]}. Решение за вами.".strip(),
            link="/crm/clients?kind=applications",
            event_code="partner_contract.disagreement",
            event_params={"application_id": app.pk},
        )
        push_notification_ws(notif)


# ── Шаги кандидата (Cabinet) ───────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def candidate_return(app: PartnerApplication, notes: str, upload=None, document_id=None) -> PartnerApplication:
    """«Есть замечания» (ПК-1, одно окно): комментарий и, если нужно, своя редакция договора (DOCX).

    Статус остаётся «Договор отправлен», сотрудник видит замечание. Приложенный файл — вложение и точка правды: он
    становится файлом договора на согласовании у ответственных (все согласны — уходит кандидату как новая редакция).
    Ответственным приходит уведомление с кратким разбором.

    ОСН-1: в пакете замечание или своя редакция относятся к названному документу (`document_id`); файл без названия
    документа при нескольких документах принять нельзя — непонятно, чью редакцию заменять."""
    notes = (notes or "").strip()
    if not notes and upload is None:
        raise AccessError("RETURN_NOTE_REQUIRED")
    rows = list(app.package_documents.all())
    row = None
    if document_id not in (None, ""):
        try:
            row = package_document(app, document_id)
        except AccessError:
            raise AccessError("RETURN_DOCUMENT_INVALID") from None
    elif upload is not None and len(rows) > 1:
        raise AccessError("RETURN_DOCUMENT_REQUIRED")
    elif rows:
        row = rows[0]
    primary_id = _primary_row_id(rows)
    if upload is not None:
        try:
            validate_contract_upload(upload)
        except ValidationError:
            raise AccessError("CONTRACT_FILE_INVALID") from None
    now = timezone.now()
    app.candidate_notes = notes[:1000]
    app.candidate_returned_at = now
    if row is not None:
        row.candidate_remark = notes[:1000]
    if upload is not None:
        data = upload.read()
        if row is None or row.pk == primary_id:
            app.candidate_file.save(upload.name, ContentFile(data), save=False)
            app.contract_file.save(upload.name, ContentFile(data), save=False)
        if row is not None:
            row.candidate_file.save(upload.name, ContentFile(data), save=False)
            row.file.save(upload.name, ContentFile(data), save=False)
        app.contract_source = PartnerContractSource.UPLOAD
        if not rows:
            app.contract_template = None  # пакет помнит шаблоны в своих документах, основной шаблон нужен для срока
        app.contract_deviation_text = notes[:4000]
        app.contract_approval = PartnerContractApproval.REQUESTED
        app.contract_approval_requested_by = None
        app.contract_approval_requested_at = now
        app.contract_approval_decided_by = None
        app.contract_approval_decided_at = None
        app.contract_approval_note = ""
        app.contract_approval_votes = []
    app.save()
    if row is not None:
        row.save()
    record(
        None,
        entity="partner_application",
        instance=app,
        event="candidate_returned_contract",
        action="Кандидат вернул договор с замечанием",
        before=None,
        after={
            "notes": app.candidate_notes,
            "with_file": upload is not None,
            **({"document": row.base_role} if row is not None and len(rows) > 1 else {}),
        },
        detail=app.company_name,
    )
    _notify_remarks(app, with_file=upload is not None, document=row.title if row is not None and len(rows) > 1 else "")
    return app


def _primary_row_id(rows: list) -> int | None:
    """Основной документ пакета — его файл лежит и в `contract_file` заявки: договор о партнёрстве, иначе первый."""
    if not rows:
        return None
    return next((r.pk for r in rows if r.base_role == "partnership"), rows[0].pk)


def _notify_remarks(app: PartnerApplication, *, with_file: bool, document: str = "") -> None:
    """Замечания контрагента: ответственным за договор и тому, кто его отправил — коротко, с отсылкой к новой редакции."""
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    people = {h.pk: h for h in _holders()}
    if app.reviewed_by_id and app.reviewed_by is not None:
        people.setdefault(app.reviewed_by_id, app.reviewed_by)
    info = NotificationType.objects.filter(code="INFO").first()
    tail = " Их редакция приложена — её нужно согласовать." if with_file else ""
    for person in people.values():
        notif = Notification.objects.create(
            user=person,
            type=info,
            title="Замечания к договору кандидата в партнёры",
            message=f"{app.company_name}{f' ({document})' if document else ''}: {app.candidate_notes[:200]}{tail}".strip(),
            link="/crm/clients?kind=applications",
            event_code="partner_contract.remarks",
            event_params={"application_id": app.pk, "with_file": with_file},
        )
        push_notification_ws(notif)


@transaction.atomic
def staff_attach_scan(pk: int, upload, user) -> PartnerApplication:
    """Скан подписанного договора — по желанию (ПК-1): прикрепляет менеджер, не контрагент; заменяет прежний."""
    app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
        raise AccessError("APPLICATION_ALREADY_DECIDED")
    try:
        validate_scan_upload(upload)
    except ValidationError:
        raise AccessError("SCAN_INVALID") from None
    app.signed_scan.save(upload.name, upload, save=False)
    app.signed_scan_at = timezone.now()
    app.save()
    record(
        user,
        entity="partner_application",
        instance=app,
        event="signed_scan_uploaded",
        action="Прикреплён скан подписанного договора кандидата",
        before=None,
        after={"signed_scan_at": str(app.signed_scan_at)},
        detail=app.company_name,
    )
    return app


@transaction.atomic
def candidate_upload_scan(app: PartnerApplication, upload) -> PartnerApplication:
    """Скан подписанного договора: после согласия кандидата; повторная загрузка заменяет скан."""
    if app.status != PartnerApplicationStatus.CANDIDATE_AGREED:
        raise AccessError("SCAN_NOT_EXPECTED")
    try:
        validate_scan_upload(upload)
    except ValidationError:
        raise AccessError("SCAN_INVALID") from None
    app.signed_scan.save(upload.name, upload, save=False)
    app.signed_scan_at = timezone.now()
    app.save()
    record(
        None,
        entity="partner_application",
        instance=app,
        event="signed_scan_uploaded",
        action="Кандидат загрузил скан подписанного договора",
        before=None,
        after={"signed_scan_at": str(app.signed_scan_at)},
        detail=app.company_name,
    )
    return app
