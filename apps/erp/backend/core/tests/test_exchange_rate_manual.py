"""W13C-F6: ручной ввод курса USD→UZS на дату, журнал и «автокурс не перетирает ручной».

Право на ввод — `settings.edit` или администратор; журнал — сотруднику бэк-офиса; текущий курс — любому вошедшему.
"""

import datetime
from decimal import Decimal

import pytest
from finance.services import fx
from rest_framework.test import APIClient
from sales.tests.helpers_fx import currency, set_rate

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from core.models import ExchangeRate
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db
CURRENT = "/api/v1/exchange-rates/current/"
JOURNAL = "/api/v1/exchange-rates/journal/"
MANUAL = "/api/v1/exchange-rates/manual/"


def _today():
    from django.utils import timezone

    return timezone.localdate()


def _client(email: str, permissions: list[str] | None = None, *, superuser=False, client_company=False) -> APIClient:
    user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
    user.first_name = "Анна"
    user.last_name = "Иванова"
    user.is_superuser = superuser
    user.save()
    if permissions is not None:
        kind, _ = CompanyType.objects.get_or_create(
            code="CLIENT" if client_company else "SUPPLIER", defaults={"name": "Тип", "sort_order": 20}
        )
        # Своя компания одна на тест (иначе ERP не поймёт, чья она): все сотрудники — её члены.
        key = "client" if client_company else "own"
        if key not in _COMPANIES:
            _COMPANIES[key] = Company.objects.create(
                name=f"ООО {key}", inn="9700000001" if key == "own" else "9700000002"
            )
            _COMPANIES[key].types.add(kind)
        company = _COMPANIES[key]
        workspace_role, _ = WorkspaceRole.objects.get_or_create(
            code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
        )
        role = CompanyRole.objects.create(company=company, name=f"Роль {email}", permissions=permissions)
        CompanyMember.objects.create(
            user=user,
            company=company,
            role=workspace_role,
            company_roles=[role],
            is_active=True,
            is_primary=True,
            can_sell=not client_company,
        )
    client = APIClient()
    client.force_authenticate(user)
    return client


_EDITORS: dict[str, APIClient] = {}
_COMPANIES: dict[str, Company] = {}


@pytest.fixture(autouse=True)
def _forget_editor():
    _EDITORS.clear()
    _COMPANIES.clear()


def _editor():
    """Один редактор на тест: клиент создаётся при первом обращении."""
    if "editor" not in _EDITORS:
        _EDITORS["editor"] = _client("editor@f6.test", ["settings.edit"])
    return _EDITORS["editor"]


def _body(rate="12750.5", rate_date=None, **extra):
    day = rate_date or _today()
    return {"rate_date": day if isinstance(day, str) else day.isoformat(), "rate_to_uzs": rate, **extra}


# --- права ---------------------------------------------------------------------------------------------------------


def test_editor_enters_rate_and_it_becomes_current():
    currency("USD")
    response = _editor().post(MANUAL, _body(), format="json")

    assert response.status_code == 201
    assert response.json() == {
        "currency": "USD",
        "rate_to_uzs": "12750.5",
        "rate_date": _today().isoformat(),
        "source": "MANUAL",
    }
    current = _editor().get(CURRENT).json()
    assert current["current"]["rate_to_uzs"] == "12750.5"
    assert current["current"]["source"] == "MANUAL"
    assert current["max_age_days"] >= 1


def test_superuser_can_enter_rate():
    currency("USD")
    assert _client("root@f6.test", superuser=True).post(MANUAL, _body(), format="json").status_code == 201


@pytest.mark.parametrize("permissions", [["catalog.manage"], ["finance.rates"], []])
def test_staff_without_settings_edit_is_denied(permissions):
    currency("USD")
    response = _client("plain@f6.test", permissions).post(MANUAL, _body(), format="json")

    assert response.status_code == 403
    assert not ExchangeRate.objects.exists()


def test_anonymous_gets_401():
    assert APIClient().post(MANUAL, _body(), format="json").status_code == 401
    assert APIClient().get(CURRENT).status_code == 401
    assert APIClient().get(JOURNAL).status_code == 401


def test_client_company_member_cannot_read_journal_or_write():
    currency("USD")
    client = _client("buyer@f6.test", ["settings.edit"], client_company=True)

    assert client.post(MANUAL, _body(), format="json").status_code == 403
    assert client.get(JOURNAL).status_code == 403


