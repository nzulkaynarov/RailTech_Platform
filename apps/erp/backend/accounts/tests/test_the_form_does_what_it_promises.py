"""
Форма делает то, что обещает: поле пишет в модель, тип задаётся, признак переназначается.

Замеры скептиков 26-08 по находкам 29, 39, 58, 92 прогона 20-08.

* **29.** Поле «Контакт (телефон)» карточки компании читало и писало ключ `contact_info`,
  которого у модели НЕТ (поле называется `phone`). DRF молча выбрасывает незнакомый ключ,
  PATCH возвращает 200 — и оператор видел зелёный тост при нулевой записи. Фантомное поле
  жило и в TS-типе, поэтому расхождение не ловил даже `tsc`.
* **92.** Экран реестра компаний фильтрует вкладками ИМЕННО по типу компании — и не давал
  тип задать: `company_types` было объявлено `SerializerMethodField` (только чтение), а в
  форме поля типа не было вовсе. Заведённый оператором арендатор не попадал ни в одну вкладку
  того же экрана; единственный путь задать тип — инженерный мастер Unfold.
* **39.** Основное членство у человека ровно одно — это ограничение БД
  (`unique_primary_company_per_user`). Сервис признак не переназначал и `IntegrityError` не
  ловил: добавление второй компании с галкой «Сделать основным» роняло сервер в 500, а
  членство не создавалось вовсе.
* **58.** Номер редакции кэша справочника двигали ТОЛЬКО хуки вьюсета, то есть один путь
  записи — API. Инженерная админка пишет ту же таблицу напрямую, и правка оттуда до десяти
  минут не доходила до арендаторов. Это зазор починки #603: там инвалидацию повесили на ПУТЬ,
  а не на запись модели.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        is_superuser=True,
        email="ops@form.test",
        username="ops_form",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )


@pytest.fixture
def company(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент", "sort_order": 10})
    return Company.objects.create(name="Компания формы", inn="908600001")


# ── 29. Поле пишет в модель, а не в никуда ──────────────────────────────────


def test_the_phone_field_actually_saves(operator, company):
    resp = _api(operator).patch(
        f"/api/v1/accounts/companies/{company.pk}/", {"phone": "+998 90 123-45-67"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    company.refresh_from_db()
    assert company.phone == "+998 90 123-45-67"


def test_the_phantom_field_is_gone_from_the_contract(operator, company):
    """`contact_info` не должно быть ни в ответе, ни в списке полей: пока оно числилось в
    TS-типе, форма компилировалась и слала его в PATCH."""
    body = _api(operator).get(f"/api/v1/accounts/companies/{company.pk}/").json()

    assert "contact_info" not in body
    assert "phone" in body


def test_every_writable_field_of_the_operator_form_exists_on_the_model(db):
    """Гард против всего класса: DRF молча глотает незнакомый ключ и отвечает 200, поэтому
    расхождение формы с моделью не даёт ни ошибки, ни следа — только ложный успех."""
    from accounts.serializers import CompanySerializer

    serializer = CompanySerializer()
    model_fields = {f.name for f in Company._meta.get_fields()}
    writable = {
        name
        for name, field in serializer.fields.items()
        if not field.read_only and not isinstance(field, type(serializer.fields["company_types"]))
    }

    unknown = {name for name in writable if name not in model_fields}

    assert unknown == set(), f"поля сериализатора без соответствия в модели: {unknown}"


# ── 92. Экран владеет полем, по которому фильтрует ──────────────────────────


def test_the_operator_can_set_the_company_type(operator, company):
    resp = _api(operator).patch(f"/api/v1/accounts/companies/{company.pk}/", {"types": ["SUPPLIER"]}, format="json")

    assert resp.status_code == 200, resp.content
    codes = set(company.types.values_list("code", flat=True))
    # SUPPLIER тянет за собой CLIENT — это не побочный эффект записи, а правило продукта
    # (`accounts/signals.py`: продавец умеет и покупать). Закрепляем, чтобы следующая правка
    # типов не сняла его молча.
    assert "SUPPLIER" in codes
    assert codes == {"SUPPLIER", "CLIENT"}, codes


def test_the_created_company_lands_in_the_tab_it_was_given(operator, db):
    """Смысл находки: арендатор, заведённый оператором, не попадал ни в одну вкладку ТОГО ЖЕ
    экрана — а вкладки фильтруют по `types__code`."""
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    client = _api(operator)

    created = client.post(
        "/api/v1/accounts/companies/",
        {"name": "Новый продавец", "inn": "908600002", "types": ["SUPPLIER"]},
        format="json",
    )

    assert created.status_code == 201, created.content
    listed = client.get("/api/v1/accounts/companies/?types__code=SUPPLIER").json()
    rows = listed["results"] if isinstance(listed, dict) else listed
    assert any(row["inn"] == "908600002" for row in rows), "компания обязана попасть в свою вкладку"


def test_an_unknown_type_code_is_refused_not_swallowed(operator, company):
    resp = _api(operator).patch(f"/api/v1/accounts/companies/{company.pk}/", {"types": ["NO_SUCH_TYPE"]}, format="json")

    assert resp.status_code == 400
    assert company.types.count() == 0


def test_types_are_written_by_code_not_by_id(operator, company):
    """Rule 2: сравнение и запись по коду. Идентификатор справочника отличается между стендами."""
    supplier = CompanyType.objects.get(code="SUPPLIER")

    resp = _api(operator).patch(f"/api/v1/accounts/companies/{company.pk}/", {"types": [supplier.pk]}, format="json")

    assert resp.status_code == 400, "идентификатор не принимается — только код"


# ── 39. Основное членство переназначается, а не роняет сервер ───────────────


@pytest.fixture
def member_user(db):
    return CustomUser.objects.create_user(
        email="member@form.test", username="member_form", password="x", is_active=True
    )


def _add_membership(operator, member_user, company, *, primary):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    return _api(operator).post(
        f"/api/v1/accounts/users/{member_user.pk}/add-membership/",
        {"company": company.pk, "workspace_role": "OWNER", "is_primary": primary},
        format="json",
    )


def test_a_second_primary_membership_reassigns_instead_of_crashing(operator, member_user, company, db):
    second = Company.objects.create(name="Вторая компания", inn="908600003")

    first = _add_membership(operator, member_user, company, primary=True)
    assert first.status_code in (200, 201), first.content

    resp = _add_membership(operator, member_user, second, primary=True)

    assert resp.status_code in (200, 201), resp.content
    primary_companies = list(
        CompanyMember.objects.filter(user=member_user, is_primary=True).values_list("company__inn", flat=True)
    )
    assert primary_companies == ["908600003"], "основное членство ровно одно — и это новое"


def test_the_previous_membership_survives_as_non_primary(operator, member_user, company, db):
    """Переназначение, а не удаление: человек остаётся в обеих компаниях."""
    second = Company.objects.create(name="Вторая компания", inn="908600004")
    _add_membership(operator, member_user, company, primary=True)
    _add_membership(operator, member_user, second, primary=True)

    assert CompanyMember.objects.filter(user=member_user).count() == 2
    assert CompanyMember.objects.get(user=member_user, company=company).is_primary is False


def test_adding_without_the_primary_flag_changes_nothing(operator, member_user, company, db):
    second = Company.objects.create(name="Вторая компания", inn="908600005")
    _add_membership(operator, member_user, company, primary=True)

    _add_membership(operator, member_user, second, primary=False)

    assert CompanyMember.objects.get(user=member_user, company=company).is_primary is True


# ── 58. Кэш сбрасывает ЗАПИСЬ МОДЕЛИ, а не путь записи ──────────────────────


def test_writing_the_model_directly_invalidates_the_api_cache(db):
    """Инженерная админка, management-команда и шелл пишут ту же таблицу мимо вьюсета.
    Инвалидация, привязанная к пути, их не замечала — и правка до десяти минут не доходила."""
    from master_data.models import UnitOfMeasure

    key = "lookup-version:master_data.unitofmeasure"
    cache.set(key, 1, None)

    UnitOfMeasure.objects.create(code="SIG_UOM", name="Сигнальная", sort_order=960)

    assert cache.get(key) > 1, "запись модели обязана двигать номер редакции"


def test_deleting_the_model_invalidates_too(db):
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code="SIG_UOM2", name="Вторая", sort_order=961)
    key = "lookup-version:master_data.unitofmeasure"
    cache.set(key, 5, None)

    unit.delete()

    assert cache.get(key) > 5


def test_an_unrelated_model_does_not_bump_the_lookup_version(db):
    """Обратная сторона: приёмник подписан без `sender=`, и без отбора он сбрасывал бы кэш
    справочников на КАЖДУЮ запись в базе."""
    key = "lookup-version:master_data.unitofmeasure"
    cache.set(key, 7, None)

    Company.objects.create(name="Не справочник", inn="908600009")

    assert cache.get(key) == 7


def test_the_api_list_shows_the_change_made_outside_the_viewset(db):
    """Проверяем СМЫСЛ, а не только счётчик: список отдаёт новое имя, а не страницу из кэша."""
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code="SIG_UOM3", name="Старое имя", sort_order=962)
    client = APIClient()
    first = client.get("/api/v1/master-data/units/").json()
    assert any(row["name"] == "Старое имя" for row in first), "заготовка обязана попасть в кэшированный список"

    UnitOfMeasure.objects.filter(pk=unit.pk).update(name="Новое имя")
    # `.update()` НЕ шлёт post_save — это ровно тот путь, которым пишет и `list_editable`.
    from master_data.signals import bump_lookup_version

    bump_lookup_version(UnitOfMeasure)

    second = client.get("/api/v1/master-data/units/").json()
    assert any(row["name"] == "Новое имя" for row in second)
