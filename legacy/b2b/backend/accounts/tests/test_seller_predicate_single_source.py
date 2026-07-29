"""«Кто такой продавец» определён в ОДНОМ месте — и остаётся там.

Предыстория (не гипотетическая). Предикат «компания-продавец» был размазан инлайн-фильтрами по
23 местам в 6 приложениях. Пикер получателей считал приглашаемым продавцом «SUPPLIER + пройденный
KYC», а подсказка продавцов (R1) — просто «SUPPLIER». Два места кодировали одно понятие и
разошлись: непроверенная компания попадала в предвыбор БЕЗ видимой строки в пикере — покупатель её
не видит, снять не может, а в маршрутизацию она уходит. Починено в #436, после чего определение
свели в `accounts.models.company`.

Эти тесты держат инвариант: пока предикат один, такое расхождение невыразимо.
"""

import ast
import pathlib

import pytest

from accounts.models import (
    Company,
    CompanyType,
    VerificationStatus,
    seller_company_q,
    verified_seller_company_q,
)

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Единственный законный дом предиката.
CANONICAL_HOME = BACKEND_ROOT / "accounts" / "models" / "company.py"

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
    `Company.objects.sellers()` / `.verified_sellers()` для выборок по компаниям,
    `CompanyMember.objects.in_seller_company()` (и через `user.memberships.…`) для членств,
    `seller_company_q(prefix)` / `verified_seller_company_q(prefix)` — для фильтра по связи.
    """
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {fragment}")
    assert not offenders, "предикат «продавец» продублирован вне accounts/models/company.py:\n" + "\n".join(offenders)


def test_canonical_home_is_importable_and_exported():
    """Публичный API доступен из `accounts.models` — иначе им не будут пользоваться."""
    import accounts.models as models_pkg

    for name in ("seller_company_q", "verified_seller_company_q", "CompanyQuerySet", "CompanyMemberQuerySet"):
        assert name in models_pkg.__all__, f"{name} не экспортирован из accounts.models"


def test_verified_predicate_is_seller_plus_kyc_not_just_kyc():
    """`verified_*` обязан сужать `sellers`, а не подменять их.

    Разбор AST, а не сравнение строк: важно, что предикат СОБРАН из seller-части, поэтому
    поменять одну половину и забыть другую нельзя.
    """
    tree = ast.parse(CANONICAL_HOME.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "verified_seller_company_q"
    )
    calls = {n.func.id for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "seller_company_q" in calls, "verified_seller_company_q должен строиться на seller_company_q"


@pytest.mark.django_db
def test_verified_sellers_excludes_unverified_seller():
    """Поведенческая проверка того самого бага: непроверенный продавец не считается приглашаемым."""
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    verified = VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})[
        0
    ]
    contracted = VerificationStatus.objects.get_or_create(
        code="L3_CONTRACTED", defaults={"name": "L3", "sort_order": 40}
    )[0]
    unverified = VerificationStatus.objects.get_or_create(
        code="L1_UNVERIFIED", defaults={"name": "L1", "sort_order": 10}
    )[0]

    def _seller(name, inn, status):
        company = Company.objects.create(name=name, inn=inn, verification_status=status)
        company.types.add(supplier)
        return company

    ok_l2 = _seller("Продавец L2", "990000001", verified)
    ok_l3 = _seller("Продавец L3", "990000002", contracted)
    not_ok = _seller("Продавец без KYC", "990000003", unverified)

    sellers = set(Company.objects.sellers().values_list("id", flat=True))
    invitable = set(Company.objects.verified_sellers().values_list("id", flat=True))

    assert {ok_l2.id, ok_l3.id, not_ok.id} <= sellers  # продавцы — все трое
    assert {ok_l2.id, ok_l3.id} <= invitable  # L3 «контрактный» ВЕРНЁЕ L2, он тоже приглашаем
    assert not_ok.id not in invitable  # а вот непроверенный — нет


@pytest.mark.django_db
def test_relation_prefixed_q_matches_the_queryset():
    """Q-фабрика с префиксом и queryset должны отбирать одно и то же множество компаний.

    Именно здесь пряталось расхождение: подсказка фильтровала товары через `owner_company__…`,
    пикер — напрямую по Company, и половину условия потеряли.
    """
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    verified = VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})[
        0
    ]
    unverified = VerificationStatus.objects.get_or_create(
        code="L1_UNVERIFIED", defaults={"name": "L1", "sort_order": 10}
    )[0]
    for name, inn, status in (("Пр-1", "990000011", verified), ("Пр-2", "990000012", unverified)):
        company = Company.objects.create(name=name, inn=inn, verification_status=status)
        company.types.add(supplier)

    # Пустой префикс = фильтр по самой Company, значит должен совпасть с queryset-методами.
    assert set(Company.objects.filter(seller_company_q()).distinct().values_list("id", flat=True)) == set(
        Company.objects.sellers().values_list("id", flat=True)
    )
    assert set(Company.objects.filter(verified_seller_company_q()).distinct().values_list("id", flat=True)) == set(
        Company.objects.verified_sellers().values_list("id", flat=True)
    )