# --- проверка значений ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "code"),
    [
        ("0", "FX_RATE_INVALID"),
        ("-5", "FX_RATE_INVALID"),
        ("abc", "FX_RATE_INVALID"),
        ("", "FX_RATE_INVALID"),
        ("NaN", "FX_RATE_INVALID"),
        ("1000000000", "FX_RATE_INVALID"),
        ("12700.1234567", "FX_RATE_INVALID"),  # больше 6 знаков
    ],
)
def test_rate_must_be_positive_sane_number(rate, code):
    currency("USD")
    response = _editor().post(MANUAL, _body(rate), format="json")

    assert response.status_code == 400
    assert response.json()["detail"] == code
    assert not ExchangeRate.objects.exists()


@pytest.mark.parametrize(
    ("days", "code"),
    [(-1, "FX_RATE_DATE_IN_FUTURE"), (367, "FX_RATE_DATE_TOO_OLD")],
)
def test_date_window(days, code):
    currency("USD")
    rate_date = _today() - datetime.timedelta(days=days)
    response = _editor().post(MANUAL, _body(rate_date=rate_date), format="json")

    assert response.status_code == 400
    assert response.json()["detail"] == code


def test_bad_date_and_currency():
    currency("USD")
    assert (
        _editor().post(MANUAL, _body(rate_date="2026-13-45"), format="json").json()["detail"] == "FX_RATE_DATE_INVALID"
    )
    assert _editor().post(MANUAL, {"rate_to_uzs": "1"}, format="json").json()["detail"] == "FX_RATE_DATE_INVALID"
    unsupported = _editor().post(MANUAL, _body(currency="XYZ"), format="json")
    assert unsupported.json()["detail"] == "FX_CURRENCY_UNSUPPORTED"
    assert _editor().get(CURRENT, {"currency": "XYZ"}).status_code == 400


def test_backdated_rate_is_accepted_at_the_edge():
    currency("USD")
    rate_date = _today() - datetime.timedelta(days=366)
    assert _editor().post(MANUAL, _body(rate_date=rate_date), format="json").status_code == 201


def test_six_decimals_are_kept():
    currency("USD")
    _editor().post(MANUAL, _body("12700.123456"), format="json")
    assert ExchangeRate.objects.get().rate_to_uzs == Decimal("12700.123456")


# --- журнал ---------------------------------------------------------------------------------------------------------


def test_manual_entry_is_journaled_with_who_when_and_previous_value():
    set_rate("USD", "12700")  # курс ЦБ на сегодня
    _editor().post(MANUAL, _body("12800"), format="json")
    _editor().post(MANUAL, _body("12900"), format="json")

    rows = _editor().get(JOURNAL).json()

    assert [r["rate_to_uzs"] for r in rows] == ["12900", "12800"]  # новые первыми
    newest, first = rows
    assert newest["kind"] == "manual"
    assert newest["currency"] == "USD"
    assert newest["rate_date"] == _today().isoformat()
    assert (newest["previous_rate_to_uzs"], newest["previous_source"]) == ("12800", "MANUAL")
    assert (first["previous_rate_to_uzs"], first["previous_source"]) == ("12700", "CBU")
    assert newest["entered_by_email"] == "editor@f6.test"
    assert newest["entered_by_name"] == "Анна Иванова"
    assert newest["entered_at"]
    log = ActivityLog.objects.get(pk=newest["id"])
    assert log.event_code == "admin.exchange_rate.manual"
    assert log.entity_type == "core.exchangerate"


def test_first_entry_has_no_previous_value():
    currency("USD")
    _editor().post(MANUAL, _body(), format="json")

    row = _editor().get(JOURNAL).json()[0]

    assert row["previous_rate_to_uzs"] is None
    assert row["previous_source"] is None


def test_repeating_the_same_manual_value_writes_nothing():
    currency("USD")
    _editor().post(MANUAL, _body(), format="json")
    again = _editor().post(MANUAL, _body(), format="json")

    assert again.status_code == 201
    assert ActivityLog.objects.filter(event_code="admin.exchange_rate.manual").count() == 1
    assert ExchangeRate.objects.count() == 1


