"""«Кто такой продавец» определён в ОДНОМ месте — и остаётся там.

Предыстория (не гипотетическая). Предикат «компания-продавец» был размазан инлайн-фильтрами по
23 местам в 6 приложениях. Пикер получателей считал приглашаемым продавцом «SUPPLIER + пройденный
KYC», а подсказка продавцов (R1) — просто «SUPPLIER». Два места кодировали одно понятие и
разошлись: непроверенная компания попадала в предвыбор БЕЗ видимой строки в пикере — покупатель её
не видит, снять не может, а в маршрутизацию она уходит. Починено в #436, после чего определение
свели в `accounts.models.company`. (KYC-половина предиката удалена в M1-ERP-02 волна 1c —
приглашаемый продавец теперь просто активная компания-продавец.)

Эти тесты держат инвариант: пока предикат один, такое расхождение невыразимо.
"""

import pathlib

import pytest

from accounts.models import Company, CompanyType, seller_company_q
from accounts.models.company.core import active_company_q

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Единственный законный дом предиката (company.py распилен в пакет — #509-волна).
CANONICAL_HOME = BACKEND_ROOT / "accounts" / "models" / "company" / "core.py"

# Инлайн-написания, которые обходят канон.
FORBIDDEN_FRAGMENTS = (
    "types__code__in=SELLER_COMPANY_TYPES",
    "types__code=CompanyTypeCode.SUPPLIER",
)


def _production_sources():
    """Продакшн-модули backend'а: без тестов, миграций и venv."""
    for path in BACKEND_ROOT.rglob("*.py"):
        parts = path.parts
        if any(p in ("migrations", "tests", ".venv", "venv", "node_modules") for p in parts):
            continue
        if path.name.startswith("test_") or path == CANONICAL_HOME:
            continue
        yield path


def test_no_inline_seller_predicate_outside_canonical_home():
    """Никто не пересобирает «это продавец» руками в ORM-фильтре.

    Если тест упал — нужен не новый инлайн-фильтр, а один из готовых способов:
    `Company.objects.sellers()` для выборок по компаниям,
    `CompanyMember.objects.in_seller_company()` (и через `user.memberships.…`) для членств,
    `seller_company_q(prefix)` (+ `active_company_q(prefix)`) — для фильтра по связи.
    """
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {fragment}")
    assert not offenders, "предикат «продавец» продублирован вне accounts/models/company/core.py:\n" + "\n".join(
        offenders
    )


def test_canonical_home_is_importable_and_exported():
    """Публичный API доступен из `accounts.models` — иначе им не будут пользоваться."""
    import accounts.models as models_pkg

    for name in ("seller_company_q", "CompanyQuerySet", "CompanyMemberQuerySet"):
        assert name in models_pkg.__all__, f"{name} не экспортирован из accounts.models"


@pytest.mark.django_db
def test_sellers_are_active_seller_companies():
    """Подбор продавцов — рабочая поверхность: архивный продавец и покупатель в неё не попадают."""
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    client = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]

    def _company(name, inn, company_type, *, is_active=True):
        company = Company.objects.create(name=name, inn=inn, is_active=is_active)
        company.types.add(company_type)
        return company

    active_seller = _company("Продавец", "990000001", supplier)
    archived_seller = _company("Архивный продавец", "990000002", supplier, is_active=False)
    buyer = _company("Покупатель", "990000003", client)

    sellers = set(Company.objects.sellers().values_list("id", flat=True))

    assert active_seller.id in sellers
    assert archived_seller.id not in sellers
    assert buyer.id not in sellers


@pytest.mark.django_db
def test_relation_prefixed_q_matches_the_queryset():
    """Q-фабрика и queryset должны отбирать одно и то же множество компаний.

    Именно здесь пряталось расхождение: подсказка фильтровала товары через `owner_company__…`,
    пикер — напрямую по Company, и половину условия потеряли.
    """
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    for name, inn, is_active in (("Пр-1", "990000011", True), ("Пр-2", "990000012", False)):
        company = Company.objects.create(name=name, inn=inn, is_active=is_active)
        company.types.add(supplier)

    # Пустой префикс = фильтр по самой Company, значит должен совпасть с queryset-методом.
    assert set(
        Company.objects.filter(seller_company_q() & active_company_q()).distinct().values_list("id", flat=True)
    ) == set(Company.objects.sellers().values_list("id", flat=True))
