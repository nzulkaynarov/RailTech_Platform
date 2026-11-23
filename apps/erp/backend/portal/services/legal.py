"""Оферта и политика Кабинета (ДВ-5): действующие редакции, акцепт контакта, черновики и публикация.

Правило входа: пока ни одна редакция не опубликована, кабинет открыт как раньше. С первой публикации контакт без акцепта
действующей редакции (каждого вида, у которого она есть) в кабинет не входит: сервер отвечает 403 `LEGAL_ACCEPTANCE_REQUIRED`
на любой эндпоинт, кроме профиля и самих документов. Новая редакция гасит акцепты неявно — у неё просто нет акцепта; прежние
записи остаются доказательством. Подстановки `{{company.*}}` заполняются при показе из реквизитов своей компании.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from portal.exceptions import PortalBadRequest, PortalConflict
from portal.models_legal import LegalAcceptance, LegalEdition, LegalKind

from core.audit import log_admin_action

LANGUAGES = ("ru", "uz", "en")
KINDS = tuple(LegalKind.values)
PLACEHOLDER = re.compile(r"\{\{\s*company\.(name|inn|address|support_email|phone)\s*\}\}")
#: Предел размера текста редакции: страховка от случайной вставки файла в поле.
MAX_TEXT = 60_000
#: Journal fallback texts (Russian, as core.audit requires); the SPA translates by event_code.
_ACCEPT_TEXT = {
    LegalKind.PRIVACY: "Клиент принял политику обработки персональных данных",
    LegalKind.TERMS: "Клиент принял условия использования кабинета",
}
_PUBLISH_TEXT = {
    LegalKind.PRIVACY: "Опубликована редакция политики обработки персональных данных",
    LegalKind.TERMS: "Опубликована редакция условий использования кабинета",
}


# ── подстановки ────────────────────────────────────────────────────────────────────────────────────────────────


def company_values() -> dict[str, str]:
    """Реквизиты своей компании для подстановок; чего нет — пустая строка (экран покажет «—»)."""
    from core.models.settings import SystemSetting
    from core.tenant import own_company

    setting = SystemSetting.load()
    company = own_company()
    name = (company.name if company else "") or (setting.platform_name if setting.company_profile_changed_at else "")
    return {
        "name": name or "",
        "inn": (getattr(company, "inn", "") or "") if company else "",
        "address": (getattr(company, "legal_address", "") or "") if company else "",
        "support_email": setting.support_email or (getattr(company, "email", "") or ""),
        "phone": (getattr(company, "phone", "") or "") if company else "",
    }


def _fill(text: str, values: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda match: values.get(match.group(1)) or "—", text or "")


def render_content(content: dict, values: dict[str, str]) -> dict:
    """Текст редакции с заполненными подстановками, во всех трёх языках."""

    def per_lang(node: dict | None) -> dict[str, str]:
        node = node or {}
        return {lang: _fill(node.get(lang, ""), values) for lang in LANGUAGES}

    return {
        "title": per_lang(content.get("title")),
        "lead": per_lang(content.get("lead")),
        "sections": [
            {"title": per_lang(section.get("title")), "body": per_lang(section.get("body"))}
            for section in content.get("sections") or []
        ],
    }


# ── действующие редакции и «нужен акцепт» ───────────────────────────────────────────────────────────────────────


def current_editions() -> dict[str, LegalEdition]:
    rows = LegalEdition.objects.filter(published_at__isnull=False, retired_at__isnull=True)
    return {row.kind: row for row in rows}


def pending_annotation(contact_field: str = "contact_id") -> Exists:
    """`Exists`: у контакта есть действующая редакция без его акцепта. Один подзапрос в выборке сессии — без лишних запросов."""
    accepted_by_contact = LegalAcceptance.objects.filter(
        edition_id=OuterRef("pk"), contact_id=OuterRef(OuterRef(contact_field))
    )
    return Exists(
        LegalEdition.objects.filter(published_at__isnull=False, retired_at__isnull=True).exclude(
            Exists(accepted_by_contact)
        )
    )


def needs_acceptance(contact_id: int) -> bool:
    return (
        LegalEdition.objects.filter(published_at__isnull=False, retired_at__isnull=True)
        .exclude(acceptances__contact_id=contact_id)
        .exists()
    )


def edition_row(edition: LegalEdition, values: dict[str, str], *, accepted: bool | None = None) -> dict[str, Any]:
    row = {
        "id": edition.pk,
        "kind": edition.kind,
        "label": edition.label,
        "published_at": edition.published_at,
        **render_content(edition.content, values),
    }
    if accepted is not None:
        row["accepted"] = accepted
    return row


def current_for_contact(contact_id: int) -> dict[str, Any]:
    values = company_values()
    editions = list(current_editions().values())
    accepted_ids = set(
        LegalAcceptance.objects.filter(contact_id=contact_id, edition__in=editions).values_list("edition_id", flat=True)
    )
    rows = [edition_row(edition, values, accepted=edition.pk in accepted_ids) for edition in editions]
    return {"needs_acceptance": any(not row["accepted"] for row in rows), "editions": rows}


def public_policy() -> dict[str, Any] | None:
    """Действующая политика для экрана входа или `None`, если она ещё не опубликована."""
    edition = current_editions().get(LegalKind.PRIVACY)
    return edition_row(edition, company_values()) if edition else None


# ── акцепт ─────────────────────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def accept(session, edition_ids: list[int], language: str, *, ip: str, user_agent: str) -> dict[str, Any]:
    """Записать акцепт действующих редакций от контакта сессии.

    `edition_ids` — то, что контакт видел на экране: если за это время вышла новая редакция, список расходится с
    действующими и акцепт отклоняется `LEGAL_EDITION_CHANGED` (контакт примет то, что прочитал, а не то, что вышло позже).
    Повтор безопасен: уже записанный акцепт второй строкой не дублируется.
    """
    if language not in LANGUAGES:
        raise PortalBadRequest("VALIDATION_ERROR")
    current = current_editions()
    if not current or set(edition_ids) != {edition.pk for edition in current.values()}:
        raise PortalConflict("LEGAL_EDITION_CHANGED")
    for edition in current.values():
        _, created = LegalAcceptance.objects.get_or_create(
            contact=session.contact,
            edition=edition,
            defaults={
                "company": session.company,
                "language": language,
                "auth_method": session.auth_method,
                "ip_address": ip or None,
                "user_agent": (user_agent or "")[:1000],
            },
        )
        if created:
            log_admin_action(
                entity_type="portal.legaledition",
                entity_id=edition.pk,
                action=f"{_ACCEPT_TEXT[edition.kind]}, редакция {edition.label}",
                actor=None,
                company_id=session.company_id,
                contact_id=session.contact_id,
                event_code="portal.legal.accepted",
                event_params={"kind": edition.kind, "edition": edition.label, "language": language},
            )
    return current_for_contact(session.contact_id)


# ── редакции для «Настроек» ─────────────────────────────────────────────────────────────────────────────────────


def editions_overview() -> list[dict[str, Any]]:
    """Все редакции по видам: статус, число акцептов; текст — отдельным запросом."""
    rows = []
    for edition in LegalEdition.objects.select_related("published_by").order_by("kind", "-created_at", "-id"):
        rows.append(
            {
                "id": edition.pk,
                "kind": edition.kind,
                "label": edition.label,
                "status": edition.status,
                "created_at": edition.created_at,
                "published_at": edition.published_at,
                "published_by": _person(edition.published_by),
                "retired_at": edition.retired_at,
                "acceptances_count": edition.acceptances.count(),
            }
        )
    return rows


def _person(user) -> str:
    if not user:
        return ""
    return (getattr(user, "get_full_name", lambda: "")() or user.get_username()).strip()


def edition_detail(edition: LegalEdition) -> dict[str, Any]:
    """Текст «как написано»: с подстановками `{{company.*}}`, чтобы их видел редактор; рендер — в `rendered`."""
    row = next(item for item in editions_overview() if item["id"] == edition.pk)
    return {**row, "content": edition.content, "rendered": render_content(edition.content, company_values())}


def _clean_content(content: Any) -> dict:
    """Проверка структуры текста редакции: три языка у каждого поля, только строки, размер в пределах."""
    if not isinstance(content, dict):
        raise PortalBadRequest("VALIDATION_ERROR")

    def per_lang(node: Any, *, required: bool) -> dict[str, str]:
        if not isinstance(node, dict) or any(not isinstance(node.get(lang, ""), str) for lang in LANGUAGES):
            raise PortalBadRequest("VALIDATION_ERROR")
        cleaned = {lang: node.get(lang, "").strip() for lang in LANGUAGES}
        if required and not all(cleaned.values()):
            raise PortalBadRequest("VALIDATION_ERROR")
        return cleaned

    sections = content.get("sections")
    if not isinstance(sections, list) or not sections:
        raise PortalBadRequest("VALIDATION_ERROR")
    cleaned = {
        "title": per_lang(content.get("title"), required=True),
        "lead": per_lang(content.get("lead"), required=False),
        "sections": [
            {
                "title": per_lang(section.get("title") if isinstance(section, dict) else None, required=True),
                "body": per_lang(section.get("body") if isinstance(section, dict) else None, required=True),
            }
            for section in sections
        ],
    }
    if len(str(cleaned)) > MAX_TEXT * 3:
        raise PortalBadRequest("VALIDATION_ERROR")
    return cleaned


def _new_label(kind: str) -> str:
    base = timezone.localdate().isoformat()
    taken = set(LegalEdition.objects.filter(kind=kind).values_list("label", flat=True))
    label, n = base, 1
    while label in taken:
        n += 1
        label = f"{base}-{n}"
    return label


def create_draft(kind: str, *, actor) -> LegalEdition:
    """Новая редакция — копия действующей (или последней, если действующей нет); черновик одного вида — один."""
    if kind not in KINDS:
        raise PortalBadRequest("VALIDATION_ERROR")
    if LegalEdition.objects.filter(kind=kind, published_at__isnull=True).exists():
        raise PortalConflict("LEGAL_DRAFT_EXISTS")
    source = (
        LegalEdition.objects.filter(kind=kind, published_at__isnull=False, retired_at__isnull=True).first()
        or LegalEdition.objects.filter(kind=kind).order_by("-created_at", "-id").first()
    )
    if source is None:
        raise PortalBadRequest("VALIDATION_ERROR")
    try:
        with transaction.atomic():
            return LegalEdition.objects.create(
                kind=kind, label=_new_label(kind), content=copy.deepcopy(source.content), created_by=actor
            )
    except IntegrityError:
        raise PortalConflict("LEGAL_DRAFT_EXISTS") from None


@transaction.atomic
def update_draft(edition_id: int, *, content: Any = None, label: str | None = None) -> LegalEdition:
    edition = LegalEdition.objects.select_for_update().get(pk=edition_id)
    if edition.published_at is not None:
        raise PortalConflict("LEGAL_EDITION_PUBLISHED")
    if label is not None:
        label = label.strip()
        if not label or len(label) > 40:
            raise PortalBadRequest("VALIDATION_ERROR")
        if LegalEdition.objects.filter(kind=edition.kind, label=label).exclude(pk=edition.pk).exists():
            raise PortalConflict("LEGAL_LABEL_TAKEN")
        edition.label = label
    if content is not None:
        edition.content = _clean_content(content)
    edition.save(update_fields=["label", "content"])
    return edition


@transaction.atomic
def release_edition(edition_id: int, *, actor) -> LegalEdition:
    """Опубликовать черновик: прежняя действующая того же вида снимается, новая действует; одна запись в журнал."""
    edition = LegalEdition.objects.select_for_update().get(pk=edition_id)
    if edition.published_at is not None:
        raise PortalConflict("LEGAL_EDITION_PUBLISHED")
    _clean_content(edition.content)
    now = timezone.now()
    previous = list(
        LegalEdition.objects.select_for_update().filter(
            kind=edition.kind, published_at__isnull=False, retired_at__isnull=True
        )
    )
    for old in previous:
        old.retired_at = now
        old.save(update_fields=["retired_at"])
    edition.published_at = now
    edition.published_by = actor
    edition.save(update_fields=["published_at", "published_by"])
    log_admin_action(
        entity_type="portal.legaledition",
        entity_id=edition.pk,
        action=f"{_PUBLISH_TEXT[edition.kind]} {edition.label}",
        actor=actor,
        event_code="admin.portal_legal.published",
        event_params={"kind": edition.kind, "edition": edition.label, "replaced": [old.label for old in previous]},
    )
    return edition


@transaction.atomic
def discard_draft(edition_id: int) -> None:
    edition = LegalEdition.objects.select_for_update().get(pk=edition_id)
    if edition.published_at is not None:
        raise PortalConflict("LEGAL_EDITION_PUBLISHED")
    edition.delete()


def acceptances_page(queryset=None):
    """Строки журнала акцептов: контакт, организация, редакция, время, язык."""
    return (queryset if queryset is not None else LegalAcceptance.objects.all()).select_related(
        "contact", "company", "edition"
    )


def acceptance_row(item: LegalAcceptance) -> dict[str, Any]:
    return {
        "id": item.pk,
        "accepted_at": item.accepted_at,
        "kind": item.edition.kind,
        "edition": item.edition.label,
        "edition_id": item.edition_id,
        "language": item.language,
        "auth_method": item.auth_method,
        "contact": {"id": item.contact_id, "name": item.contact.name, "email": item.contact.email or ""},
        "company": {"id": item.company_id, "name": item.company.name},
    }
