"""Ссылки уведомлений CRM (W15-H8b, B-009): одна карта маршрутов — Платформа, иначе старая CRM."""

import pytest

from app.domain.platform_links import LinkBase, notification_link

PLATFORM = "https://platform.example.com"
CRM = "https://crm.example.com"


@pytest.mark.parametrize(
    ("kind", "ref", "expected"),
    [
        # лид: номер как в Платформе (`L-0042`), боковое окно с карточкой
        ("lead", 42, f"{PLATFORM}/crm/leads?lead=L-0042&panel=open&tab=card"),
        ("lead", 12345, f"{PLATFORM}/crm/leads?lead=L-12345&panel=open&tab=card"),
        ("dashboard", None, f"{PLATFORM}/dashboard/summary"),
        ("integrations", None, f"{PLATFORM}/admin/integrations"),
        ("bus", None, f"{PLATFORM}/admin/bus"),
    ],
)
def test_platform_routes(kind: str, ref: int | None, expected: str) -> None:
    assert notification_link(kind, ref, platform=PLATFORM, crm=CRM) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "ref", "expected"),
    [
        ("lead", 42, f"{CRM}/leads/42"),
        ("dashboard", None, f"{CRM}/dashboard"),
        # у «Подключений» и журнала шины в старой CRM нет своего адреса: ссылки не будет
        ("integrations", None, None),
        ("bus", None, None),
    ],
)
def test_without_a_platform_address_links_lead_to_the_old_crm(
    kind: str, ref: int | None, expected: str | None
) -> None:
    assert notification_link(kind, ref, platform=None, crm=CRM) == expected  # type: ignore[arg-type]
    assert notification_link(kind, ref, platform="", crm=CRM) == expected  # type: ignore[arg-type]


def test_trailing_slashes_are_not_doubled() -> None:
    assert notification_link("dashboard", None, platform=PLATFORM + "/", crm=CRM) == (
        f"{PLATFORM}/dashboard/summary"
    )
    assert notification_link("dashboard", None, platform=None, crm=CRM + "/") == f"{CRM}/dashboard"


def test_lead_needs_a_number() -> None:
    with pytest.raises(ValueError, match="lead"):
        notification_link("lead", None, platform=PLATFORM, crm=CRM)


def test_unknown_kind_is_an_error_not_a_dead_link() -> None:
    with pytest.raises(ValueError, match="kind"):
        notification_link("nowhere", None, platform=PLATFORM, crm=CRM)  # type: ignore[arg-type]


def test_link_base_gives_typed_shortcuts() -> None:
    base = LinkBase(platform=PLATFORM, crm=CRM)
    assert base.lead(7) == f"{PLATFORM}/crm/leads?lead=L-0007&panel=open&tab=card"
    assert base.dashboard() == f"{PLATFORM}/dashboard/summary"
    assert base.integrations() == f"{PLATFORM}/admin/integrations"
    old = LinkBase(platform=None, crm=CRM)
    assert old.lead(7) == f"{CRM}/leads/7"
    assert old.integrations() is None
    assert old.on_platform is False
    assert base.on_platform is True


def test_every_platform_route_exists_in_the_platform_sections() -> None:
    """Маршруты карты — разделы Платформы (`modules/*/module.ts`), а не «не найдено»."""
    import re
    from pathlib import Path

    from app.domain.platform_links import _PLATFORM

    modules = Path(__file__).resolve().parents[5] / "platform" / "web" / "src" / "modules"
    if not modules.is_dir():
        pytest.skip("исходники Платформы недоступны в этом окружении")
    declared = {
        path
        for module in modules.glob("*/module.ts")
        for path in re.findall(r'path: "(/[^"]+)"', module.read_text(encoding="utf-8"))
    }
    for route in _PLATFORM.values():
        assert route.split("?")[0] in declared, route
