"""PART-2: загрузка прайса партнёром из кабинета — шаблон, предпросмотр, запись, отчёт, чужие карточки и чужие задачи.

Движок тот же, что у сотрудника (`sourcing/catalog_import.py`); брокера в тестах нет, поэтому задача Celery выполняется
сразу, а её результат отдаётся вместо `AsyncResult` (как в `catalog/tests/test_cat1_supplier_prices.py`).
"""

import uuid
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from ai.models import ImportTask
from portal.tests.partner_world import PREFIX, URL, report, row, upload, xlsx

from catalog.models import Category, Product, ProductFieldProposal, SupplierOffer
from sourcing.views_templates import CATALOG_TEMPLATE_HEADERS

pytestmark = pytest.mark.django_db


class TestTemplate:
    def test_same_template_as_the_employee_gets(self, partner_world):
        from openpyxl import load_workbook

        response = partner_world["client_a"].get(f"{PREFIX}/price-template")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        sheet = load_workbook(BytesIO(response.content))["Товары"]
        assert [cell.value for cell in sheet[1]] == CATALOG_TEMPLATE_HEADERS


class TestUpload:
    def test_dry_run_reports_without_writing(self, partner_world, broker):
        w = partner_world
        before = (Product.objects.count(), SupplierOffer.objects.count())
        records = [row(), row(**{"Наименование": "Кран", "Артикул производителя": "K-1", "Цена": "abc"})]
        response = upload(w["client_a"], xlsx(records), dry_run="true")
        assert response.status_code == 202
        body = report(w["client_a"], response.json()["task_id"])
        assert body["status"] == "completed" and body["error"] is None
        result = body["report"]
        assert result["dry_run"] is True and result["created"] == 1
        assert result["error_count"] == 1
        assert result["errors"] == [{"row": 3, "field": "price", "code": "PRICE_NOT_A_NUMBER", "value": None}]
        assert (Product.objects.count(), SupplierOffer.objects.count()) == before

    def test_real_upload_creates_draft_owned_by_us_sourced_by_partner_with_confirmed_price(self, partner_world, broker):
        w = partner_world
        response = upload(w["client_a"], xlsx([row()]), valid_until="2027-12-31", valid_from="2026-11-01")
        body = report(w["client_a"], response.json()["task_id"])["report"]
        assert (body["created"], body["offers_created"], body["error_count"]) == (1, 1, 0)
        card = Product.objects.get(manufacturer_part_number="AQ-50")
        assert card.status.code == "DRAFT"
        assert card.owner_company_id == w["own"].pk and card.source_supplier_id == w["a"].pk
        offer = SupplierOffer.objects.get(product=card)
        assert offer.supplier_id == w["a"].pk and offer.source == "price_list"
        assert offer.valid_from == date(2026, 11, 1) and offer.valid_until == date(2027, 12, 31)
        assert offer.confirmed_at is not None and offer.confirmed_by_contact_id == w["a_contact"].pk
        # после загрузки карточка в списке партнёра: черновик, своя цена
        item = next(i for i in w["client_a"].get(f"{PREFIX}/products").json()["items"] if i["id"] == card.pk)
        assert item["status"] == "draft" and item["offer"]["price"] == {"amount": "120.00", "currency": "USD"}
        assert item["offer"]["confirmed_at"] is not None and item["offer"]["freshness"] == "fresh"

    def test_supplier_is_the_session_company_and_cannot_be_chosen(self, partner_world, broker):
        w = partner_world
        upload(w["client_a"], xlsx([row()]), supplier_company_id=str(w["b"].pk), supplier=str(w["b"].pk))
        assert broker.calls[0]["supplier_id"] == w["a"].pk and broker.calls[0]["contact_id"] == w["a_contact"].pk
        assert broker.calls[0]["owner_company_id"] == w["own"].pk and "actor_id" not in broker.calls[0]
        assert SupplierOffer.objects.filter(supplier=w["b"], product__manufacturer_part_number="AQ-50").count() == 0
        assert SupplierOffer.objects.filter(supplier=w["a"], product__manufacturer_part_number="AQ-50").count() == 1

    def test_task_is_recorded_for_the_contact(self, partner_world, broker):
        w = partner_world
        task_id = upload(w["client_a"], xlsx([row()])).json()["task_id"]
        task = ImportTask.objects.get(celery_task_id=task_id)
        assert task.contact_id == w["a_contact"].pk and task.owner_id is None and task.task_type == "CATALOG_IMPORT"

    def test_own_draft_and_returned_cards_are_updated_review_and_published_get_proposals(self, partner_world, broker):
        w = partner_world
        c = w["cards"]
        category = Category.objects.create(name="Задвижки")
        records = [
            row(**{"Наименование": "Болт А-1 новое имя", "Артикул производителя": "A-1", "Бренд": "Аквилон"}),
            row(**{"Наименование": "Болт А-3 новое имя", "Артикул производителя": "A-3", "Категория": category.name}),
            row(**{"Наименование": "Болт А-2 новое имя", "Артикул производителя": "A-2"}),
            row(**{"Наименование": "Болт А-4 новое имя", "Артикул производителя": "A-4"}),
        ]
        body = report(w["client_a"], upload(w["client_a"], xlsx(records)).json()["task_id"])["report"]
        assert body["created"] == 0 and body["updated"] == 4
        assert Product.objects.get(pk=c["draft"].pk).name == "Болт А-1 новое имя"
        returned = Product.objects.get(pk=c["returned"].pk)
        assert returned.name == "Болт А-3 новое имя" and returned.category_id == category.pk
        assert returned.status.code == "RETURNED"  # исправляет партнёр, на проверку отправляет сам
        assert Product.objects.get(pk=c["review"].pk).name == "Болт А-2"  # на проверке прайс карточку не меняет
        assert Product.objects.get(pk=c["published"].pk).name == "Болт А-4"
        proposed = ProductFieldProposal.objects.filter(supplier=w["a"])
        assert {p.product_id for p in proposed} == {c["review"].pk, c["published"].pk}
        assert all(p.contact_id == w["a_contact"].pk and p.created_by_id is None for p in proposed)
        assert body["proposal_count"] == 2
        assert {(p["field"]) for p in body["proposals"]} == {"name"}

    def test_foreign_card_keeps_its_fields_and_the_report_does_not_leak_them(self, partner_world, broker):
        """Совпадение с чужой карточкой: цена А записана, поля карточки Б не тронуты, в отчёте нет её содержимого."""
        w = partner_world
        card = w["cards"]["b_only"]
        records = [row(**{"Наименование": "Другое имя", "Артикул производителя": "B-1", "Бренд": "Аквилон"})]
        task_id = upload(w["client_a"], xlsx(records)).json()["task_id"]
        text = w["client_a"].get(f"{URL}/{task_id}").content.decode()
        assert Product.objects.get(pk=card.pk).name == "Секретная деталь Б-1"
        assert SupplierOffer.objects.filter(product=card, supplier=w["a"]).exists()
        assert "Секретная деталь" not in text and "product_name" not in text and "current" not in text
        assert '"555.55"' not in text

    def test_rejected_proposal_is_not_offered_again(self, partner_world, broker):
        w = partner_world
        records = [row(**{"Наименование": "Болт А-4 иначе", "Артикул производителя": "A-4"})]
        upload(w["client_a"], xlsx(records))
        ProductFieldProposal.objects.filter(supplier=w["a"]).update(status="rejected")
        task_id = upload(w["client_a"], xlsx(records)).json()["task_id"]
        assert report(w["client_a"], task_id)["report"]["proposal_count"] == 0

    @pytest.mark.parametrize(
        ("content", "code", "http"),
        [
            (b"not an excel", "XLSX_REQUIRED", 400),
            (b"PK\x03\x04" + b"0" * 10, None, 202),  # подпись верна — дальше разбирает движок
        ],
    )
    def test_file_checks(self, partner_world, broker, monkeypatch, content, code, http):
        monkeypatch.setattr(
            "portal.services.partner_price_list.process_catalog_import.delay",
            lambda *a, **k: SimpleNamespace(id=uuid.uuid4().hex),
        )
        response = upload(partner_world["client_a"], content)
        assert response.status_code == http
        if code:
            assert response.json() == {"detail": code}

    def test_no_file_is_400(self, partner_world, broker):
        response = partner_world["client_a"].post(URL, {"dry_run": "true"}, format="multipart")
        assert response.status_code == 400 and response.json() == {"detail": "FILE_REQUIRED"}

    def test_too_large_file_is_422(self, partner_world, broker, monkeypatch):
        monkeypatch.setattr("portal.services.partner_price_list.MAX_EXCEL_FILE_SIZE", 10)
        response = upload(partner_world["client_a"], xlsx([row()]))
        assert response.status_code == 422 and response.json() == {"detail": "FILE_TOO_LARGE"}

    @pytest.mark.parametrize(
        ("params", "code"),
        [
            ({"valid_until": "31.12.2027"}, "VALID_DATE_INVALID"),
            ({"valid_from": "2027-02-30"}, "VALID_DATE_INVALID"),
            ({"valid_from": "2027-05-01", "valid_until": "2027-04-01"}, "OFFER_VALIDITY_RANGE_INVALID"),
        ],
    )
    def test_validity_checks(self, partner_world, broker, params, code):
        response = upload(partner_world["client_a"], xlsx([row()]), **params)
        assert response.status_code == 422 and response.json() == {"detail": code}
        assert broker.calls == []

    def test_json_body_is_still_refused(self, partner_world, broker):
        response = partner_world["client_a"].post(URL, {"file": "x"}, format="json")
        assert response.status_code in (400, 415, 422)

    def test_queue_failure_is_503(self, partner_world, monkeypatch):
        from kombu.exceptions import OperationalError

        def boom(*args, **kwargs):
            raise OperationalError("broker down")

        monkeypatch.setattr("portal.services.partner_price_list.process_catalog_import.delay", boom)
        response = upload(partner_world["client_a"], xlsx([row()]))
        assert response.status_code == 503 and response.json() == {"detail": "IMPORT_FAILED"}

    def test_no_own_company_means_no_upload(self, partner_world, broker, settings, monkeypatch):
        monkeypatch.setattr("portal.services.partner_price_list.own_company_id", lambda: None)
        response = upload(partner_world["client_a"], xlsx([row()]))
        assert response.status_code == 503 and response.json() == {"detail": "IMPORT_FAILED"}
        assert broker.calls == []

    def test_unknown_category_is_a_row_error_with_row_number(self, partner_world, broker):
        records = [row(), row(**{"Категория": "Нет такой", "Артикул производителя": "Z-9"})]
        body = report(partner_world["client_a"], upload(partner_world["client_a"], xlsx(records)).json()["task_id"])
        assert body["report"]["errors"] == [
            {"row": 3, "field": "category", "code": "UNKNOWN_CATEGORY", "value": "Нет такой"}
        ]
        assert body["report"]["created"] == 1

    def test_missing_name_column_fails_the_whole_file_with_a_code(self, partner_world, broker, monkeypatch):
        results = {}

        def delay(b64, supplier_id, dry_run, **options):
            task_id = uuid.uuid4().hex
            from sourcing.tasks import process_catalog_import

            results[task_id] = process_catalog_import.apply(args=(b64, supplier_id, dry_run), kwargs=options).result
            return SimpleNamespace(id=task_id)

        monkeypatch.setattr("portal.services.partner_price_list.process_catalog_import.delay", delay)
        monkeypatch.setattr(
            "portal.services.partner_price_list.async_result",
            lambda task_id: SimpleNamespace(state="SUCCESS", result=results[task_id]),
        )
        task_id = upload(partner_world["client_a"], xlsx([{"Цена": "1"}])).json()["task_id"]
        body = report(partner_world["client_a"], task_id)
        assert body == {"task_id": task_id, "status": "failed", "error": "NAME_COLUMN_NOT_FOUND", "report": None}


