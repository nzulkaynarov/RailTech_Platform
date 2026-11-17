"""Люди компании — один источник (ADR-0028 п. 2): главный контакт вместо текстового «контактного лица»."""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from parties.models import Company, Contact
from parties.people import contact_name, contact_names, primary_contact, set_contact_name

pytestmark = pytest.mark.django_db

migration = importlib.import_module("parties.migrations.0027_contact_person_to_people")


def _company(**extra) -> Company:
    return Company.objects.create(name="ООО Пример", inn=extra.pop("inn", "300100200"), **extra)


def test_set_contact_name_creates_primary_person_with_company_channels():
    company = _company(phone="+998 71 200-00-00", email="office@example.uz")
    other = Contact.objects.create(company=company, name="Бухгалтер", email="b@example.uz", is_primary=True)

    person = set_contact_name(company, "  Рустам Ахмедов ")

    assert person.name == "Рустам Ахмедов" and person.is_primary
    assert (person.phone, person.email) == ("+998 71 200-00-00", "office@example.uz")
    other.refresh_from_db()
    assert not other.is_primary
    assert contact_name(company) == "Рустам Ахмедов"


def test_set_contact_name_marks_existing_person_without_duplicate():
    company = _company()
    person = Contact.objects.create(company=company, name="Нилуфар Каримова", phone="+998 93 000-00-00")

    assert set_contact_name(company, "нилуфар каримова").pk == person.pk
    assert Contact.objects.filter(company=company).count() == 1
    person.refresh_from_db()
    assert person.is_primary


def test_empty_name_keeps_people():
    company = _company()
    person = Contact.objects.create(company=company, name="Иван", phone="1", is_primary=True)

    assert set_contact_name(company, " ") is None
    assert primary_contact(company).pk == person.pk


def test_primary_contact_skips_archived_and_batch_names_match():
    from django.utils import timezone

    first = _company()
    second = _company(inn="300100201")
    Contact.objects.create(company=first, name="Архивный", phone="1", is_primary=True, archived_at=timezone.now())
    Contact.objects.create(company=first, name="Действующий", phone="2")
    Contact.objects.create(company=second, name="Второй", phone="3", is_primary=True)

    assert contact_name(first) == "Действующий"
    assert contact_names([first, second]) == {first.pk: "Действующий", second.pk: "Второй"}
    prefetched = Company.objects.prefetch_related("contacts").get(pk=first.pk)
    assert contact_name(prefetched) == "Действующий"


def test_migration_moves_text_to_people_and_rollback_restores_text():
    created = _company(contact_person="Отдел продаж", phone="+998 71 1", email="s@example.uz")
    matched = _company(inn="300100202", contact_person="Анна Ли")
    anna = Contact.objects.create(company=matched, name="анна ли", phone="5")
    Contact.objects.create(company=matched, name="Борис", phone="6", is_primary=True)
    untouched = _company(inn="300100203")

    migration.forwards(apps, None)

    created.refresh_from_db()
    matched.refresh_from_db()
    assert created.contact_person == "" and matched.contact_person == ""
    assert contact_name(created) == "Отдел продаж"
    assert primary_contact(created).email == "s@example.uz"
    anna.refresh_from_db()
    assert anna.is_primary and Contact.objects.filter(company=matched, is_primary=True).count() == 1
    assert not Contact.objects.filter(company=untouched).exists()

    migration.backwards(apps, None)

    created.refresh_from_db()
    matched.refresh_from_db()
    assert created.contact_person == "Отдел продаж"
    assert matched.contact_person == "анна ли"
