"""ТЕСТ-2: охрана шлюза доставки уведомлений ERP.

Каждый вид уведомления из кода отнесён к «сделочным» (нужен `deal=`) или «без сделки» (список явный); письма сотрудникам по
сделкам уходят только через `notifications.gate.staff_recipients`.
"""

import pathlib
import re

import pytest

from notifications.subjects import is_company_free, is_deal_scoped

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _sources():
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in f"/{rel}" or "migrations" in rel or rel.endswith(("conftest.py", "settings_pytest.py")):
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_every_notification_kind_is_classified():
    codes = set()
    for _rel, text in _sources():
        codes.update(re.findall(r'event_code\s*=\s*"([a-z_]+\.[a-z_.]+)"', text))
    unknown = sorted(c for c in codes if not (is_deal_scoped(c) or is_company_free(c)))
    assert not unknown, f"вид уведомления без классификации (notifications/subjects.py): {unknown}"


def test_staff_email_goes_only_through_the_gate():
    allowed = {  # где ставят письма сотрудникам в очередь и чем они гейтятся
        "notifications/signals.py": "staff_recipients",
        "crm/services/deal_emails.py": "staff_recipients",
        "accounts/services/auth.py": None,  # пароль сотрудника, не запись сделки
    }
    found = {rel for rel, text in _sources() if "send_transactional_email.delay(" in text}
    assert found <= set(allowed), f"письмо сотруднику мимо шлюза: {sorted(found - set(allowed))}"
    for rel, needle in allowed.items():
        if needle:
            assert needle in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_notifications_are_created_only_through_the_manager():
    """Охрана: прямой `bulk_create`/`_base_manager` для уведомлений обходит шлюз."""
    bad = [
        rel
        for rel, text in _sources()
        if re.search(r"Notification\._base_manager|Notification\._default_manager", text)
    ]
    assert not bad, bad


@pytest.mark.django_db
def test_a_deal_scoped_kind_without_a_deal_is_refused():
    from accounts.models import CustomUser
    from notifications.models import Notification

    user = CustomUser.objects.create(username="u@x.example", email="u@x.example")
    with pytest.raises(ValueError):
        Notification.objects.create(user=user, title="t", message="m", event_code="quote.approval_your_turn")
    assert Notification.objects.create(
        user=user, title="t", message="m", event_code="catalog.category_request_approved"
    ).pk
