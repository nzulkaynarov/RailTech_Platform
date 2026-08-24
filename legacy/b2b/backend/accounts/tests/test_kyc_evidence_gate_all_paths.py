"""
Гейт «выдать L2+ без доказательств — только с обоснованием» проверяется НА КАЖДОМ ПУТИ.

Находки прогона 20-08 №11/№12: обоснование требовал ОДИН диалог из четырёх (карточка компании
в панели оператора). Меню строки реестра, массовое действие, аварийное действие Unfold и сырой
POST по API вели к тому же сервису и проходили мимо — в журнале оставался пустой reason у
выдачи уровня, который открывает подачу заявок и отправку/экспорт КП.

Поэтому тест на сервис здесь недостаточен: он был бы зелёным и при дыре в трёх путях из
четырёх. Каждый путь пробуется отдельно, своим вызовом.

Слово «ВСЕ» в названии файла обязано быть правдой, поэтому сюда добавлены и пути, которые
сервис вообще не звали (их нашёл скептик уже по готовой волне): мастер компаний Unfold и
форма компании в Unfold писали `verification_status` напрямую, без обоснования и без единой
строки в журнале. Плюс очередь триажа — пятый живой вход оператора.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Company, CustomUser, SystemRole, VerificationStatus


@pytest.fixture
def levels(db):
    for code, name, rank in [
        ("L1_UNVERIFIED", "L1", 10),
        ("PROFILE_SUBMITTED", "Профиль на проверке", 20),
        ("L2_VERIFIED", "KYC подтверждён", 30),
        ("L3_CONTRACTED", "Договор заключён", 40),
    ]:
        VerificationStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": rank})


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        email="kyc.operator@test.uz",
        username="kyc_operator",
        password="Probe1234!",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def bare_company(levels):
    """Компания без единого KYC-документа — ровно тот случай, который политика владельца
    разрешает подтвердить, но требует объяснить."""
    return Company.objects.create(
        name="Без доказательств",
        inn="907000001",
        verification_status=VerificationStatus.objects.get(code="PROFILE_SUBMITTED"),
    )


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _status_of(company):
    company.refresh_from_db()
    return company.verification_status.code


# ── Путь 1: POST verify-kyc (им ходят и меню строки, и карточка компании) ────


def test_api_path_refuses_l2_without_reason(operator, bare_company):
    url = reverse("company-verify-kyc", kwargs={"pk": bare_company.pk})
    resp = _api(operator).post(url, {"status_code": "L2_VERIFIED"}, format="json")

    assert resp.status_code == 400
    assert resp.json() == {"detail": "KYC_REASON_REQUIRED_WITHOUT_EVIDENCE"}
    assert _status_of(bare_company) == "PROFILE_SUBMITTED"
    assert bare_company.is_verified is False


def test_api_path_allows_l2_with_reason(operator, bare_company):
    """Политика владельца сохранена: подтвердить без документов МОЖНО — с объяснением."""
    url = reverse("company-verify-kyc", kwargs={"pk": bare_company.pk})
    resp = _api(operator).post(
        url, {"status_code": "L2_VERIFIED", "reason": "ИНН сверен по реестру ГНК"}, format="json"
    )

    assert resp.status_code == 200
    assert _status_of(bare_company) == "L2_VERIFIED"

    from crm.models import ActivityLog

    entry = ActivityLog.objects.get(entity_type="company", entity_id=bare_company.pk)
    assert entry.reason == "ИНН сверен по реестру ГНК", "обоснование обязано попасть в журнал"


def test_api_path_accepts_comment_as_reason(operator, bare_company):
    """Диалоги отправляют объяснение в поле `comment` — оно и есть обоснование, вью
    сводит его к `reason`. Иначе гейт отбивал бы уже заполненную форму."""
    url = reverse("company-verify-kyc", kwargs={"pk": bare_company.pk})
    resp = _api(operator).post(
        url, {"status_code": "L2_VERIFIED", "comment": "устав придёт после регистрации"}, format="json"
    )

    assert resp.status_code == 200
    assert _status_of(bare_company) == "L2_VERIFIED"


# ── Путь 2: массовое действие реестра ───────────────────────────────────────


def test_bulk_path_reports_instead_of_approving(operator, bare_company, levels):
    documented = Company.objects.create(
        name="С доказательствами",
        inn="907000002",
        verification_status=VerificationStatus.objects.get(code="PROFILE_SUBMITTED"),
    )
    from django.core.files.uploadedfile import SimpleUploadedFile

    from accounts import services as acc_services

    acc_services.upload_kyc_document(
        documented, SimpleUploadedFile("charter.pdf", b"%PDF-1.4 ok", content_type="application/pdf"), "OTHER"
    )

    resp = _api(operator).post(
        reverse("company-bulk-verify-kyc"),
        {"ids": [bare_company.pk, documented.pk], "level": "L2_VERIFIED"},
        format="json",
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == 1
    assert [item["error"] for item in body["skipped"]] == ["KYC_REASON_REQUIRED_WITHOUT_EVIDENCE"]
    assert _status_of(bare_company) == "PROFILE_SUBMITTED"
    assert _status_of(documented) == "L2_VERIFIED"


# ── Путь 3: аварийное действие Unfold ───────────────────────────────────────


def test_unfold_emergency_action_reports_skipped_without_crashing(operator, bare_company, rf):
    """`skipped` — список СЛОВАРЕЙ; строковый join по нему падал в TypeError, то есть
    аварийное действие ломалось ровно тогда, когда ему было что сказать оператору."""
    from django.contrib.messages.storage.fallback import FallbackStorage

    from accounts.admin import CompanyAdmin

    admin_instance = CompanyAdmin(Company, __import__("django.contrib.admin", fromlist=["site"]).site)
    request = rf.post("/admin/accounts/company/")
    request.user = operator
    request.session = {}
    request._messages = FallbackStorage(request)

    admin_instance.verify_kyc(request, Company.objects.filter(pk=bare_company.pk))

    texts = [str(m) for m in request._messages]
    assert any("KYC_REASON_REQUIRED_WITHOUT_EVIDENCE" in text for text in texts)
    assert any("Без доказательств" in text for text in texts)
    assert _status_of(bare_company) == "PROFILE_SUBMITTED"


# ── Равный уровень: действия без изменения не выдают себя за успех ──────────


def test_revoke_on_l1_company_is_refused_not_logged_as_success(operator, levels):
    company = Company.objects.create(
        name="И так в L1",
        inn="907000003",
        verification_status=VerificationStatus.objects.get(code="L1_UNVERIFIED"),
    )
    resp = _api(operator).post(
        reverse("company-verify-kyc", kwargs={"pk": company.pk}),
        {"status_code": "L1_UNVERIFIED", "reason": "жалоба клиента"},
        format="json",
    )

    assert resp.status_code == 400
    assert resp.json() == {"detail": "KYC_LEVEL_UNCHANGED"}

    from crm.models import ActivityLog

    assert not ActivityLog.objects.filter(entity_type="company", entity_id=company.pk).exists()


# ── Пути, которые сервис не звали вовсе ─────────────────────────────────────


def test_wizard_cannot_create_a_company_already_verified(levels, db):
    """Мастер ЗАВОДИТ арендатора, а не верифицирует его.

    До 24-08 в мастере можно было выбрать любой уровень, включая L2_VERIFIED: компания
    рождалась подтверждённой без документов, без причины и без записи в журнале.
    """
    from accounts.wizard import Step3RoleForm

    offered = set(Step3RoleForm().fields["verification_status"].queryset.values_list("code", flat=True))

    assert "L2_VERIFIED" not in offered
    assert "L3_CONTRACTED" not in offered
    assert offered == {"L1_UNVERIFIED", "PROFILE_SUBMITTED"}, "уровни ДО верификации остаются доступны"


def test_unfold_company_form_cannot_write_kyc_level(operator, bare_company):
    """Уровень KYC — бизнес-действие со следом, а не поле формы.

    Обычное «Сохранить» на карточке компании в Unfold ставило L2_VERIFIED мимо сервиса:
    ни обоснования, ни журнала — при том что письмо владельцам всё равно уходило.
    """
    from django.contrib.admin.sites import site

    from accounts.admin import CompanyAdmin
    from accounts.models import Company

    admin_instance = CompanyAdmin(Company, site)

    class _Req:
        user = operator

    readonly = admin_instance.get_readonly_fields(_Req(), obj=bare_company)

    assert "verification_status" in readonly
    assert "is_verified" in readonly, "денормализованный флаг тоже не поле формы"


def test_triage_queue_row_carries_evidence_gaps(operator, bare_company, levels, django_assert_num_queries):
    """Очередь триажа — пятый путь выдачи уровня, и правила у него те же.

    Пробелы считает СЕРВЕР тем же предикатом (у витрины своего нет), а список компаний не
    имеет права превратиться в N+1 из-за этого счёта.
    """
    from accounts.models import Company

    for index in range(4):
        Company.objects.create(
            name=f"Очередь {index}",
            inn=f"90700010{index}",
            verification_status=VerificationStatus.objects.get(code="PROFILE_SUBMITTED"),
        )

    resp = _api(operator).get(reverse("admin-queue"))
    assert resp.status_code == 200

    rows = [row for row in resp.json()["items"] if row["queue_type"] == "kyc_pending"]
    assert rows, "очередь обязана показывать компании на проверке"
    assert all("evidence_gaps" in row for row in rows)
    mine = next(row for row in rows if row["entity_id"] == bare_company.pk)
    assert mine["evidence_gaps"] == ["NO_DOCUMENTS"], "ИНН есть, документов нет"
