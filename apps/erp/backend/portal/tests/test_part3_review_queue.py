"""PART-3: очередь проверки карточек партнёров в Платформе — список «ждут проверки» со сроками, возврат с причинами по полям,
публикация, письмо партнёру о решении. Мир — `partner_world` (два партнёра, их карточки), сотрудники — `catalog.tests.desk_world`.

Желаемое поведение — ADR-0022 п. 4: карточкой владеем мы, партнёр отправил — сотрудник публикует или возвращает с причиной.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.core import mail
from django.utils import timezone
from parties.models import Contact
from portal.tests.conftest import LOCMEM_BACKEND

from catalog.models import Product, ProductFieldProposal, ProductReview, ProductStatus
from catalog.review_queue import due_at, is_overdue
from catalog.tests.desk_world import client_for as staff_client
from catalog.tests.desk_world import make_staff
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

ITEMS = "/api/v1/catalog/items/"
HS = "8708301009"


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.fixture
def desk(partner_world):
    """Сотрудники своей компании: снабженец (публикует), менеджер (только читает) — и клиенты API."""
    own = partner_world["own"]
    supply = make_staff(own, "supply", label="pq-supply")
    manager = make_staff(own, "manager", label="pq-manager")
    return {**partner_world, "supply": supply, "supply_api": staff_client(supply), "manager_api": staff_client(manager)}


def publishable(card):
    """Партнёр заполнил своё, остальное (ТН ВЭД) дописал сотрудник — карточка проходит порог полноты."""
    card.hs_code = HS
    card.save()
    return card


def ago(**delta):
    return timezone.now() - timedelta(**delta)


def make_review(card, contact, when):
    """Открытая проверка с заданным временем отправки (поле `auto_now_add` ставится при создании — правим обновлением)."""
    ProductReview.objects.filter(product=card, decision="pending").delete()
    review = ProductReview.objects.create(product=card, submitted_by_contact=contact)
    ProductReview.objects.filter(pk=review.pk).update(submitted_at=when)
    return review


def waiting(api, **params):
    response = api.get(ITEMS, {"review": "waiting", **params})
    assert response.status_code == 200, response.content
    return response.json()


class TestDueDate:
    """Срок ответа — 24 часа без субботы и воскресенья (своего календаря компании в ERP нет)."""

    def at(self, text):
        return timezone.make_aware(datetime.fromisoformat(text))

    def test_weekday_adds_a_day(self):
        assert due_at(self.at("2026-11-04 10:00")) == self.at("2026-11-05 10:00")  # среда

    def test_friday_evening_is_due_on_monday_evening(self):
        assert due_at(self.at("2026-11-06 18:00")) == self.at("2026-11-09 18:00")

    def test_saturday_and_sunday_start_on_monday(self):
        assert due_at(self.at("2026-11-07 15:00")) == self.at("2026-11-10 00:00")
        assert due_at(self.at("2026-11-08 03:00")) == self.at("2026-11-10 00:00")

    def test_overdue_only_after_the_due_moment(self):
        sent = self.at("2026-11-04 10:00")
        assert not is_overdue(sent, self.at("2026-11-05 09:59"))
        assert is_overdue(sent, self.at("2026-11-05 10:01"))

    def test_aware_utc_input_is_counted_in_company_time(self):
        sent = datetime(2026, 11, 6, 13, 0, tzinfo=dt_timezone.utc)  # пятница, вечер по времени компании
        assert due_at(sent) > sent + timedelta(hours=24)


class TestQueueList:
    def test_only_waiting_cards_oldest_first_with_partner_and_due(self, desk):
        cards, contact = desk["cards"], desk["a_contact"]
        make_review(cards["review"], contact, ago(hours=30))
        newer = cards["draft"]
        newer.status = ProductStatus.objects.get(code="REVIEW")
        newer.save()
        make_review(newer, contact, ago(hours=2))
        body = waiting(desk["supply_api"])
        ids = [row["id"] for row in body["results"]]
        assert ids == [cards["review"].pk, newer.pk]
        first = body["results"][0]
        assert first["review"]["kind"] == "card"
        assert first["review"]["partner"] == {"id": desk["a"].pk, "name": "Завод Север"}
        assert first["review"]["overdue"] is True or first["review"]["submitted_at"] < first["review"]["due_at"]
        assert 0 <= first["completeness"] <= 100
        assert body["results"][1]["review"]["overdue"] is False
        assert body["count"] == 2

    def test_old_submission_is_overdue_and_fresh_is_not(self, desk):
        cards, contact = desk["cards"], desk["a_contact"]
        make_review(cards["review"], contact, ago(days=5))  # дольше рабочих суток при любом дне недели
        row = waiting(desk["supply_api"])["results"][0]
        assert row["review"]["overdue"] is True
        ProductReview.objects.filter(product=cards["review"]).update(submitted_at=timezone.now())
        assert waiting(desk["supply_api"])["results"][0]["review"]["overdue"] is False

    def test_drafts_published_and_returned_are_not_in_the_queue(self, desk):
        ids = {row["id"] for row in waiting(desk["supply_api"])["results"]}
        cards = desk["cards"]
        assert cards["review"].pk in ids
        for key in ("draft", "returned", "published", "b_only", "shared"):
            assert cards[key].pk not in ids, key

    def test_partner_proposal_on_a_published_card_is_in_the_queue_staff_proposal_is_not(self, desk):
        cards = desk["cards"]
        ProductFieldProposal.objects.create(
            product=cards["published"],
            field="name",
            current_value=cards["published"].name,
            proposed_value="Болт А-4 усиленный",
            supplier=desk["a"],
            contact=desk["a_contact"],
        )
        ProductFieldProposal.objects.create(
            product=cards["shared"],
            field="description",
            proposed_value="Из прайса, загруженного сотрудником",
            supplier=desk["b"],
            created_by=desk["supply"],
        )
        body = waiting(desk["supply_api"])
        by_id = {row["id"]: row for row in body["results"]}
        assert cards["published"].pk in by_id and cards["shared"].pk not in by_id
        assert by_id[cards["published"].pk]["review"]["kind"] == "changes"
        assert by_id[cards["published"].pk]["review"]["partner"]["name"] == "Завод Север"

    def test_card_on_review_with_a_proposal_is_listed_once(self, desk):
        cards = desk["cards"]
        ProductFieldProposal.objects.create(
            product=cards["review"],
            field="name",
            proposed_value="Другое",
            supplier=desk["a"],
            contact=desk["a_contact"],
        )
        ProductFieldProposal.objects.create(
            product=cards["review"],
            field="description",
            proposed_value="Ещё",
            supplier=desk["a"],
            contact=desk["a_contact"],
        )
        rows = [row for row in waiting(desk["supply_api"])["results"] if row["id"] == cards["review"].pk]
        assert len(rows) == 1

    def test_list_without_the_filter_has_no_queue_fields(self, desk):
        row = desk["supply_api"].get(ITEMS).json()["results"][0]
        assert "review" not in row and "completeness" not in row

    def test_manager_can_read_the_queue(self, desk):
        assert desk["manager_api"].get(ITEMS, {"review": "waiting"}).status_code == 200

    def test_card_detail_tells_the_wait_and_what_the_catalog_will_show(self, desk):
        card = desk["cards"]["review"]
        detail = desk["supply_api"].get(f"{ITEMS}{card.pk}/").json()
        assert detail["review"]["kind"] == "card" and detail["review"]["partner"]["id"] == desk["a"].pk
        assert detail["catalog_price"] == {"visibility": "on_request", "source": "company", "price": None}
        assert desk["supply_api"].get(f"{ITEMS}{desk['cards']['draft'].pk}/").json()["review"] is None


class TestPartnerPriceInTheCard:
    def test_partner_agreement_shows_in_the_card(self, desk):
        from parties.models import CompanyRelationship

        from core.models import Currency

        card = desk["cards"]["review"]
        CompanyRelationship.objects.filter(company=desk["a"]).update(catalog_price_visibility="cabinet")
        card.list_price = 12500
        card.list_price_currency = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})[0]
        card.save()
        detail = desk["supply_api"].get(f"{ITEMS}{card.pk}/").json()
        assert detail["catalog_price"] == {
            "visibility": "cabinet",
            "source": "partner",
            "price": {"amount": "12500.00", "currency": "UZS"},
        }
        # цена-витрина обязательна, пока цену видно клиенту: без неё публикация закрыта и говорит, чего не хватает
        card.list_price = None
        card.save()
        missing = desk["supply_api"].get(f"{ITEMS}{card.pk}/").json()["publish"]["missing"]
        assert "list_price" in missing


class TestReturn:
    def url(self, card):
        return f"{ITEMS}{card.pk}/return/"

    def send(self, desk, card, body, api="supply_api", capture=None):
        return desk[api].post(self.url(card), body, format="json")

    def test_return_with_reason_and_field_issues(self, desk, django_capture_on_commit_callbacks):
        card = desk["cards"]["review"]
        make_review(card, desk["a_contact"], ago(hours=3))
        body = {
            "reason": "Не хватает данных",
            "issues": [
                {"field": "manufacturer_part_number", "comment": "Укажите артикул по шильдику"},
                {"field": "category", "comment": "Не та категория"},
            ],
        }
        with django_capture_on_commit_callbacks(execute=True):
            response = self.send(desk, card, body)
        assert response.status_code == 200, response.content
        assert response.json()["status"] == "RETURNED" and response.json()["review"] is None
        card.refresh_from_db()
        assert card.status.code == "RETURNED"
        review = ProductReview.objects.get(product=card, decision="returned")
        assert review.reason == "Не хватает данных"
        assert review.field_issues == body["issues"]
        assert review.decided_by_id == desk["supply"].pk and review.decided_at is not None
        assert not ProductReview.objects.filter(product=card, decision="pending").exists()
        # партнёр видит решение в «Мои товары»
        mine = desk["client_a"].get("/api/portal/v1/partner/products", {"status": "returned"})
        assert mine.status_code == 200, mine.content
        row = next(item for item in mine.json()["items"] if item["id"] == card.pk)
        assert row["return_reason"] == "Не хватает данных" and len(row["return_issues"]) == 2
        # решение — в журнале
        entry = ActivityLog.objects.get(event_code="admin.product_review.returned")
        assert entry.entity_id == card.pk and entry.user_id == desk["supply"].pk

    def test_issues_alone_are_enough(self, desk):
        card = desk["cards"]["review"]
        response = self.send(desk, card, {"issues": [{"field": "name", "comment": "Опечатка в названии"}]})
        assert response.status_code == 200, response.content
        review = ProductReview.objects.get(product=card, decision="returned")
        # хранится код, а не текст: слово подставляется при показе на языке получателя
        assert review.reason == "REVIEW_ISSUES_ONLY"
        assert review.field_issues == [{"field": "name", "comment": "Опечатка в названии"}]

    def test_reason_alone_is_enough(self, desk):
        response = self.send(desk, desk["cards"]["review"], {"reason": "Нет фото"})
        assert response.status_code == 200, response.content

    @pytest.mark.parametrize("body", [{}, {"reason": "   "}, {"reason": "", "issues": []}, {"issues": None}])
    def test_return_without_any_reason_is_refused(self, desk, body):
        card = desk["cards"]["review"]
        response = self.send(desk, card, body)
        assert response.status_code == 400 and response.json()["detail"] == "REVIEW_REASON_REQUIRED", response.content
        card.refresh_from_db()
        assert card.status.code == "REVIEW"
        assert ProductReview.objects.filter(product=card, decision="pending").count() == 1

    @pytest.mark.parametrize(
        "issues",
        [
            [{"field": "sku", "comment": "x"}],
            [{"field": "price", "comment": ""}],
            [{"field": "price", "comment": "я" * 501}],
            [{"comment": "без поля"}],
            "не список",
            [["не", "словарь"]],
            [{"field": ["price"], "comment": "x"}],
        ],
    )
    def test_field_outside_the_card_list_or_bad_comment_is_refused(self, desk, issues):
        card = desk["cards"]["review"]
        response = self.send(desk, card, {"reason": "Есть причина", "issues": issues})
        assert response.status_code == 400, response.content
        assert response.json() == {"detail": "REVIEW_ISSUES_INVALID"}
        card.refresh_from_db()
        assert card.status.code == "REVIEW"
        assert not ProductReview.objects.filter(product=card, decision="returned").exists()

    def test_too_long_reason_has_its_own_code(self, desk):
        response = self.send(desk, desk["cards"]["review"], {"reason": "я" * 2001})
        assert response.status_code == 400 and response.json() == {"detail": "REVIEW_REASON_TOO_LONG"}

    @pytest.mark.parametrize("key", ["draft", "returned", "published"])
    def test_card_not_on_review_is_409_and_nothing_is_written(self, desk, key):
        card = desk["cards"][key]
        before = ProductReview.objects.filter(product=card).count()
        response = self.send(desk, card, {"reason": "Поздно"})
        assert response.status_code == 409 and response.json()["detail"] == "PRODUCT_NOT_ON_REVIEW"
        assert ProductReview.objects.filter(product=card).count() == before
        card.refresh_from_db()
        assert card.status.code == key.upper()

    def test_second_decision_is_refused_and_does_not_duplicate(self, desk, django_capture_on_commit_callbacks):
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            assert self.send(desk, card, {"reason": "Первое"}).status_code == 200
        returned_rows = ProductReview.objects.filter(product=card, decision="returned").count()
        mails = len(mail.outbox)
        again = self.send(desk, card, {"reason": "Второе"})
        assert again.status_code == 409
        assert ProductReview.objects.filter(product=card, decision="returned").count() == returned_rows
        assert ProductReview.objects.get(product=card, decision="returned").reason == "Первое"
        assert len(mail.outbox) == mails
        # и «опубликовать» после возврата не оставляет висящей проверки
        assert not ProductReview.objects.filter(product=card, decision="pending").exists()

    def test_return_does_not_touch_the_review_of_another_card(self, desk):
        other = desk["cards"]["draft"]
        other.status = ProductStatus.objects.get(code="REVIEW")
        other.save()
        make_review(other, desk["a_contact"], ago(hours=1))
        assert self.send(desk, desk["cards"]["review"], {"reason": "Только эта"}).status_code == 200
        assert ProductReview.objects.get(product=other).decision == "pending"
        other.refresh_from_db()
        assert other.status.code == "REVIEW"

    def test_without_the_publish_right_it_is_403(self, desk):
        card = desk["cards"]["review"]
        response = self.send(desk, card, {"reason": "Нельзя"}, api="manager_api")
        assert response.status_code == 403
        card.refresh_from_db()
        assert card.status.code == "REVIEW"

    def test_unknown_card_is_404(self, desk):
        response = desk["supply_api"].post(f"{ITEMS}999999/return/", {"reason": "x"}, format="json")
        assert response.status_code == 404

    def test_anonymous_is_refused(self, desk):
        from rest_framework.test import APIClient

        response = APIClient().post(self.url(desk["cards"]["review"]), {"reason": "x"}, format="json")
        assert response.status_code in (401, 403)

    def test_card_on_review_without_an_open_review_still_keeps_the_decision_in_history(self, desk):
        card = desk["cards"]["review"]
        ProductReview.objects.filter(product=card).delete()
        assert self.send(desk, card, {"reason": "Статус менял сотрудник"}).status_code == 200
        assert ProductReview.objects.filter(product=card, decision="returned").count() == 1

    def test_partner_card_can_be_resubmitted_after_the_return(self, desk, django_capture_on_commit_callbacks):
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            assert self.send(desk, card, {"reason": "Исправьте"}).status_code == 200
        response = desk["client_a"].post("/api/portal/v1/partner/products/submit", {"ids": [card.pk]}, format="json")
        assert response.status_code == 200, response.content
        assert waiting(desk["supply_api"])["count"] >= 1
        assert ProductReview.objects.filter(product=card, decision="returned").count() == 1
        assert ProductReview.objects.filter(product=card, decision="pending").count() == 1


class TestPublish:
    def publish(self, desk, card, api="supply_api"):
        return desk[api].post(f"{ITEMS}{card.pk}/publish/")

    def test_publish_closes_the_review_and_writes_the_journal(self, desk, django_capture_on_commit_callbacks):
        card = publishable(desk["cards"]["review"])
        with django_capture_on_commit_callbacks(execute=True):
            response = self.publish(desk, card)
        assert response.status_code == 200, response.content
        assert response.json()["status"] == "PUBLISHED" and response.json()["review"] is None
        review = ProductReview.objects.get(product=card)
        assert review.decision == "published" and review.decided_by_id == desk["supply"].pk and review.decided_at
        assert ActivityLog.objects.filter(event_code="admin.product_review.published", entity_id=card.pk).count() == 1
        assert card.pk not in [row["id"] for row in waiting(desk["supply_api"])["results"]]

    def test_incomplete_card_is_not_published_and_says_what_is_missing(self, desk):
        card = desk["cards"]["review"]  # ТН ВЭД не заполнен
        response = self.publish(desk, card)
        assert response.status_code == 409 and response.json()["detail"] == "PRODUCT_INCOMPLETE"
        card.refresh_from_db()
        assert card.status.code == "REVIEW"
        assert ProductReview.objects.get(product=card).decision == "pending"
        detail = desk["supply_api"].get(f"{ITEMS}{card.pk}/").json()
        assert detail["publish"]["publishable"] is False and "hs_code" in detail["publish"]["missing"]

    def test_category_document_is_required_when_the_category_asks_for_it(self, desk):
        card = publishable(desk["cards"]["review"])
        card.category.requires_conformity_doc = True
        card.category.save()
        response = self.publish(desk, card)
        assert response.status_code == 409
        assert "conformity_doc" in desk["supply_api"].get(f"{ITEMS}{card.pk}/").json()["publish"]["missing"]

    def test_without_the_publish_right_it_is_403(self, desk):
        card = publishable(desk["cards"]["review"])
        assert self.publish(desk, card, api="manager_api").status_code == 403
        card.refresh_from_db()
        assert card.status.code == "REVIEW"

    def test_publishing_twice_does_not_duplicate_anything(self, desk, django_capture_on_commit_callbacks):
        card = publishable(desk["cards"]["review"])
        with django_capture_on_commit_callbacks(execute=True):
            assert self.publish(desk, card).status_code == 200
        sent = len(mail.outbox)
        assert sent == 1
        with django_capture_on_commit_callbacks(execute=True):
            assert self.publish(desk, card).status_code == 200
        assert len(mail.outbox) == sent
        assert ProductReview.objects.filter(product=card).count() == 1
        assert ActivityLog.objects.filter(event_code="admin.product_review.published", entity_id=card.pk).count() == 1

    def test_accepting_a_partner_proposal_takes_the_card_out_of_the_queue(self, desk):
        card = desk["cards"]["published"]
        proposal = ProductFieldProposal.objects.create(
            product=card,
            field="description",
            current_value="",
            proposed_value="Оцинкованный болт",
            supplier=desk["a"],
            contact=desk["a_contact"],
        )
        assert card.pk in [row["id"] for row in waiting(desk["supply_api"])["results"]]
        response = desk["supply_api"].post(f"/api/v1/catalog/field-proposals/{proposal.pk}/accept/")
        assert response.status_code == 200, response.content
        card.refresh_from_db()
        assert card.description == "Оцинкованный болт"
        assert card.pk not in [row["id"] for row in waiting(desk["supply_api"])["results"]]


class TestPartnerLetter:
    def to_review(self, desk, key="review"):
        return publishable(desk["cards"][key])

    def test_published_letter_goes_to_acting_contacts_with_the_link(self, desk, django_capture_on_commit_callbacks):
        card = self.to_review(desk)
        reader = Contact.objects.create(
            company=desk["a"], name="Наблюдатель", email="reader@plant-north.example", can_act=False
        )
        with django_capture_on_commit_callbacks(execute=True):
            assert desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/").status_code == 200
        assert [m.to for m in mail.outbox] == [["north@plant-north.example"]]
        letter = mail.outbox[0]
        assert "опубликована" in letter.subject
        assert f"http://cabinet.localhost/my-products?card={card.pk}" in letter.body
        assert reader.email not in letter.to
        assert letter.reply_to == [desk["supply"].email]

    def test_returned_letter_has_the_reason_and_the_issue_labels(self, desk, django_capture_on_commit_callbacks):
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            desk["supply_api"].post(
                f"{ITEMS}{card.pk}/return/",
                {
                    "reason": "Нет артикула",
                    "issues": [{"field": "manufacturer_part_number", "comment": "Укажите по шильдику"}],
                },
                format="json",
            )
        assert len(mail.outbox) == 1
        letter = mail.outbox[0]
        assert "возвращена" in letter.subject
        assert "Нет артикула" in letter.body and "Артикул изготовителя: Укажите по шильдику" in letter.body
        assert f"/my-products?card={card.pk}" in letter.body

    def test_letter_is_in_the_language_of_the_contact(self, desk, django_capture_on_commit_callbacks):
        Contact.objects.filter(pk=desk["a_contact"].pk).update(language="uz")
        card = self.to_review(desk)
        with django_capture_on_commit_callbacks(execute=True):
            desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/")
        assert "e'lon qilindi" in mail.outbox[0].subject

    def test_no_letter_when_the_partner_has_no_cabinet_module(self, desk, django_capture_on_commit_callbacks):
        from parties.models import CompanyRelationship

        CompanyRelationship.objects.filter(company=desk["a"]).update(modules=["catalog_requests"])
        card = self.to_review(desk)
        with django_capture_on_commit_callbacks(execute=True):
            assert desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/").status_code == 200
        assert mail.outbox == []

    def test_no_letter_when_the_relationship_is_suspended(self, desk, django_capture_on_commit_callbacks):
        from parties.models import CompanyRelationship

        CompanyRelationship.objects.filter(company=desk["a"]).update(status="suspended")
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                desk["supply_api"].post(f"{ITEMS}{card.pk}/return/", {"reason": "x"}, format="json").status_code == 200
            )
        assert mail.outbox == []

    def test_no_letter_when_staff_publishes_a_draft_the_partner_did_not_send(
        self, desk, django_capture_on_commit_callbacks
    ):
        card = self.to_review(desk, "draft")
        with django_capture_on_commit_callbacks(execute=True):
            assert desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/").status_code == 200
        assert mail.outbox == []

    def test_failed_mail_does_not_undo_the_decision(self, desk, django_capture_on_commit_callbacks, monkeypatch):
        from portal.services import partner_decision_mail

        def boom(*args, **kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(partner_decision_mail, "send_templated_email", boom)
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                desk["supply_api"].post(f"{ITEMS}{card.pk}/return/", {"reason": "x"}, format="json").status_code == 200
            )
        card.refresh_from_db()
        assert card.status.code == "RETURNED"

    def test_letter_never_leaves_the_partner_company(self, desk, django_capture_on_commit_callbacks):
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            desk["supply_api"].post(f"{ITEMS}{card.pk}/return/", {"reason": "x"}, format="json")
        recipients = {address for m in mail.outbox for address in m.to}
        assert recipients == {desk["a_contact"].email}
        assert desk["b_contact"].email not in recipients


class TestStalePublish:
    """Сотрудник A открыл карточку «на проверке» и жмёт «Опубликовать», а B успел её вернуть: решение B не перезаписывается."""

    def test_publish_after_a_parallel_return_is_409_and_changes_nothing(self, desk, django_capture_on_commit_callbacks):
        from catalog.desk import items

        card = publishable(desk["cards"]["review"])
        stale = Product.objects.select_related("status", "source_supplier").get(pk=card.pk)  # чтение A до решения B
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                desk["supply_api"].post(f"{ITEMS}{card.pk}/return/", {"reason": "B"}, format="json").status_code == 200
            )
        letters = len(mail.outbox)
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(items.ItemError) as refused:
                items.set_published(stale, True, desk["supply"])
        assert refused.value.code == "PRODUCT_NOT_ON_REVIEW"
        card.refresh_from_db()
        assert card.status.code == "RETURNED"
        assert list(ProductReview.objects.filter(product=card).values_list("decision", flat=True)) == ["returned"]
        assert len(mail.outbox) == letters
        assert not ActivityLog.objects.filter(event_code="admin.product_review.published", entity_id=card.pk).exists()

    def test_publish_after_a_parallel_publish_does_not_write_a_second_decision(
        self, desk, django_capture_on_commit_callbacks
    ):
        card = publishable(desk["cards"]["review"])
        with django_capture_on_commit_callbacks(execute=True):
            assert desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/").status_code == 200
        stale = Product.objects.select_related("status", "source_supplier").get(pk=card.pk)
        stale.status = ProductStatus.objects.get(code="REVIEW")  # так карточку видел второй сотрудник
        from catalog.desk import items

        with pytest.raises(items.ItemError) as refused:
            items.set_published(stale, True, desk["supply"])
        assert refused.value.code == "PRODUCT_NOT_ON_REVIEW"
        assert ActivityLog.objects.filter(event_code="admin.product_review.published", entity_id=card.pk).count() == 1

    def test_no_journal_and_no_letter_when_there_was_no_open_review(self, desk, django_capture_on_commit_callbacks):
        """Статус «на проверке» поставили мимо кабинета, открытой проверки нет: публикация идёт, решения проверки не пишутся."""
        card = publishable(desk["cards"]["review"])
        ProductReview.objects.filter(product=card).delete()
        with django_capture_on_commit_callbacks(execute=True):
            assert desk["supply_api"].post(f"{ITEMS}{card.pk}/publish/").status_code == 200
        assert mail.outbox == []
        assert not ActivityLog.objects.filter(event_code="admin.product_review.published", entity_id=card.pk).exists()


class TestLetterIsEscapedAndTranslated:
    EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)><a href="http://evil.example">клик</a>'

    def test_html_in_reason_issue_and_card_name_is_escaped_in_the_html_letter(
        self, desk, django_capture_on_commit_callbacks
    ):
        card = desk["cards"]["review"]
        Product.objects.filter(pk=card.pk).update(name='Болт <script>alert(3)</script> "A&B"')
        with django_capture_on_commit_callbacks(execute=True):
            response = desk["supply_api"].post(
                f"{ITEMS}{card.pk}/return/",
                {"reason": self.EVIL, "issues": [{"field": "name", "comment": self.EVIL}]},
                format="json",
            )
        assert response.status_code == 200, response.content
        html = mail.outbox[0].alternatives[0][0]
        assert "<script>" not in html and "<img" not in html and '<a href="http://evil.example"' not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;script&gt;alert(3)&lt;/script&gt;" in html
        assert html.count("&lt;img src=x onerror=alert(2)&gt;") >= 2  # причина и замечание

    def test_issues_only_reason_is_shown_in_the_language_of_the_contact(self, desk, django_capture_on_commit_callbacks):
        Contact.objects.filter(pk=desk["a_contact"].pk).update(language="uz")
        card = desk["cards"]["review"]
        with django_capture_on_commit_callbacks(execute=True):
            desk["supply_api"].post(
                f"{ITEMS}{card.pk}/return/", {"issues": [{"field": "name", "comment": "Опечатка"}]}, format="json"
            )
        assert ProductReview.objects.get(product=card, decision="returned").reason == "REVIEW_ISSUES_ONLY"
        assert "REVIEW_ISSUES_ONLY" not in mail.outbox[0].body
        assert "tuzating" in mail.outbox[0].body
        # кабинет: тот же код словами на языке контакта
        mine = desk["client_a"].get("/api/portal/v1/partner/products", {"status": "returned"}).json()
        row = next(item for item in mine["items"] if item["id"] == card.pk)
        assert row["return_reason"] != "REVIEW_ISSUES_ONLY" and "tuzating" in row["return_reason"]
