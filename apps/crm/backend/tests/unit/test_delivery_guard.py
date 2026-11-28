"""ТЕСТ-2: охрана шлюза доставки сотрудникам (CRM).

Колокольчик и Telegram по ERP- и EDS-событиям пишутся только в `services/test_delivery.py`:
ни `add_in`, ни `"kind": "staff"` в модулях этих уведомлений вне шлюза не встречаются. Остальные
записи в колокольчик (`add_in`) — в явном списке с причиной; новое место — сначала в список.
"""

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

GATE = "services/test_delivery.py"
# записи в колокольчик вне шлюза: уведомления не по записям тестовых компаний
OTHER_BELL_WRITERS = {
    "services/leads.py",  # лид: уведомления по нему идут как раньше
    "services/staff_tickets.py",  # обращения сотрудников в поддержку
    "services/partner_clients.py",  # партнёры, не клиенты
    "services/staff_notifications.py",  # определение `add_in`
}
GATED_MODULES = ("services/erp_events.py", "services/eds_notices.py")
TELEGRAM_ITEM = re.compile(r"""["']kind["']\s*:\s*["']staff["']|kind\s*=\s*["']staff["']""")
BELL_WRITE = re.compile(r"\b(?:staff_notifications|notes)\.add_in\(")


def _text(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _files(rx: re.Pattern[str]) -> set[str]:
    return {
        p.relative_to(APP).as_posix() for p in APP.rglob("*.py") if rx.search(p.read_text("utf-8"))
    }


def test_bell_is_written_only_by_the_gate_or_listed_modules() -> None:
    extra = sorted(_files(BELL_WRITE) - OTHER_BELL_WRITERS - {GATE})
    assert not extra, f"новая запись в колокольчик мимо шлюза: {extra}"


def test_staff_telegram_items_are_built_only_by_the_gate() -> None:
    extra = sorted(_files(TELEGRAM_ITEM) - {GATE, "models/integrations.py"})
    assert not extra, f"сообщение сотруднику в Telegram мимо шлюза: {extra}"


def test_erp_and_eds_notice_modules_use_the_gate_and_have_no_direct_writes() -> None:
    for rel in GATED_MODULES:
        text = _text(rel)
        assert "test_delivery.deliver_staff(" in text, rel
        assert not BELL_WRITE.search(text), rel
        assert not TELEGRAM_ITEM.search(text), rel