class TestTaskStatus:
    def test_other_partner_cannot_read_the_task(self, partner_world, broker):
        w = partner_world
        task_id = upload(w["client_a"], xlsx([row()])).json()["task_id"]
        for client in (w["client_b"],):
            response = client.get(f"{URL}/{task_id}")
            assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}

    def test_unknown_task_and_task_of_an_employee_are_404(self, partner_world, broker):
        w = partner_world
        ImportTask.objects.create(celery_task_id="staff-task", owner=w["staff"], task_type="CATALOG_IMPORT")
        for task_id in ("nope", "staff-task"):
            assert w["client_a"].get(f"{URL}/{task_id}").status_code == 404

    def test_colleague_of_the_same_company_reads_the_task(self, partner_world, broker):
        from parties.models import Contact
        from portal.tests.partner_world import client_for

        w = partner_world
        task_id = upload(w["client_a"], xlsx([row()])).json()["task_id"]
        colleague = Contact.objects.create(company=w["a"], name="Коллега", email="c@plant-north.example", can_act=False)
        assert client_for(colleague).get(f"{URL}/{task_id}").status_code == 200

    @pytest.mark.parametrize(
        ("state", "status"),
        [("PENDING", "pending"), ("STARTED", "running"), ("PROGRESS", "running"), ("FAILURE", "failed")],
    )
    def test_states(self, partner_world, monkeypatch, state, status):
        w = partner_world
        ImportTask.objects.create(celery_task_id="t1", contact=w["a_contact"], task_type="CATALOG_IMPORT")
        monkeypatch.setattr(
            "portal.services.partner_price_list.async_result",
            lambda task_id: SimpleNamespace(state=state, result=RuntimeError("секретный трейс")),
        )
        response = w["client_a"].get(f"{URL}/t1")
        assert response.json()["status"] == status
        assert "секретный трейс" not in response.content.decode()
        assert response.json()["error"] == ("IMPORT_FAILED" if state == "FAILURE" else None)


