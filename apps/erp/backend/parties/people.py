"""Люди компании — один источник (ADR-0028 п. 2).

Текстового «контактного лица» у компании нет: главный контакт — отметка `is_primary` в списке `Contact`. Поле API
`contact_person` (карточка компании, поставщик в каталоге) остаётся для совместимости и читается и пишется здесь.
"""

from typing import Optional

from django.db import transaction
from parties.models import Company, Contact
from parties.models.contacts import active_contact_q


def primary_contact(company: Optional[Company]) -> Optional[Contact]:
    """Главный действующий контакт; без отметки — первый действующий по имени."""
    if company is None or company.pk is None:
        return None
    cached = getattr(company, "_prefetched_objects_cache", {}).get("contacts")
    if cached is not None:  # список компаний с prefetch — без запроса на строку
        alive = sorted((p for p in cached if p.archived_at is None), key=lambda p: (not p.is_primary, p.name, p.pk))
        return alive[0] if alive else None
    people = Contact.objects.filter(active_contact_q(), company=company)
    return people.filter(is_primary=True).order_by("name", "pk").first() or people.order_by("name", "pk").first()


def contact_name(company: Optional[Company]) -> str:
    person = primary_contact(company)
    return person.name if person is not None else ""


def contact_names(companies) -> dict[int, str]:
    """Имена главных контактов страницы компаний одним запросом: `{company_id: имя}`."""
    names: dict[int, str] = {}
    people = Contact.objects.filter(active_contact_q(), company__in=list(companies)).order_by(
        "company_id", "-is_primary", "name", "pk"
    )
    for company_id, name in people.values_list("company_id", "name"):
        names.setdefault(company_id, name)
    return names


def set_contact_name(company: Company, name: str, *, actor=None) -> Optional[Contact]:
    """«Контактное лицо — X»: человек с этим именем становится главным; нет такого — заводится.

    Пустое имя людей не удаляет и отметку не снимает. Новый человек получает телефон и почту компании, чтобы с ним можно
    было связаться (`Contact.clean`).
    """
    name = (name or "").strip()
    if not name or company.pk is None:
        return None
    with transaction.atomic():
        people = Contact.objects.select_for_update().filter(active_contact_q(), company=company)
        person = next((p for p in people if p.name.strip().casefold() == name.casefold()), None)
        if person is None:
            person = Contact.objects.create(
                company=company,
                name=name[:255],
                phone=(company.phone or "")[:50],
                email=company.email or "",
                is_primary=True,
                created_by=actor if getattr(actor, "is_authenticated", False) else None,
            )
        elif not person.is_primary:
            person.is_primary = True
            person.save(update_fields=["is_primary", "updated_at"])
        Contact.objects.filter(company=company, is_primary=True).exclude(pk=person.pk).update(is_primary=False)
    return person
