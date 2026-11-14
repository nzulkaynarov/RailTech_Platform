"""PART-2 (ADR-0022 п. 4): «Мои товары» партнёра — список, карточка, отправка на проверку, подтверждение актуальности.

Партнёр видит только своё. Негативные тесты: чужие карточки, чужие цены, факт других поставщиков, наши цены; отправка
чужой и опубликованной карточки; публикации из портала нет; клиент без модуля — 403; без `can_act` — 403 на изменениях.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from parties.models import CompanyRelationship
from portal.tests.partner_world import PREFIX, client_for, make_card, make_offer

from catalog.models import Product, ProductReview, SupplierOffer
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def ids(response):
    return {item["id"] for item in response.json()["items"]}


class TestList:
    def test_partner_sees_own_cards_and_cards_with_own_offer(self, partner_world):
        w = partner_world
        response = w["client_a"].get(f"{PREFIX}/products")
        assert response.status_code == 200
        c = w["cards"]
        assert ids(response) == {
            c["draft"].pk,
            c["review"].pk,
            c["returned"].pk,
            c["published"].pk,
            c["shared"].pk,
            c["b_draft_with_a_offer"].pk,
        }

    def test_foreign_cards_prices_and_internal_layer_are_not_in_the_response(self, partner_world):
        w = partner_world
        text = w["client_a"].get(f"{PREFIX}/products").content.decode()
        for forbidden in (
            "Секретная деталь",  # карточка Б без цены А
            "Деталь Б-2 в работе",  # чужая неопубликованная карточка с ценой А: её название А не видит
            "Секретное описание",
            '"555.55"',  # цена Б по своей карточке (сумма — строка JSON; голая подстрока совпала бы со временем)
            '"9.99"',  # цена Б по общей карточке
            "EUR",
            w["b"].name,
            "base_price",
            "list_price",
            "margin",
            "supplier",
            "cost",
        ):
            assert forbidden not in text, forbidden

    def test_own_price_only_on_shared_card(self, partner_world):
        w = partner_world
        item = next(
            i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["shared"].pk
        )
        assert item["offer"]["price"] == {"amount": "11.00", "currency": "USD"}
        assert item["is_own"] is False and item["can_submit"] is False
        b_item = next(
            i for i in w["client_b"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["shared"].pk
        )
        assert b_item["offer"]["price"] == {"amount": "9.99", "currency": "EUR"}

    def test_statuses_counts_and_reason(self, partner_world):
        w = partner_world
        body = w["client_a"].get(f"{PREFIX}/products").json()
        by_id = {i["id"]: i for i in body["items"]}
        c = w["cards"]
        assert by_id[c["draft"].pk]["status"] == "draft" and by_id[c["draft"].pk]["can_submit"] is True
        assert by_id[c["review"].pk]["status"] == "review" and by_id[c["review"].pk]["can_submit"] is False
        returned = by_id[c["returned"].pk]
        assert returned["status"] == "returned" and returned["return_reason"] == "Нет артикула производителя"
        assert returned["can_submit"] is True
        assert returned["return_issues"] == [
            {"field": "manufacturer_part_number", "comment": "Укажите артикул по шильдику"},
            {"field": "category", "comment": "Не та категория"},
        ]
        assert by_id[c["draft"].pk]["return_issues"] == [] and by_id[c["published"].pk]["return_issues"] == []
        assert by_id[c["published"].pk]["status"] == "published"
        assert by_id[c["published"].pk]["return_reason"] is None
        # чужая неопубликованная карточка — «сопоставлена»: только присланное партнёром, ход чужой карточки не раскрывается
        foreign = by_id[c["b_draft_with_a_offer"].pk]
        assert foreign["status"] == "matched" and foreign["is_own"] is False and foreign["can_submit"] is False
        assert body["counts"] == {"all": 6, "draft": 1, "review": 1, "returned": 1, "published": 2, "matched": 1}

    def test_status_filter_search_and_pagination(self, partner_world):
        w = partner_world
        only_draft = w["client_a"].get(f"{PREFIX}/products", {"status": "draft"}).json()
        assert [i["id"] for i in only_draft["items"]] == [w["cards"]["draft"].pk]
        assert only_draft["total"] == 1 and only_draft["counts"]["all"] == 6  # вкладки считают всё
        found = w["client_a"].get(f"{PREFIX}/products", {"q": "А-3"}).json()
        assert [i["id"] for i in found["items"]] == [w["cards"]["returned"].pk]
        page = w["client_a"].get(f"{PREFIX}/products", {"page_size": 2, "page": 2}).json()
        assert len(page["items"]) == 2 and page["page"] == 2 and page["total"] == 6
        assert w["client_a"].get(f"{PREFIX}/products", {"status": "published_by_me"}).status_code == 422

    def test_return_reason_of_foreign_card_is_not_shown(self, partner_world):
        """Причина возврата — только своей карточки: чужая возвращённая показывается как «на проверке» без причины."""
        w = partner_world
        foreign = make_card("Деталь Б-3", "RETURNED", source=w["b"], owner=w["own"])
        make_offer(foreign, w["a"], "5.00")
        ProductReview.objects.create(
            product=foreign, decision="returned", reason="Секрет причины Б", decided_at=timezone.now()
        )
        body = w["client_a"].get(f"{PREFIX}/products").content.decode()
        assert "Секрет причины Б" not in body
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == foreign.pk)
        assert item["status"] == "matched" and item["return_reason"] is None and item["return_issues"] == []

    def test_archived_cards_are_hidden(self, partner_world):
        w = partner_world
        from catalog.models import ProductStatus

        archived = ProductStatus.objects.get_or_create(code="ARCHIVED", defaults={"name": "Архив"})[0]
        w["cards"]["draft"].status = archived
        w["cards"]["draft"].save()
        assert w["cards"]["draft"].pk not in ids(w["client_a"].get(f"{PREFIX}/products"))

    def test_pending_change_flag(self, partner_world):
        from catalog.models import ProductFieldProposal

        w = partner_world
        ProductFieldProposal.objects.create(
            product=w["cards"]["published"],
            field="name",
            proposed_value="Новое",
            supplier=w["a"],
            contact=w["a_contact"],
        )
        by_id = {i["id"]: i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"]}
        assert by_id[w["cards"]["published"].pk]["has_pending_change"] is True
        assert by_id[w["cards"]["draft"].pk]["has_pending_change"] is False
        # правка Б по общей карточке А не видна
        ProductFieldProposal.objects.create(
            product=w["cards"]["shared"], field="name", proposed_value="Другое", supplier=w["b"], contact=w["b_contact"]
        )
        by_id = {i["id"]: i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"]}
        assert by_id[w["cards"]["shared"].pk]["has_pending_change"] is False

    def test_freshness_flags(self, partner_world):
        w = partner_world
        by_id = {i["id"]: i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"]}
        assert by_id[w["cards"]["published"].pk]["offer"]["freshness"] == "expiring"  # срок через 3 дня
        assert by_id[w["cards"]["draft"].pk]["offer"]["freshness"] == "fresh"
        SupplierOffer.objects.filter(pk=w["offers"]["draft"].pk).update(
            valid_until=timezone.localdate() - timedelta(days=1)
        )
        SupplierOffer.objects.filter(pk=w["offers"]["shared"].pk).update(updated_at=timezone.now() - timedelta(days=45))
        by_id = {i["id"]: i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"]}
        assert by_id[w["cards"]["draft"].pk]["offer"]["freshness"] == "expired"
        assert by_id[w["cards"]["shared"].pk]["offer"]["freshness"] == "stale"

    def test_confirm_days_setting_of_the_company(self, partner_world):
        from parties.models import CompanySettings

        w = partner_world
        SupplierOffer.objects.filter(pk=w["offers"]["shared"].pk).update(updated_at=timezone.now() - timedelta(days=10))
        item = lambda: next(  # noqa: E731
            i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["shared"].pk
        )
        assert item()["offer"]["freshness"] == "fresh"
        CompanySettings.objects.update_or_create(company=w["own"], defaults={"offer_confirm_days": 5})
        assert item()["offer"]["freshness"] == "stale"

    def test_expiring_days_setting_of_the_company(self, partner_world):
        """Задача «Н3c»: «истекает» — за сколько дней до конца срока, настройка компании, а не константа в коде."""
        from parties.models import CompanySettings

        w = partner_world
        item = lambda: next(  # noqa: E731
            i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["published"].pk
        )
        assert item()["offer"]["freshness"] == "expiring"  # срок через 3 дня, умолчание — 14
        CompanySettings.objects.update_or_create(company=w["own"], defaults={"offer_expiring_days": 2})
        assert item()["offer"]["freshness"] == "fresh"


class TestAttention:
    """Плашка «подтвердите актуальность»: счётчики по ВСЕМ ценам компании тем же правилом, что флаги строк."""

    def test_counts_cover_all_own_offers_and_none_of_the_others(self, partner_world):
        w = partner_world
        body = lambda: w["client_a"].get(f"{PREFIX}/products", {"page_size": 1}).json()["attention"]  # noqa: E731
        assert body() == {"expired": 0, "stale": 0, "expiring": 1}  # у «Болт А-4» срок через 3 дня
        SupplierOffer.objects.filter(pk=w["offers"]["draft"].pk).update(
            valid_until=timezone.localdate() - timedelta(days=1)
        )
        SupplierOffer.objects.filter(pk=w["offers"]["shared"].pk).update(updated_at=timezone.now() - timedelta(days=45))
        SupplierOffer.objects.filter(pk=w["offers"]["shared_b"].pk).update(
            updated_at=timezone.now() - timedelta(days=99)
        )
        assert body() == {"expired": 1, "stale": 1, "expiring": 1}  # просроченная цена Б не считается
        w["client_a"].post(f"{PREFIX}/offers/confirm", {"all": True}, format="json")
        assert body() == {"expired": 1, "stale": 0, "expiring": 1}


class TestDetail:
    def test_own_card_with_history(self, partner_world):
        w = partner_world
        body = w["client_a"].get(f"{PREFIX}/products/{w['cards']['returned'].pk}").json()
        assert body["status"] == "returned"
        assert [h["decision"] for h in body["history"]] == ["returned"]
        assert body["history"][0]["reason"] == "Нет артикула производителя"
        assert "decided_by" not in body["history"][0]
        assert [i["field"] for i in body["history"][0]["issues"]] == ["manufacturer_part_number", "category"]
        assert [i["field"] for i in body["return_issues"]] == ["manufacturer_part_number", "category"]
        assert {"description", "hs_code", "uom", "missing"} <= set(body)

    def test_foreign_and_unknown_cards_are_404(self, partner_world):
        w = partner_world
        for pk in (w["cards"]["b_only"].pk, 999999):
            response = w["client_a"].get(f"{PREFIX}/products/{pk}")
            assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}

    def test_history_of_foreign_card_with_own_offer_is_empty(self, partner_world):
        w = partner_world
        ProductReview.objects.create(product=w["cards"]["b_draft_with_a_offer"], decision="pending")
        body = w["client_a"].get(f"{PREFIX}/products/{w['cards']['b_draft_with_a_offer'].pk}").json()
        assert body["history"] == [] and body["is_own"] is False

    def test_missing_fields_are_only_what_the_partner_can_fill(self, partner_world):
        w = partner_world
        card = make_card("Без категории", "DRAFT", source=w["a"], owner=w["own"], price_visibility="cabinet")
        body = w["client_a"].get(f"{PREFIX}/products/{card.pk}").json()
        codes = {m["code"] for m in body["missing"]}
        assert "category" in codes and "list_price" not in codes and "conformity" not in codes
        assert 0 <= body["completeness"] < 100


class TestSubmit:
    def test_draft_and_returned_go_to_review_and_history_is_written(self, partner_world):
        w = partner_world
        c = w["cards"]
        response = w["client_a"].post(
            f"{PREFIX}/products/submit", {"ids": [c["draft"].pk, c["returned"].pk]}, format="json"
        )
        assert response.status_code == 200
        assert response.json() == {"submitted": [c["draft"].pk, c["returned"].pk], "errors": []}
        for key in ("draft", "returned"):
            card = Product.objects.get(pk=c[key].pk)
            assert card.status.code == "REVIEW"
            review = card.reviews.get(decision="pending")
            assert review.submitted_by_contact_id == w["a_contact"].pk
        body = w["client_a"].get(f"{PREFIX}/products/{c['returned'].pk}").json()
        assert body["status"] == "review" and body["return_reason"] is None and body["return_issues"] == []
        assert [h["decision"] for h in body["history"]] == ["pending", "returned"]  # новые сверху

    def test_foreign_unknown_published_and_in_review_cards_are_refused_by_id(self, partner_world):
        w = partner_world
        c = w["cards"]
        ask = [c["b_only"].pk, c["b_draft_with_a_offer"].pk, c["shared"].pk, c["published"].pk, c["review"].pk, 999999]
        response = w["client_a"].post(f"{PREFIX}/products/submit", {"ids": ask}, format="json")
        assert response.status_code == 200
        assert response.json()["submitted"] == []
        codes = {e["id"]: e["code"] for e in response.json()["errors"]}
        assert codes == {
            c["b_only"].pk: "NOT_FOUND",
            c["b_draft_with_a_offer"].pk: "NOT_FOUND",  # цена А есть, но карточку завёл Б
            c["shared"].pk: "NOT_FOUND",
            c["published"].pk: "PRODUCT_NOT_SUBMITTABLE",
            c["review"].pk: "PRODUCT_NOT_SUBMITTABLE",
            999999: "NOT_FOUND",
        }
        # статусы не тронуты, лишних проверок нет
        assert Product.objects.get(pk=c["b_draft_with_a_offer"].pk).status.code == "DRAFT"
        assert Product.objects.get(pk=c["published"].pk).status.code == "PUBLISHED"
        assert ProductReview.objects.filter(product=c["published"], decision="pending").count() == 0
        assert ProductReview.objects.filter(product=c["review"], decision="pending").count() == 1

    def test_second_submit_is_refused_not_duplicated(self, partner_world):
        w = partner_world
        url, body = f"{PREFIX}/products/submit", {"ids": [w["cards"]["draft"].pk]}
        assert w["client_a"].post(url, body, format="json").json()["submitted"] == [w["cards"]["draft"].pk]
        again = w["client_a"].post(url, body, format="json").json()
        assert again["submitted"] == [] and again["errors"] == [
            {"id": w["cards"]["draft"].pk, "code": "PRODUCT_NOT_SUBMITTABLE"}
        ]
        assert w["cards"]["draft"].reviews.filter(decision="pending").count() == 1

    def test_partner_b_cannot_submit_partner_a_card(self, partner_world):
        w = partner_world
        response = w["client_b"].post(f"{PREFIX}/products/submit", {"ids": [w["cards"]["draft"].pk]}, format="json")
        assert response.json()["errors"] == [{"id": w["cards"]["draft"].pk, "code": "NOT_FOUND"}]
        assert Product.objects.get(pk=w["cards"]["draft"].pk).status.code == "DRAFT"

    @pytest.mark.parametrize("body", [{}, {"ids": []}, {"ids": ["x"]}, {"ids": [0]}, {"ids": [1] * 501}, {"ids": 5}])
    def test_bad_body_is_422(self, partner_world, body):
        response = partner_world["client_a"].post(f"{PREFIX}/products/submit", body, format="json")
        assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}

    def test_responsible_employee_is_notified(self, partner_world):
        w = partner_world
        CompanyRelationship.objects.filter(company=w["a"]).update(responsible=w["staff"])
        w["client_a"].post(
            f"{PREFIX}/products/submit", {"ids": [w["cards"]["draft"].pk, w["cards"]["returned"].pk]}, format="json"
        )
        note = Notification.objects.get(user=w["staff"], event_code="portal.partner_products_submitted")
        assert w["a"].name in note.title and note.event_params == {"company": w["a"].name, "count": 2}

    def test_without_responsible_publishers_are_notified_then_platform_admins(self, partner_world, grant):
        w = partner_world
        publisher = w["staff"]
        grant(publisher, "catalog.publish")
        w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [w["cards"]["draft"].pk]}, format="json")
        assert Notification.objects.filter(user=publisher, event_code="portal.partner_products_submitted").count() == 1
        # право отозвано, ответственного нет — администраторы платформы
        publisher.memberships.update(is_active=False)
        w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [w["cards"]["returned"].pk]}, format="json")
        assert Notification.objects.filter(
            audience=Notification.AUDIENCE_PLATFORM_ADMIN, event_code="portal.partner_products_submitted"
        ).exists()

    def test_nothing_submitted_nothing_notified(self, partner_world):
        w = partner_world
        w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [w["cards"]["published"].pk]}, format="json")
        assert not Notification.objects.filter(event_code="portal.partner_products_submitted").exists()


class TestNoPublishing:
    """Из портала публикации нет: ни пути, ни побочного эффекта (ADR-0022 п. 4: публикуем мы)."""

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_card_cannot_be_changed_by_verbs(self, partner_world, method):
        w = partner_world
        url = f"{PREFIX}/products/{w['cards']['draft'].pk}"
        response = getattr(w["client_a"], method)(url, {"status": "published"}, format="json")
        assert response.status_code in (404, 405) and response.json() == {"detail": "NOT_FOUND"}
        assert Product.objects.get(pk=w["cards"]["draft"].pk).status.code == "DRAFT"

    @pytest.mark.parametrize("path", ["products/publish", "products/1/publish", "publish"])
    def test_no_publish_endpoint(self, partner_world, path):
        response = partner_world["client_a"].post(f"{PREFIX}/{path}", {"ids": [1]}, format="json")
        assert response.status_code == 404

    def test_no_partner_path_ever_writes_published(self, partner_world):
        w = partner_world
        before = set(Product.objects.filter(status__code="PUBLISHED").values_list("pk", flat=True))
        w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [c.pk for c in w["cards"].values()]}, format="json")
        w["client_a"].post(f"{PREFIX}/offers/confirm", {"all": True}, format="json")
        assert set(Product.objects.filter(status__code="PUBLISHED").values_list("pk", flat=True)) == before


class TestConfirm:
    def test_confirm_by_ids_sets_date_and_contact_only_on_own_offers(self, partner_world):
        w = partner_world
        c, o = w["cards"], w["offers"]
        response = w["client_a"].post(
            f"{PREFIX}/offers/confirm", {"ids": [c["draft"].pk, c["shared"].pk]}, format="json"
        )
        assert response.json() == {"confirmed": 2, "expired": 0, "errors": []}
        for key in ("draft", "shared"):
            offer = SupplierOffer.objects.get(pk=o[key].pk)
            assert offer.confirmed_at is not None and offer.confirmed_by_contact_id == w["a_contact"].pk
        for key in ("shared_b", "b_only", "published"):  # чужая цена и неназванная своя не тронуты
            assert SupplierOffer.objects.get(pk=o[key].pk).confirmed_at is None
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == c["draft"].pk)
        assert item["offer"]["confirmed_at"] is not None

    def test_confirm_all(self, partner_world):
        w = partner_world
        response = w["client_a"].post(f"{PREFIX}/offers/confirm", {"all": True}, format="json")
        assert response.json() == {"confirmed": 4, "expired": 0, "errors": []}
        assert SupplierOffer.objects.filter(supplier=w["a"], confirmed_at__isnull=True).count() == 0
        assert SupplierOffer.objects.filter(supplier=w["b"], confirmed_at__isnull=False).count() == 0

    def test_foreign_card_is_not_found_and_other_partner_price_untouched(self, partner_world):
        w = partner_world
        response = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [w["cards"]["b_only"].pk]}, format="json")
        assert response.json() == {
            "confirmed": 0,
            "expired": 0,
            "errors": [{"id": w["cards"]["b_only"].pk, "code": "NOT_FOUND"}],
        }
        assert SupplierOffer.objects.get(pk=w["offers"]["b_only"].pk).confirmed_at is None

    def test_card_without_own_offer_is_not_found(self, partner_world):
        """Своя карточка без цены компании: подтверждать нечего."""
        w = partner_world
        response = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [w["cards"]["review"].pk]}, format="json")
        assert response.json()["errors"] == [{"id": w["cards"]["review"].pk, "code": "NOT_FOUND"}]

    def test_expired_price_is_not_confirmed(self, partner_world):
        w = partner_world
        SupplierOffer.objects.filter(pk=w["offers"]["draft"].pk).update(
            valid_until=timezone.localdate() - timedelta(days=2)
        )
        by_ids = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [w["cards"]["draft"].pk]}, format="json").json()
        assert by_ids == {
            "confirmed": 0,
            "expired": 1,
            "errors": [{"id": w["cards"]["draft"].pk, "code": "OFFER_EXPIRED"}],
        }
        everything = w["client_a"].post(f"{PREFIX}/offers/confirm", {"all": True}, format="json").json()
        assert everything == {"confirmed": 3, "expired": 1, "errors": []}
        assert SupplierOffer.objects.get(pk=w["offers"]["draft"].pk).confirmed_at is None

    def test_confirmation_refreshes_a_stale_price(self, partner_world):
        w = partner_world
        SupplierOffer.objects.filter(pk=w["offers"]["shared"].pk).update(updated_at=timezone.now() - timedelta(days=45))

        def freshness():
            return next(
                i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["shared"].pk
            )["offer"]["freshness"]

        assert freshness() == "stale"
        w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [w["cards"]["shared"].pk]}, format="json")
        assert freshness() == "fresh"

    @pytest.mark.parametrize("body", [{}, {"all": False}, {"ids": [1], "all": True}, {"ids": []}, {"ids": ["x"]}])
    def test_bad_body_is_422(self, partner_world, body):
        response = partner_world["client_a"].post(f"{PREFIX}/offers/confirm", body, format="json")
        assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


class TestAccess:
    OPERATIONS = [
        ("get", "/products"),
        ("get", "/products/1"),
        ("post", "/products/submit"),
        ("post", "/offers/confirm"),
        ("get", "/price-template"),
        ("post", "/price-list"),
        ("get", "/price-list/abc"),
    ]

    @pytest.mark.parametrize(("method", "path"), OPERATIONS)
    def test_partner_without_the_module_gets_403(self, partner_world, method, path):
        w = partner_world
        CompanyRelationship.objects.filter(company=w["a"]).update(modules=["catalog_requests"])
        response = getattr(w["client_a"], method)(PREFIX + path, {}, format="json")
        assert response.status_code == 403 and response.json() == {"detail": "MODULE_REQUIRED"}

    @pytest.mark.parametrize(("method", "path"), OPERATIONS)
    def test_client_company_without_the_module_gets_403(self, partner_world, portal_client, method, path):
        response = getattr(portal_client, method)(PREFIX + path, {}, format="json")
        assert response.status_code == 403 and response.json() == {"detail": "MODULE_REQUIRED"}

    @pytest.mark.parametrize(("method", "path"), OPERATIONS)
    def test_anonymous_gets_401(self, partner_world, anon_portal_client, method, path):
        assert getattr(anon_portal_client, method)(PREFIX + path, {}, format="json").status_code == 401

    @pytest.mark.parametrize(
        ("path", "body"),
        [("/products/submit", {"ids": [1]}), ("/offers/confirm", {"all": True}), ("/price-list", {})],
    )
    def test_without_can_act_changes_are_forbidden_reads_are_not(self, partner_world, path, body):
        w = partner_world
        w["a_contact"].can_act = False
        w["a_contact"].save(update_fields=["can_act"])
        denied = w["client_a"].post(PREFIX + path, body, format="json")
        assert denied.status_code == 403 and denied.json() == {"detail": "FORBIDDEN"}
        assert w["client_a"].get(f"{PREFIX}/products").status_code == 200
        assert w["client_a"].get(f"{PREFIX}/price-template").status_code == 200
        assert Product.objects.get(pk=w["cards"]["draft"].pk).status.code == "DRAFT"
        assert SupplierOffer.objects.filter(supplier=w["a"], confirmed_at__isnull=False).count() == 0

    def test_suspended_relationship_closes_the_section(self, partner_world):
        from parties.models import RelationshipStatus

        w = partner_world
        CompanyRelationship.objects.filter(company=w["a"]).update(status=RelationshipStatus.SUSPENDED)
        assert w["client_a"].get(f"{PREFIX}/products").status_code == 401

    def test_modules_can_be_switched_back_on_without_relogin(self, partner_world):
        w = partner_world
        CompanyRelationship.objects.filter(company=w["a"]).update(modules=["catalog_requests"])
        assert w["client_a"].get(f"{PREFIX}/products").status_code == 403
        CompanyRelationship.objects.filter(company=w["a"]).update(modules=["my_products"])
        assert w["client_a"].get(f"{PREFIX}/products").status_code == 200

    def test_missing_idempotency_key_is_400(self, partner_world):
        client = client_for(partner_world["a_contact"])
        client.auto_idempotency_key = False
        response = client.post(f"{PREFIX}/products/submit", {"ids": [1]}, format="json")
        assert response.status_code == 400 and response.json() == {"detail": "IDEMPOTENCY_KEY_REQUIRED"}


class TestConstraints:
    def test_one_pending_review_per_card(self, partner_world):
        from django.db import IntegrityError, transaction

        card = partner_world["cards"]["review"]
        with pytest.raises(IntegrityError), transaction.atomic():
            ProductReview.objects.create(product=card)

    def test_return_needs_a_reason(self, partner_world):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            ProductReview.objects.create(product=partner_world["cards"]["draft"], decision="returned", reason="")

    def test_import_task_has_exactly_one_author(self, partner_world):
        from ai.models import ImportTask
        from django.db import IntegrityError, transaction

        w = partner_world
        for kwargs in ({}, {"owner": w["staff"], "contact": w["a_contact"]}):
            with pytest.raises(IntegrityError), transaction.atomic():
                ImportTask.objects.create(celery_task_id="t-" + str(len(kwargs)), task_type="CATALOG_IMPORT", **kwargs)
        ImportTask.objects.create(celery_task_id="by-contact", task_type="CATALOG_IMPORT", contact=w["a_contact"])
        ImportTask.objects.create(celery_task_id="by-user", task_type="CATALOG_IMPORT", owner=w["staff"])

    def test_proposal_has_at_most_one_author(self, partner_world):
        from django.db import IntegrityError, transaction

        from catalog.models import ProductFieldProposal

        w = partner_world
        with pytest.raises(IntegrityError), transaction.atomic():
            ProductFieldProposal.objects.create(
                product=w["cards"]["published"],
                field="name",
                proposed_value="x",
                supplier=w["a"],
                created_by=w["staff"],
                contact=w["a_contact"],
            )


class TestIssues:
    """`clean_issues` — форма замечаний возврата (её пишет очередь проверки, PART-3): поле из перечня, текст, предел."""

    def test_clean(self):
        from catalog.models.reviews import clean_issues

        assert clean_issues(None) == [] and clean_issues([]) == []
        assert clean_issues(
            [{"field": "name", "comment": " Нет бренда "}, {"field": "name", "comment": "Нет бренда"}]
        ) == [{"field": "name", "comment": "Нет бренда"}]

    @pytest.mark.parametrize(
        "raw",
        [
            "name",
            [{"field": "base_price", "comment": "x"}],
            [{"field": "name", "comment": ""}],
            [{"field": "name", "comment": "я" * 501}],
            [{"field": "name"}],
            ["name"],
            [{"field": "other", "comment": "x"}] * 31 + [{"field": "name", "comment": "y"}],
        ],
    )
    def test_invalid(self, raw):
        from catalog.models.reviews import clean_issues

        with pytest.raises(ValueError, match="REVIEW_ISSUES_INVALID"):
            clean_issues(raw)

    def test_contract_enum_matches_the_model(self):
        from portal.tests.contract_support import component

        from catalog.models.reviews import ISSUE_FIELDS

        assert tuple(component("PartnerIssueField")["enum"]) == ISSUE_FIELDS
