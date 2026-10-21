"""FIX-55 / D-04 (хвост): импорт файла в сделку не пишет строки в КП вне черновика.

`ExcelImportView` → `process_excel_import` писали в `deal.active_quote` в любом статусе, а `merge_request_lines`
складывал количества и пересчитывал сумму согласованного/отправленного/принятого КП. Теперь вьюха отвечает 409
(`QUOTE_NOT_DRAFT` / `QUOTE_FROZEN`), а задача перед записью перепроверяет КП (статус мог смениться между
постановкой и выполнением) и завершается ошибкой импорта, ничего не меняя. Нет активного КП — как раньше.
"""

import base64
import io
from decimal import Decimal

import pandas as pd
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CustomUser
from crm.constants import QuoteStatusCode
from crm.models import QuoteItem, QuoteStatus
from crm.tests.test_quote_edit_lock import _set_status
from crm.tests.test_quote_items_bulk_update import _quote_with_items, lookups, world  # noqa: F401
from sourcing.tasks import process_excel_import

# flake8: noqa: F811

pytestmark = pytest.mark.django_db

NON_DRAFT = [code for code in QuoteStatusCode.values if code != QuoteStatusCode.DRAFT]


def _xlsx_b64(rows):
    buffer = io.BytesIO()
    pd.DataFrame([["Наименование", "Кол-во"], *rows]).to_excel(buffer, header=False, index=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _admin():
    return CustomUser.objects.create_user(
        email="root-import@t.test", username="root-import@t.test", password="x", is_superuser=True, is_staff=True
    )


def _state(quote):
    quote.refresh_from_db()
    return (
        list(QuoteItem.objects.filter(quote=quote).order_by("id").values_list("id", "imported_raw_name", "quantity")),
        quote.total_incl_vat,
    )


def _post_import(user, deal):
    client = APIClient()
    client.force_authenticate(user)
    return client.post(f"/api/v1/sourcing/import-deal/{deal.id}/", {}, format="multipart")


@pytest.mark.parametrize("status_code", NON_DRAFT)
def test_view_refuses_non_draft_active_quote(world, status_code):  # noqa: F811
    deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    _set_status(quote, status_code)

    response = _post_import(_admin(), deal)

    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "QUOTE_NOT_DRAFT"


def test_view_refuses_frozen_active_quote(world):  # noqa: F811
    deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    response = _post_import(_admin(), deal)

    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "QUOTE_FROZEN"


def test_view_lets_a_draft_quote_through_to_file_validation(world):  # noqa: F811
    deal, _quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])

    response = _post_import(_admin(), deal)

    assert response.status_code == 400 and response.json()["detail"] == "FILE_REQUIRED"


@pytest.mark.parametrize("status_code", NON_DRAFT)
def test_task_does_not_write_into_non_draft_quote(world, status_code):  # noqa: F811
    deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    QuoteItem.objects.filter(quote=quote).update(imported_raw_name="Позиция 0")
    _set_status(quote, status_code)
    before = _state(quote)

    result = process_excel_import.apply(args=[deal.id, _xlsx_b64([["Позиция 0", 5], ["Новая", 1]]), _admin().id]).get()

    assert result["status"] == "error"
    assert result["code"] == "QUOTE_NOT_DRAFT"
    assert _state(quote) == before, "сумма и количества согласованного КП не меняются"


def test_task_rechecks_the_quote_right_before_writing(world, monkeypatch):  # noqa: F811
    """Статус сменился уже ПОСЛЕ старта задачи (во время разбора файла): запись отменяется."""
    deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    before = _state(quote)
    original = pd.read_excel

    def read_then_submit(*args, **kwargs):
        frame = original(*args, **kwargs)
        _set_status(quote, QuoteStatusCode.PENDING_APPROVAL)  # менеджер отправил КП на согласование
        return frame

    monkeypatch.setattr("sourcing.tasks.pd.read_excel", read_then_submit)

    result = process_excel_import.apply(args=[deal.id, _xlsx_b64([["Новая", 3]]), _admin().id]).get()

    assert result["status"] == "error" and result["code"] == "QUOTE_NOT_DRAFT"
    assert _state(quote) == before


def test_task_still_imports_into_a_draft_quote(world):  # noqa: F811
    deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])

    result = process_excel_import.apply(args=[deal.id, _xlsx_b64([["Новая", 3]]), _admin().id]).get()

    assert result["status"] == "success", result
    assert QuoteItem.objects.filter(quote=quote, imported_raw_name="Новая", quantity=3).exists()


def test_task_without_active_quote_creates_a_draft_as_before(world):  # noqa: F811
    from crm.models import Deal, DealStage

    deal = Deal.objects.create(title="Без КП", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT"))
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})

    result = process_excel_import.apply(args=[deal.id, _xlsx_b64([["Новая", 3]]), _admin().id]).get()

    assert result["status"] == "success", result
    created = deal.quotes.get()
    assert created.status.code == "DRAFT" and created.items.count() == 1