def test_journal_limit_and_currency_filter():
    currency("USD")
    currency("EUR")
    for index in range(3):
        _editor().post(MANUAL, _body(str(12000 + index), _today() - datetime.timedelta(days=index)), format="json")
    _editor().post(MANUAL, _body("14000", currency="EUR"), format="json")

    assert len(_editor().get(JOURNAL, {"limit": 2}).json()) == 2
    assert len(_editor().get(JOURNAL).json()) == 3  # только USD
    assert [r["currency"] for r in _editor().get(JOURNAL, {"currency": "EUR"}).json()] == ["EUR"]
    assert len(_editor().get(JOURNAL, {"limit": "x"}).json()) == 3


def test_read_only_staff_sees_the_journal_but_cannot_write():
    currency("USD")
    _editor().post(MANUAL, _body(), format="json")
    reader = _client("reader@f6.test", ["catalog.manage"])

    assert len(reader.get(JOURNAL).json()) == 1
    assert reader.post(MANUAL, _body("1"), format="json").status_code == 403


# --- текущий курс ---------------------------------------------------------------------------------------------------


def test_current_is_null_when_no_fresh_rate():
    set_rate("USD", "12700", days_ago=30)
    body = _client("any@f6.test").get(CURRENT).json()

    assert body["current"] is None
    assert body["currency"] == "USD"


def test_current_reports_date_and_source_of_auto_rate():
    rate_date = set_rate("USD", "12701.5", days_ago=1)
    current = _editor().get(CURRENT).json()["current"]

    assert current == {"currency": "USD", "rate_to_uzs": "12701.5", "rate_date": rate_date.isoformat(), "source": "CBU"}


# --- автозагрузка не перетирает ручной ------------------------------------------------------------------------------


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _cbu(monkeypatch, rate, rate_date=None):
    day = (rate_date or _today()).strftime("%d.%m.%Y")
    monkeypatch.setattr("httpx.get", lambda url, **kw: _Resp([{"Ccy": "USD", "Rate": rate, "Date": day}]))


def test_auto_load_does_not_overwrite_manual_rate_and_journals_the_skip(monkeypatch):
    currency("USD")
    _editor().post(MANUAL, _body("12800"), format="json")
    _cbu(monkeypatch, "12700.00")

    assert fx.fetch_cbu_rates() == 0
    fx.fetch_cbu_rates()  # второй запуск — запись о пропуске не дублируется

    row = ExchangeRate.objects.get()
    assert (row.rate_to_uzs, row.source) == (Decimal("12800"), "MANUAL")
    skipped = ActivityLog.objects.filter(event_code="admin.exchange_rate.auto_skipped")
    assert skipped.count() == 1
    entry = [r for r in _editor().get(JOURNAL).json() if r["kind"] == "auto_skipped"][0]
    assert entry["rate_to_uzs"] == "12700"  # то, что прислал ЦБ
    assert entry["previous_rate_to_uzs"] == "12800"  # то, что осталось
    assert entry["entered_by_email"] == ""


def test_auto_load_with_same_value_as_manual_is_silent(monkeypatch):
    currency("USD")
    _editor().post(MANUAL, _body("12800"), format="json")
    _cbu(monkeypatch, "12800")

    fx.fetch_cbu_rates()

    assert not ActivityLog.objects.filter(event_code="admin.exchange_rate.auto_skipped").exists()


def test_auto_load_still_updates_auto_rows_and_other_dates(monkeypatch):
    currency("USD")
    yesterday = _today() - datetime.timedelta(days=1)
    set_rate("USD", "12600", days_ago=1)  # ЦБ вчера
    _editor().post(MANUAL, _body("12800"), format="json")  # вручную сегодня
    _cbu(monkeypatch, "12650", yesterday)

    assert fx.fetch_cbu_rates() == 1

    assert ExchangeRate.objects.get(rate_date=yesterday).rate_to_uzs == Decimal("12650")
    assert ExchangeRate.objects.get(rate_date=_today()).source == "MANUAL"


def test_manual_entry_replaces_a_cbu_row_for_the_same_date():
    set_rate("USD", "12700")
    _editor().post(MANUAL, _body("12800"), format="json")

    row = ExchangeRate.objects.get()
    assert (row.rate_to_uzs, row.source) == (Decimal("12800"), "MANUAL")
