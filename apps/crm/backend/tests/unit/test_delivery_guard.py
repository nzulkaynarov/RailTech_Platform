"""ТЕСТ-2: охрана шлюза доставки сотрудникам (CRM).

Колокольчик сотруднику (`add_in`) и Telegram по ERP/EDS-событиям (`ErpEventNotices.add`) вне
разрешённых модулей не пишутся; модули по записям ERP и EDS пропускают получателей через
`test_delivery.allowed`. Новое место доставки — сначала в список и под шлюз, иначе тест красный.
"""

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# где пишут колокольчик сотруднику (`add_in`) — и почему шлюз не нужен
BELL_WRITERS = {
    "services/erp_events.py": "gate",  # ERP-события: клиент может быть тестовым
    "services/eds_notices.py": "gate",  # EDS-уведомления: `is_test` из события
    "services/leads.py": "own",  # лид: уведомления по нему идут как раньше
    "services/staff_tickets.py": "own",  # обращения сотрудников в поддержку
    "services/partner_clients.py": "own",  # партнёры, не клиенты
}
PUSHERS = {  # `self._notices.add(` / `notices.add(` — Telegram по событиям
    "services/erp_events.py",
    "services/eds_notices.py",
    "services/erp_acceptance_code.py",
    "services/erp_invite_delivery.py",
    "services/client_notices.py",
    "bus/notices.py",
    "container.py",
}


def _files(pattern: str) -> set[str]:
    rx = re.compile(pattern)
    return {
        p.relative_to(APP).as_posix()
        for p in APP.rglob("*.py")
        if rx.search(p.read_text(encoding="utf-8"))
    }


def test_bell_writers_are_known() -> None:
    found = _files(r"\b(?:staff_notifications|notes)\.add_in\(")
    assert found <= set(BELL_WRITERS), (
        f"новая запись в колокольчик мимо шлюза: {sorted(found - set(BELL_WRITERS))}"
    )


def test_notice_pushers_are_known() -> None:
    found = _files(r"\b_?notices\.add\(")
    extra = sorted(found - PUSHERS)
    assert not extra, f"новая доставка по событию мимо шлюза: {extra}"


def test_gated_modules_use_the_gate() -> None:
    for rel, kind in BELL_WRITERS.items():
        if kind == "gate":
            assert "test_delivery.allowed(" in (APP / rel).read_text(encoding="utf-8"), rel
