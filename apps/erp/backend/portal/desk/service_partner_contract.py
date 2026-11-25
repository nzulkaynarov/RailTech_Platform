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
from parties.models import PartnerApplication, PartnerApplicationStatus, PartnerContractApproval, PartnerContractSource
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


def approver_names() -> list[str]:
    """Кто решает: держатели права утверждать договоры (зона «Право») своей компании — именами."""
    from core.tenant import own_company_id
    from crm.services.contract_templates import _holders_to_notify

    names = []
    for holder in _holders_to_notify(own_company_id()):
        names.append((holder.get_full_name() or holder.email).strip())
    return sorted(set(names))


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
    }


def contract_facts(app: PartnerApplication, *, viewer=None) -> dict:
    """Договорная часть карточки заявки — по фактам заявки."""
    from crm.services.contract_templates import is_approver

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
        "contract_blocker": send_blocker(app) if app.status == PartnerApplicationStatus.SUBMITTED else None,
        "candidate_returned_at": app.candidate_returned_at,
        "has_signed_scan": bool(app.signed_scan),
        "signed_scan_at": app.signed_scan_at,
        "can_decide_contract": bool(viewer is not None and is_approver(viewer)),
        "contract_approvers": approver_names() if app.contract_approval == PartnerContractApproval.REQUESTED else [],
    }


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

    if upload is not None:
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
    # Новая версия: прежняя отправка, возврат кандидата и скан к ней не относятся
    app.status = PartnerApplicationStatus.SUBMITTED
    app.contract_draft_sent_at = None
    app.candidate_returned_at = None
    app.signed_scan = None
    app.signed_scan_at = None
    app.save()

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
    """Решение держателя права утверждать договоры: `approve` или `return` (с замечанием)."""
    from crm.services.contract_templates import is_approver

    if not is_approver(user):
        raise AccessError("CONTRACT_DECISION_FORBIDDEN", 403)
    app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    if app.contract_approval != PartnerContractApproval.REQUESTED:
        raise AccessError("CONTRACT_APPROVAL_NOT_REQUESTED")
    decision = data.get("decision")
    note = (data.get("note") or "").strip()
    if decision not in ("approve", "return"):
        raise AccessError("CONTRACT_DECISION_INVALID")
    if decision == "return" and not note:
        raise AccessError("CONTRACT_RETURN_NOTE_REQUIRED")
    approved = decision == "approve"
    app.contract_approval = PartnerContractApproval.APPROVED if approved else PartnerContractApproval.RETURNED
    app.contract_approval_decided_by = user
    app.contract_approval_decided_at = timezone.now()
    app.contract_approval_note = note[:1000]
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
    app.save()
    record(
        user,
        entity="partner_application",
        instance=app,
        event="contract_approved" if approved else "contract_returned",
        action="Договор кандидата согласован" if approved else "Договор кандидата возвращён на доработку",
        before=None,
        after={"approval": app.contract_approval, "note": app.contract_approval_note},
        detail=app.company_name,
    )
    return app


# ── Шаги кандидата (Cabinet) ───────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def candidate_return(app: PartnerApplication, notes: str) -> PartnerApplication:
    """Кандидат вернул договор с замечанием: статус остаётся «Договор отправлен», сотрудник видит замечание."""
    notes = (notes or "").strip()
    if not notes:
        raise AccessError("RETURN_NOTE_REQUIRED")
    app.candidate_notes = notes[:1000]
    app.candidate_returned_at = timezone.now()
    app.save(update_fields=["candidate_notes", "candidate_returned_at", "updated_at"])
    record(
        None,
        entity="partner_application",
        instance=app,
        event="candidate_returned_contract",
        action="Кандидат вернул договор с замечанием",
        before=None,
        after={"notes": app.candidate_notes},
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
