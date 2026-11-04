"""PART-2, возврат по ревью #398: чужая неопубликованная карточка не раскрывается, проверка не «висит», срок цены, границы страниц.

Мир — `partner_world`: у партнёра А есть цена на неопубликованную карточку Б («Деталь Б-2 в работе», артикул B-2, секретное
описание и ТН ВЭД), а своя строка прайса А называет её по-своему.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from portal.tests.partner_world import PREFIX, report, row, upload, xlsx

from catalog.models import Product, ProductFieldProposal, ProductReview, ProductStatus, SupplierOffer
from catalog.publishing import archive_product, publish_product, unpublish_product

pytestmark = pytest.mark.django_db

SECRET = ("Деталь Б-2 в работе", "Секретное описание", "8708301009")


def _foreign_row(**extra):
    """Строка прайса А, совпавшая с карточкой Б по бренду и артикулу, но со своим названием."""
    return row(**{"Наименование": "Деталь, как зову её я", "Артикул производителя": "B-2", "Бренд": "Аквилон", **extra})


class TestForeignDraftIsNotRevealed:
    def test_list_and_detail_show_only_what_the_partner_sent(self, partner_world, broker):
        w = partner_world
        upload(w["client_a"], xlsx([_foreign_row()]))  # цена А привязалась к карточке Б
        card = w["cards"]["b_draft_with_a_offer"]
        mine = SupplierOffer.objects.get(product=card, supplier=w["a"])
        assert mine.supplier_item_name == "Деталь, как зову её я" and mine.supplier_mpn == "B-2"
        listing = w["client_a"].get(f"{PREFIX}/products")
        item = next(i for i in listing.json()["items"] if i["id"] == card.pk)
        assert item["name"] == "Деталь, как зову её я" and item["brand"] == "Аквилон"
        assert item["manufacturer_part_number"] == "B-2"
        assert item["status"] == "matched" and item["category"] is None and item["completeness"] == 0
        assert item["is_own"] is False and item["can_submit"] is False and item["has_pending_change"] is False
        assert item["return_reason"] is None and item["return_issues"] == []
        assert item["offer"]["price"] == {"amount": "120.00", "currency": "USD"}
        detail = w["client_a"].get(f"{PREFIX}/products/{card.pk}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["description"] == "" and body["hs_code"] == "" and body["uom"] is None
        assert body["missing"] == [] and body["history"] == []
        for text in (listing.content.decode(), detail.content.decode()):
            for secret in SECRET:
                assert secret not in text, secret

    def test_card_date_does_not_leak_through_updated_at_or_order(self, partner_world):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        before = [i["id"] for i in w["client_a"].get(f"{PREFIX}/products").json()["items"]]
        Product.objects.filter(pk=card.pk).update(updated_at=timezone.now() + timedelta(days=30))
        items = w["client_a"].get(f"{PREFIX}/products").json()["items"]
        assert [i["id"] for i in items] == before  # правки чужой карточки порядок списка партнёра не меняют
        item = next(i for i in items if i["id"] == card.pk)
        offer = SupplierOffer.objects.get(product=card, supplier=w["a"])
        assert timezone.datetime.fromisoformat(item["updated_at"]) == offer.updated_at  # дата своей цены, не карточки

    def test_search_does_not_find_the_foreign_card_by_its_own_fields(self, partner_world):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        for text in ("в работе", "Секретное", "RT-"):
            found = w["client_a"].get(f"{PREFIX}/products", {"q": text}).json()
            assert card.pk not in {i["id"] for i in found["items"]}, text
        mine = w["client_a"].get(f"{PREFIX}/products", {"q": "Моя деталь"}).json()
        assert [i["id"] for i in mine["items"]] == [card.pk]  # а по своему названию — находит

    def test_report_does_not_tell_about_the_foreign_card(self, partner_world, broker):
        """Проверка (dry_run) и запись: ни предложений по полям, ни полноты чужой неопубликованной карточки."""
        w = partner_world
        records = [_foreign_row(**{"Категория": ""})]
        for dry in ("true", "false"):
            task_id = upload(w["client_a"], xlsx(records), dry_run=dry).json()["task_id"]
            result = report(w["client_a"], task_id)["report"]
            assert result["proposal_count"] == 0 and result["proposals"] == []
            assert result["unpublishable"] == 0 and result["missing_breakdown"] == []
            assert result["updated"] == 1 and result["created"] == 0  # «сопоставлено» — счётчик допустим
        assert not ProductFieldProposal.objects.filter(product=w["cards"]["b_draft_with_a_offer"]).exists()
        assert w["cards"]["b_draft_with_a_offer"].name == "Деталь Б-2 в работе"

    def test_matched_card_is_not_submittable_but_its_price_can_be_confirmed(self, partner_world):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        refused = w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [card.pk]}, format="json").json()
        assert refused["errors"] == [{"id": card.pk, "code": "NOT_FOUND"}]
        confirmed = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [card.pk]}, format="json").json()
        assert confirmed["confirmed"] == 1

    def test_published_foreign_card_stays_public(self, partner_world):
        """Опубликованный слой публичен: чужая опубликованная карточка со своей ценой показана как раньше."""
        w = partner_world
        item = next(
            i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == w["cards"]["shared"].pk
        )
        assert item["status"] == "published" and item["name"] == "Общая деталь" and item["category"]

    def test_card_published_later_becomes_visible_with_its_fields(self, partner_world):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        Product.objects.filter(pk=card.pk).update(status=ProductStatus.objects.get(code="PUBLISHED"))
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == card.pk)
        assert item["status"] == "published" and item["name"] == "Деталь Б-2 в работе"


class TestRowWithoutKeysDoesNotGuessForeignName:
    """Строка без артикула, бренда+MPN и ГОСТ: скрытую чужую карточку по её названию не находим (подсказка «такая есть»)."""

    def _keyless(self, name):
        return {"Наименование": name, "Цена": "77.00", "Валюта": "USD"}

    def _counts(self, w, name, dry):
        task_id = upload(w["client_a"], xlsx([self._keyless(name)]), dry_run=dry).json()["task_id"]
        result = report(w["client_a"], task_id)["report"]
        return {k: result[k] for k in ("created", "updated", "offers_created", "offers_updated", "proposal_count")}

    def test_right_and_wrong_foreign_name_give_the_same_counts_and_keep_the_price(self, partner_world, broker):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        right, wrong = "Деталь Б-2 в работе", "Совсем другое название"
        before = SupplierOffer.objects.get(product=card, supplier=w["a"])
        for dry in ("true", "false"):
            assert (
                self._counts(w, right, dry)
                == self._counts(w, wrong, dry)
                == {
                    "created": 1,
                    "updated": 0,
                    "offers_created": 1,
                    "offers_updated": 0,
                    "proposal_count": 0,
                }
            )
        # ни dry_run, ни запись не нашли чужую карточку по названию: её цена А не тронута, лишняя карточка заведена отдельно
        after = SupplierOffer.objects.get(product=card, supplier=w["a"])
        assert (after.base_price, after.supplier_item_name) == (before.base_price, before.supplier_item_name)
        assert Product.objects.filter(name__in=[right, wrong], source_supplier=w["a"]).count() == 2

    def test_own_row_name_still_matches_the_hidden_card(self, partner_world, broker):
        """По тому, что партнёр прислал сам (`supplier_item_name`), повторная загрузка находит своё предложение."""
        w = partner_world
        task_id = upload(w["client_a"], xlsx([self._keyless("Моя деталь Б-2")]), dry_run="false").json()["task_id"]
        result = report(w["client_a"], task_id)["report"]
        assert (result["created"], result["updated"], result["offers_updated"]) == (0, 1, 1)
        offer = SupplierOffer.objects.get(product=w["cards"]["b_draft_with_a_offer"], supplier=w["a"])
        assert offer.base_price == 77

    def test_own_and_published_cards_are_still_found_by_card_name(self, partner_world, broker):
        w = partner_world
        task_id = upload(w["client_a"], xlsx([self._keyless("Болт А-1")]), dry_run="true").json()["task_id"]
        assert report(w["client_a"], task_id)["report"]["updated"] == 1
        task_id = upload(w["client_a"], xlsx([self._keyless("Общая деталь")]), dry_run="true").json()["task_id"]
        assert report(w["client_a"], task_id)["report"]["updated"] == 1

    def test_old_offer_without_a_row_name_shows_brand_and_article_not_the_card_name(self, partner_world):
        w = partner_world
        card = w["cards"]["b_draft_with_a_offer"]
        SupplierOffer.objects.filter(product=card, supplier=w["a"]).update(
            supplier_item_name="", supplier_brand="Аквилон", supplier_mpn="B-2"
        )
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == card.pk)
        assert item["name"] == "Аквилон B-2" and "Деталь Б-2" not in item["name"]
        SupplierOffer.objects.filter(product=card, supplier=w["a"]).update(
            supplier_brand="", supplier_mpn="", supplier_sku=""
        )
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == card.pk)
        assert item["name"] == "—"


class TestReviewDoesNotHang:
    def _complete(self, card):
        from master_data.models import UnitOfMeasure

        card.hs_code = "8708301009"
        card.uom = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})[0]
        card.save()

    def test_submit_publish_unpublish_submit_again(self, partner_world, django_user_model):
        w = partner_world
        card = w["cards"]["draft"]
        self._complete(card)
        admin = django_user_model.objects.create_superuser(email="root@staff.example", username="root", password="x")
        url, body = f"{PREFIX}/products/submit", {"ids": [card.pk]}
        assert w["client_a"].post(url, body, format="json").json()["submitted"] == [card.pk]
        _, error = publish_product(Product.objects.get(pk=card.pk), admin)
        assert error is None
        assert not ProductReview.objects.filter(product=card, decision="pending").exists()
        published = ProductReview.objects.get(product=card)
        assert published.decision == "published" and published.decided_by_id == admin.pk and published.decided_at
        _, error = unpublish_product(Product.objects.get(pk=card.pk), admin)
        assert error is None
        again = w["client_a"].post(url, body, format="json")
        assert again.status_code == 200 and again.json()["submitted"] == [card.pk]  # раньше — 500
        assert sorted(ProductReview.objects.filter(product=card).values_list("decision", flat=True)) == [
            "pending",
            "published",
        ]
        assert Product.objects.get(pk=card.pk).status.code == "REVIEW"

    def test_archive_closes_the_open_review(self, partner_world, django_user_model):
        w = partner_world
        admin = django_user_model.objects.create_superuser(email="root2@staff.example", username="root2", password="x")
        card = Product.objects.get(pk=w["cards"]["review"].pk)
        assert archive_product(card, admin)[1] is None
        assert ProductReview.objects.get(product=card, decision="cancelled")
        assert not ProductReview.objects.filter(product=card, decision="pending").exists()

    def test_dangling_open_review_is_closed_not_a_500(self, partner_world):
        """Статус карточки вернули мимо проверки (прямая правка): открытая проверка остаётся — отправка её закрывает."""
        w = partner_world
        card = w["cards"]["review"]
        Product.objects.filter(pk=card.pk).update(status=ProductStatus.objects.get(code="DRAFT"))
        response = w["client_a"].post(f"{PREFIX}/products/submit", {"ids": [card.pk]}, format="json")
        assert response.status_code == 200 and response.json()["submitted"] == [card.pk]
        decisions = sorted(ProductReview.objects.filter(product=card).values_list("decision", flat=True))
        assert decisions == ["cancelled", "pending"]
        cancelled = w["client_a"].get(f"{PREFIX}/products/{card.pk}").json()["history"]
        assert {h["decision"] for h in cancelled} == {"pending", "cancelled"}


class TestExpiredPriceIsNotConfirmedByUpload:
    def _offer(self, partner_world):
        return SupplierOffer.objects.get(supplier=partner_world["a"], product__manufacturer_part_number="AQ-50")

    def test_expired_in_file_stays_unconfirmed(self, partner_world, broker):
        w = partner_world
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        upload(w["client_a"], xlsx([row()]), valid_until=past)
        offer = self._offer(w)
        assert offer.valid_until.isoformat() == past
        assert offer.confirmed_at is None and offer.confirmed_by_contact_id is None

    def test_future_or_open_ended_is_confirmed(self, partner_world, broker):
        w = partner_world
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        upload(w["client_a"], xlsx([row()]), valid_until=future)
        assert self._offer(w).confirmed_at is not None
        SupplierOffer.objects.all().update(confirmed_at=None, confirmed_by_contact=None)
        upload(
            w["client_a"], xlsx([row(**{"Цена": "130"})]), valid_until=timezone.localdate().isoformat()
        )  # сегодня — ещё действует
        assert self._offer(w).confirmed_at is not None

    def test_old_expired_term_is_kept_when_the_file_has_none(self, partner_world, broker):
        w = partner_world
        upload(w["client_a"], xlsx([row()]))
        offer = self._offer(w)
        SupplierOffer.objects.filter(pk=offer.pk).update(
            valid_until=timezone.localdate() - timedelta(days=3), confirmed_at=None, confirmed_by_contact=None
        )
        upload(w["client_a"], xlsx([row(**{"Цена": "140"})]))  # срок в файле не задан — действует прежний, он истёк
        offer.refresh_from_db()
        assert offer.base_price == 140 and offer.confirmed_at is None


class TestPageBounds:
    @pytest.mark.parametrize(
        "params",
        [
            {"page": 0},
            {"page": -1},
            {"page": 10001},
            {"page": "abc"},
            {"page_size": 0},
            {"page_size": 101},
            {"page_size": "x"},
        ],
    )
    def test_out_of_bounds_is_422(self, partner_world, params):
        response = partner_world["client_a"].get(f"{PREFIX}/products", params)
        assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}

    def test_edges_are_fine(self, partner_world):
        client = partner_world["client_a"]
        assert client.get(f"{PREFIX}/products", {"page": 10000}).json()["items"] == []
        assert client.get(f"{PREFIX}/products", {"page": 1, "page_size": 100}).status_code == 200
