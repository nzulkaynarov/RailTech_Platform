"""Бизнес-логика заявок на категорию (R6, D7). Rule 8: вью — тонкая обёртка над этим модулем.

Паттерн заимствован у заявок на роль компании (`accounts/services/applications.py`): подача →
уведомление платформе → решение оператора с обязательным основанием → уведомление автору.
Отличие ровно одно и оно принципиальное (Rule 1): одобрение НЕ создаёт строку справочника.
Категорию заводит оператор своим инструментом и ПРИВЯЗЫВАЕТ её к заявке — иначе таксономию
площадки наполнял бы свободный ввод продавцов, чего эталон (Google Merchant Center) не
допускает.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Ссылка операторской плоскости, куда ведёт уведомление о новом обращении.
OPERATOR_LINK = "#admin-categories"


def submitting_company_id(user) -> int | None:
    """Компания, от имени которой человек просит категорию.

    Продавцовое членство в приоритете (категория нужна тому, кто ведёт каталог), но подать
    обращение может любой участник любой своей компании: просьба «заведите категорию» — не
    бизнес-операция и запирать её ролью не за что.
    """
    from accounts.services.permissions import primary_seller_company_id

    seller_company_id = primary_seller_company_id(user)
    if seller_company_id:
        return seller_company_id
    membership = user.memberships.filter(is_active=True).order_by("-is_primary", "id").first()
    return membership.company_id if membership else None


@transaction.atomic
def submit_category_request(
    *,
    user,
    proposed_name: str,
    parent=None,
    domain_type=None,
    justification: str = "",
) -> tuple[object | None, str | None]:
    """Подать обращение. Возвращает `(request, error_code)`."""

    from .models import CategoryRequest

    cleaned_name = (proposed_name or "").strip()
    if not cleaned_name:
        return None, "CATEGORY_REQUEST_NAME_REQUIRED"
    company_id = submitting_company_id(user)
    if not company_id:
        return None, "COMPANY_REQUIRED"

    duplicate = CategoryRequest.objects.filter(
        company_id=company_id,
        status=CategoryRequest.STATUS_PENDING,
        proposed_name__iexact=cleaned_name,
    ).first()
    if duplicate is not None:
        # Не блокировка, а честный ответ: обращение уже лежит у оператора. Второе такое же
        # ничего не ускорит, а очередь замусорит.
        return None, "CATEGORY_REQUEST_ALREADY_PENDING"

    request_row = CategoryRequest.objects.create(
        company_id=company_id,
        requested_by=user,
        proposed_name=cleaned_name,
        parent=parent,
        domain_type=domain_type,
        justification=(justification or "").strip(),
    )
    _notify_operators(request_row)
    return request_row, None


def _notify_operators(request_row) -> None:
    """Уведомление платформе. Сбой доставки НЕ откатывает поданное обращение."""
    from notifications.services import notify_platform_admins

    try:
        notify_platform_admins(
            title="Запрошена новая категория",
            message=f"{request_row.company.name}: «{request_row.proposed_name}»",
            link=OPERATOR_LINK,
            type_code="INFO",
            # По проводам — код и параметры, слова собирает витрина на языке ЗРИТЕЛЯ
            # (ARCH-05; так же устроены журнал сделки и остальные уведомления).
            event_code="catalog.category_requested",
            event_params={
                "request_id": request_row.pk,
                "company_name": request_row.company.name,
                "category_name": request_row.proposed_name,
            },
        )
    except Exception:  # noqa: BLE001 — fault barrier: обращение важнее уведомления о нём
        logger.exception("Failed to notify operators about category request %s", request_row.pk)


@transaction.atomic
def approve_category_request(request_row, *, reviewer, category) -> tuple[object | None, str | None]:
    """Закрыть обращение заведённой категорией. Возвращает `(request, error_code)`.

    `category` обязателен: одобрение без строки справочника означало бы «да, категория будет»
    без ответа на вопрос «куда класть товар» — то есть тот же тупик, только с зелёным
    статусом.
    """
    from .models import CategoryRequest

    if request_row.status not in CategoryRequest.OPEN_STATUSES:
        return None, "CATEGORY_REQUEST_ALREADY_REVIEWED"
    if category is None:
        return None, "CATEGORY_REQUIRED"

    before_status = request_row.status
    request_row.status = CategoryRequest.STATUS_APPROVED
    request_row.resulting_category = category
    request_row.reviewed_by = reviewer
    request_row.reviewed_at = timezone.now()
    request_row.save(
        update_fields=["status", "resulting_category", "reviewed_by", "reviewed_at", "updated_at"],
    )
    _log_review(request_row, reviewer, before_status, level="SUCCESS")
    _notify_requester(request_row, approved=True)
    return request_row, None


@transaction.atomic
def reject_category_request(request_row, *, reviewer, reason: str) -> tuple[object | None, str | None]:
    """Отклонить обращение. Причина обязательна — у отказа должно быть основание."""
    from .models import CategoryRequest

    if request_row.status not in CategoryRequest.OPEN_STATUSES:
        return None, "CATEGORY_REQUEST_ALREADY_REVIEWED"
    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        return None, "REASON_REQUIRED"

    before_status = request_row.status
    request_row.status = CategoryRequest.STATUS_REJECTED
    request_row.review_notes = cleaned_reason
    request_row.reviewed_by = reviewer
    request_row.reviewed_at = timezone.now()
    request_row.save(
        update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "updated_at"],
    )
    _log_review(request_row, reviewer, before_status, level="WARNING")
    _notify_requester(request_row, approved=False)
    return request_row, None


def _log_review(request_row, reviewer, before_status: str, *, level: str) -> None:
    from core.audit import log_admin_action

    log_admin_action(
        entity_type="category_request",
        entity_id=request_row.pk,
        action="Заявка на категорию рассмотрена",
        detail=f"{request_row.company.name} → «{request_row.proposed_name}»",
        event_code="catalog.category_request_reviewed",
        event_params={
            "company_name": request_row.company.name,
            "category_name": request_row.proposed_name,
            "status_code": request_row.status,
        },
        actor=reviewer,
        reason=request_row.review_notes,
        before={"status": before_status},
        after={"status": request_row.status},
        level=level,
        company_id=request_row.company_id,
    )


def _notify_requester(request_row, *, approved: bool) -> None:
    """Ответ автору обращения — тем же каналом, что и остальные события платформы."""
    from notifications.services import notify_user

    if request_row.requested_by_id is None:
        return
    resulting_name = request_row.resulting_category.name if request_row.resulting_category_id else ""
    common = {
        "user": request_row.requested_by,
        "title": "Заявка на категорию рассмотрена",
        "message": f"«{request_row.proposed_name}»: {request_row.status}",
        # Ведём в справочник — туда, где категория теперь есть (или где видно решение).
        "link": "#catalog-reference?ref=categories",
        "event_params": {
            "category_name": request_row.proposed_name,
            "resulting_name": resulting_name,
            "reason": request_row.review_notes,
        },
    }
    try:
        # Коды написаны ЛИТЕРАЛАМИ у самого вызова: guard-тест покрытия подписей
        # (`frontend/src/i18n/__tests__/activityCoverage.test.ts`) читает исходники бэкенда, и
        # код, спрятанный в переменную, прошёл бы мимо проверки — то есть уехал бы на прод
        # без подписи и напечатался бы по-русски в английской ленте.
        if approved:
            notify_user(**common, type_code="SUCCESS", event_code="catalog.category_request_approved")
        else:
            notify_user(**common, type_code="WARNING", event_code="catalog.category_request_rejected")
    except Exception:  # noqa: BLE001 — fault barrier: решение оператора не откатывается из-за уведомления
        logger.exception("Failed to notify author of category request %s", request_row.pk)
