"""Х-1: договор не уходит клиенту, пока не собраны визы маршрута подписи (ADR-0025, решение владельца 2026-11-09).

ERP не знает состава виз: его ведёт EDS (`DOCUMENT_VISAS`, право EDS у держателя). EDS сообщает состояние событием
`eds.signing.visas_changed`; здесь оно лежит у запроса подписи (`CommercialSigningRequest.visas`) и отвечает на один
вопрос: можно ли отправить ЭТУ редакцию договора клиенту. Ответ — по фактам: запрос на текущую редакцию (отпечаток
совпадает), все визы маршрута `approved`. Изменённый после виз договор — другая редакция, визы собираются заново.

Единственный источник для всех путей отправки: действие `send_to_client`, создание договора сразу «у клиента» (акцепт КП,
`generate-from-quote` без `send_to_client=false`), список действий и карточка проекта в Платформе.
"""

from __future__ import annotations

from typing import Optional

from django.utils import timezone

VISAS_REQUIRED = "CONTRACT_VISAS_REQUIRED"

#: Кодовые причины блокировки (`send_blocker.code`): по ним Платформа выбирает слова и ссылку.
NOT_REQUESTED = "visas_not_requested"
DECLINED = "visas_declined"
PENDING = "visas_pending"
RETURNED = "visas_returned"
NO_HOLDER = "no_visa_holder"


def _roles(visas: list, *statuses: str) -> list[str]:
    return [str(v.get("role") or v.get("label") or "").lower() for v in visas if v.get("status") in statuses]


def _blocker(code: str, message: str, missing=None, *, remark: str = "", settings_link: bool = False) -> dict:
    return {
        "code": code,
        "message": message,
        "missing": list(missing or []),
        "remark": remark,
        "settings_link": settings_link,
    }


def send_blocker(contract) -> Optional[dict]:
    """`None` — визы собраны, договор можно отправлять; иначе `{code, message, missing, remark, settings_link}`.

    `missing` — роли не поставивших визу словами в нижнем регистре («бухгалтер», «юрист»); `remark` — слова человека или
    EDS (замечание визирующего, причина отказа), как написаны; `settings_link` — в компании
    нет держателя нужного права, назначить его можно в настройках (без тупика).
    """
    from integration.models import CommercialSigningRequest as Request

    from .signing_outbound import fingerprint

    request = (
        Request.objects.filter(kind="contract", object_id=contract.pk, fingerprint=fingerprint("contract", contract))
        .exclude(status=Request.Status.STALE)
        .order_by("-created_at", "-id")
        .first()
    )
    if request is None:
        return _blocker(
            NOT_REQUESTED, "Нужны визы: сначала отправьте договор «На подпись», после виз его можно отправить клиенту."
        )
    if request.status == Request.Status.SIGNED:
        return None  # подпись невозможна без виз
    visas = request.visas or []
    if not visas:
        if (
            request.status == Request.Status.REJECTED
        ):  # отказ до виз: нет полномочия подписать и т. п. — причина словами
            return _blocker(
                DECLINED,
                f"Договор не принят на визы: {request.comment or 'отправьте его «На подпись» заново'}.",
                remark=request.comment,
            )
        return _blocker(PENDING, "Визы собираются.")
    no_holder = _roles(visas, "no_holder")
    if no_holder:
        roles = ", ".join(no_holder)
        return _blocker(
            NO_HOLDER,
            f"Нет сотрудника для визы: {roles}. Назначьте роль в настройках и отправьте договор «На подпись» снова.",
            no_holder,
            settings_link=True,
        )
    returned = _roles(visas, "returned")
    if returned:
        remark = f" {request.comment}" if request.comment else ""
        return _blocker(
            RETURNED, f"Визы возвращены: {', '.join(returned)}.{remark}".strip(), returned, remark=request.comment
        )
    missing = _roles(visas, "pending")
    if missing:
        return _blocker(PENDING, f"Нужны визы: {', '.join(missing)}", missing)
    return None


def apply_visas_changed(data: dict) -> tuple[bool, str]:
    """`eds.signing.visas_changed`: проекция виз у запроса подписи той же редакции; событие старее применённого — пропуск."""
    from datetime import datetime

    from django.db import transaction
    from integration.models import CommercialSigningRequest as Request

    obj = data.get("object") or {}
    kind, object_id, version = obj.get("kind"), obj.get("object_id"), obj.get("version")
    if not kind or not object_id:
        return False, "invalid_object"
    changed_at = datetime.fromisoformat(str(data["changed_at"]).replace("Z", "+00:00"))
    with transaction.atomic():
        candidates = (
            Request.objects.select_for_update(of=("self",))
            .filter(kind=kind, object_id=object_id)
            .exclude(status=Request.Status.STALE)
            .order_by("-created_at", "-id")
        )
        # Версия для EDS — от отпечатка редакции (`signing_outbound._version`): та же редакция — та же версия.
        request = next((r for r in candidates if version is None or int(r.fingerprint[:7], 16) == version), None)
        if request is None:
            return False, "no_request"
        if request.visas_changed_at is not None and changed_at <= request.visas_changed_at:
            return False, "stale_event"
        request.visas = list(data.get("visas") or [])
        request.visas_changed_at = changed_at or timezone.now()
        request.save(update_fields=["visas", "visas_changed_at"])
    return True, "applied"
