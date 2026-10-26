"""R6 (spec-nomenclature-ux-audit-2026-08-05, D7) — «нужной категории нет» перестало быть тупиком.

До R6 справочник категорий только читался, при этом подпись страницы обещала «Управление
деревом категорий». Продавец, чей товар не ложился ни в одну строку, не мог ни опубликовать
карточку (категория — требование порога полноты), ни попросить категорию: обращения к
платформе из этого места не существовало.

Решение по бенчмарку (Google Merchant Center, двухслойная модель): таксономия площадки
остаётся авторитетной, продавцу даётся escape-hatch — заявка оператору. Тесты держат три
свойства этого решения:

  * заявка НИЧЕГО не создаёт сама (Rule 1) — категорию заводит оператор и привязывает её;
  * компания-автор считается СЕРВЕРОМ, чужие обращения не видны (многотенантность);
  * у отказа обязательно есть основание, а решение доходит до автора уведомлением.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole
from catalog.models import Category, CategoryRequest
from notifications.models import Notification

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/catalog/category-requests/"


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _seller_company(name: str, inn: str) -> Company:
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(supplier_type)
    return company


def _seller_member(company: Company, email: str, permissions=("catalog.manage",)) -> CustomUser:
    workspace_role, _ = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
    )
    company_role = CompanyRole.objects.create(company=company, name=f"Роль {email}", permissions=list(permissions))
    user = CustomUser.objects.create_user(email=email, username=email, password="pw")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role,
        company_roles=[company_role],
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user


def _operator(email: str = "operator@r6.test") -> CustomUser:
    admin_role, _ = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Администратор"})
    return CustomUser.objects.create_user(
        is_superuser=True, email=email, username=email, password="pw", role=admin_role
    )


@pytest.fixture
def world(db):
    company = _seller_company("ООО Р6", "9600000001")
    return {
        "company": company,
        "seller": _seller_member(company, "seller@r6.test"),
        "operator": _operator(),
    }


def test_seller_submits_request_and_operators_are_notified(world):
    """Подача — один POST; компанию подставляет сервер, платформа получает уведомление."""
    response = _client_for(world["seller"]).post(
        ENDPOINT,
        {"proposed_name": "Тормозные колодки композитные", "justification": "Три позиции из заявки №12"},
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.data["status"] == "PENDING"
    row = CategoryRequest.objects.get(pk=response.data["id"])
    assert row.company_id == world["company"].pk
    assert row.requested_by_id == world["seller"].pk

    alert = Notification.objects.filter(audience=Notification.AUDIENCE_PLATFORM_ADMIN).first()
    assert alert is not None
    # По проводам — код и параметры (ARCH-05), слова собирает витрина на языке зрителя.
    assert alert.event_code == "catalog.category_requested"
    assert alert.event_params["category_name"] == "Тормозные колодки композитные"


def test_company_is_not_taken_from_the_request_body(world):
    """Компанию нельзя подменить телом запроса — иначе обращение подавалось бы «от чужого имени»."""
    other = _seller_company("ООО Чужая", "9600000002")

    response = _client_for(world["seller"]).post(
        ENDPOINT, {"proposed_name": "Буксовые узлы", "company": other.pk}, format="json"
    )

    assert response.status_code == 201, response.content
    assert CategoryRequest.objects.get(pk=response.data["id"]).company_id == world["company"].pk


def test_duplicate_pending_request_is_answered_not_stacked(world):
    """Второе такое же обращение ничего не ускорит — сервер говорит об этом кодом, а не молчит."""
    client = _client_for(world["seller"])
    client.post(ENDPOINT, {"proposed_name": "Рессорное подвешивание"}, format="json")

    response = client.post(ENDPOINT, {"proposed_name": "  рессорное подвешивание "}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "CATEGORY_REQUEST_ALREADY_PENDING"
    assert CategoryRequest.objects.count() == 1


def test_request_never_creates_a_category_by_itself(world):
    """Rule 1: таксономию наполняет ОПЕРАТОР, а не свободный ввод продавца."""
    categories_before = Category.objects.count()

    _client_for(world["seller"]).post(ENDPOINT, {"proposed_name": "Совершенно новая ветка"}, format="json")

    assert Category.objects.count() == categories_before
    assert not Category.objects.filter(name="Совершенно новая ветка").exists()


def test_approve_requires_the_category_the_operator_actually_created(world):
    """Одобрение без строки справочника — тот же тупик, только с зелёным статусом."""
    row = CategoryRequest.objects.create(company=world["company"], proposed_name="Гидравлика")

    response = _client_for(world["operator"]).post(f"{ENDPOINT}{row.pk}/approve/", {}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "CATEGORY_REQUIRED"
    row.refresh_from_db()
    assert row.status == "PENDING"


def test_approve_links_the_category_and_answers_the_author(world):
    row = CategoryRequest.objects.create(
        company=world["company"], requested_by=world["seller"], proposed_name="Гидравлика"
    )
    created = Category.objects.create(name="Гидравлика")

    response = _client_for(world["operator"]).post(
        f"{ENDPOINT}{row.pk}/approve/", {"category": created.pk}, format="json"
    )

    assert response.status_code == 200, response.content
    row.refresh_from_db()
    assert row.status == "APPROVED"
    assert row.resulting_category_id == created.pk
    assert row.reviewed_by_id == world["operator"].pk
    answer = Notification.objects.filter(user=world["seller"]).first()
    assert answer is not None
    assert answer.event_code == "catalog.category_request_approved"


def test_rejection_without_a_reason_is_refused(world):
    row = CategoryRequest.objects.create(company=world["company"], proposed_name="Прочее")

    response = _client_for(world["operator"]).post(f"{ENDPOINT}{row.pk}/reject/", {"reason": "  "}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "REASON_REQUIRED"
    row.refresh_from_db()
    assert row.status == "PENDING"


def test_rejection_with_a_reason_closes_the_request(world):
    row = CategoryRequest.objects.create(company=world["company"], requested_by=world["seller"], proposed_name="Прочее")

    response = _client_for(world["operator"]).post(
        f"{ENDPOINT}{row.pk}/reject/", {"reason": "Подходит «Запасные части»"}, format="json"
    )

    assert response.status_code == 200, response.content
    row.refresh_from_db()
    assert row.status == "REJECTED"
    assert row.review_notes == "Подходит «Запасные части»"
    answer = Notification.objects.filter(user=world["seller"]).first()
    assert answer is not None
    assert answer.event_code == "catalog.category_request_rejected"


def test_reviewed_request_cannot_be_reviewed_twice(world):
    row = CategoryRequest.objects.create(company=world["company"], proposed_name="Гидравлика")
    created = Category.objects.create(name="Гидравлика")
    client = _client_for(world["operator"])
    client.post(f"{ENDPOINT}{row.pk}/approve/", {"category": created.pk}, format="json")

    response = client.post(f"{ENDPOINT}{row.pk}/reject/", {"reason": "Передумал"}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "CATEGORY_REQUEST_ALREADY_REVIEWED"


def test_seller_sees_only_his_own_company_requests(world):
    """Многотенантность: обращение соседа не видно ни в списке, ни поштучно."""
    stranger_company = _seller_company("ООО Сосед", "9600000003")
    stranger = _seller_member(stranger_company, "stranger@r6.test")
    mine = CategoryRequest.objects.create(company=world["company"], proposed_name="Моя ветка")
    theirs = CategoryRequest.objects.create(company=stranger_company, proposed_name="Чужая ветка")

    listing = _client_for(world["seller"]).get(ENDPOINT)
    detail = _client_for(world["seller"]).get(f"{ENDPOINT}{theirs.pk}/")

    ids = (
        [item["id"] for item in listing.data["results"]]
        if "results" in listing.data
        else [item["id"] for item in listing.data]
    )
    assert ids == [mine.pk]
    assert detail.status_code == 404
    assert stranger.pk  # сосед заведён именно как участник другой компании


def test_seller_cannot_review_his_own_request(world):
    """Решение — операторское действие: продавец не закрывает собственное обращение."""
    row = CategoryRequest.objects.create(company=world["company"], proposed_name="Сам себе оператор")
    created = Category.objects.create(name="Сам себе оператор")

    response = _client_for(world["seller"]).post(
        f"{ENDPOINT}{row.pk}/approve/", {"category": created.pk}, format="json"
    )

    assert response.status_code == 403
    row.refresh_from_db()
    assert row.status == "PENDING"


def test_operator_sees_every_pending_request(world):
    CategoryRequest.objects.create(company=world["company"], proposed_name="Первая")
    other_company = _seller_company("ООО Вторая", "9600000004")
    CategoryRequest.objects.create(company=other_company, proposed_name="Вторая")

    response = _client_for(world["operator"]).get(f"{ENDPOINT}?status=PENDING")

    assert response.status_code == 200
    payload = response.data["results"] if "results" in response.data else response.data
    assert len(payload) == 2


def test_settings_editor_reviews_requests_without_superuser(world):
    """W13-A3: решение — по праву `settings.edit` (раздел Платформы «Компания»), а не только суперпользователь."""
    editor = _seller_member(world["company"], "editor@r6.test", permissions=("settings.edit",))
    approved = CategoryRequest.objects.create(company=world["company"], proposed_name="Одобрить")
    rejected = CategoryRequest.objects.create(company=world["company"], proposed_name="Отклонить")
    created = Category.objects.create(name="Одобрить")
    client = _client_for(editor)

    ok = client.post(f"{ENDPOINT}{approved.pk}/approve/", {"category": created.pk}, format="json")
    no = client.post(f"{ENDPOINT}{rejected.pk}/reject/", {"reason": "Дубль"}, format="json")

    assert (ok.status_code, no.status_code) == (200, 200)
    approved.refresh_from_db()
    rejected.refresh_from_db()
    assert (approved.status, rejected.status) == ("APPROVED", "REJECTED")


def test_member_without_settings_edit_cannot_review_even_with_catalog_manage(world):
    """`catalog.manage` ведёт справочник и подаёт запросы, но решение — только `settings.edit`."""
    row = CategoryRequest.objects.create(company=world["company"], proposed_name="Без права")
    created = Category.objects.create(name="Без права")
    client = _client_for(world["seller"])

    approve = client.post(f"{ENDPOINT}{row.pk}/approve/", {"category": created.pk}, format="json")
    reject = client.post(f"{ENDPOINT}{row.pk}/reject/", {"reason": "Нет"}, format="json")

    assert (approve.status_code, reject.status_code) == (403, 403)
    row.refresh_from_db()
    assert row.status == "PENDING"