class TestHistory:
    def test_price_history_names_the_contact_for_staff(self, partner_world, broker):
        """Цена, загруженная партнёром, в истории предложения подписана контактом (метаданные pghistory `contact`)."""
        from types import SimpleNamespace as NS

        from catalog.desk.suppliers import offer_history

        w = partner_world
        upload(w["client_a"], xlsx([row()]))
        offer = SupplierOffer.objects.get(product__manufacturer_part_number="AQ-50")
        # в тестовой базе контекст pghistory — заглушка (conftest), подставляем метаданные как их кладёт движок
        from pghistory.models import Context

        ctx = Context.objects.create(metadata={"contact": w["a_contact"].pk, "source": "price_list"})
        offer.events.update(pgh_context=ctx)
        rows = offer_history(offer, NS(is_superuser=True, is_authenticated=True))
        assert rows and rows[0]["by"] == w["a_contact"].name


class TestRowIssues:
    """Отчёт по строкам: номер строки, колонка шаблона, код и значение — кабинет по ним пишет «что исправить»."""

    @pytest.mark.parametrize(
        ("cells", "field", "code", "value"),
        [
            ({"Цена": "-5"}, "price", "PRICE_NOT_POSITIVE", None),
            ({"Валюта": "XXX"}, "currency", "UNKNOWN_CURRENCY", "XXX"),
            ({"Наличие": "MAYBE"}, "stock", "UNKNOWN_STOCK_STATUS", "MAYBE"),
            ({"Направление": "Космос"}, "domain_type", "UNKNOWN_DOMAIN", "Космос"),
            ({"Действует с": "вчера"}, "valid_from", "VALID_DATE_INVALID", None),
            (
                {"Действует с": "2027-05-01", "Действует до": "2027-04-01"},
                "valid_until",
                "OFFER_VALIDITY_RANGE_INVALID",
                None,
            ),
        ],
    )
    def test_errors_name_the_column_and_value(self, partner_world, broker, cells, field, code, value):
        records = [row(**{"Артикул производителя": "OK-1"}), row(**{"Артикул производителя": "BAD-1", **cells})]
        body = report(partner_world["client_a"], upload(partner_world["client_a"], xlsx(records)).json()["task_id"])
        assert body["report"]["errors"] == [{"row": 3, "field": field, "code": code, "value": value}]

    def test_warning_about_unknown_hs_code_names_the_column(self, partner_world, broker):
        records = [row(**{"Код ТН ВЭД": "99999999999999999999"})]
        body = report(partner_world["client_a"], upload(partner_world["client_a"], xlsx(records)).json()["task_id"])
        assert body["report"]["created"] == 1  # предупреждение строку не блокирует
        assert body["report"]["warnings"] == [
            {"row": 2, "field": "hs_code", "code": "HS_CODE_TOO_LONG", "value": "99999999999999999999"}
        ]
