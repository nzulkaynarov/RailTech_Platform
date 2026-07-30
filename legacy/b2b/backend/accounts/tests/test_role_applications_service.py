"""Заявки на роль: одобрение выдаёт компании ПРАВА на платформе.

Модуль был покрыт на 18%, хотя одобрение заявки добавляет компании `CompanyType` — то есть
делает её продавцом или производителем со всеми вытекающими возможностями. Здесь покрыты
документные гейты (без договора и NDA роль продавца выдавать нельзя), защита от повторного
рассмотрения, обязательность причины отказа и барьеры отказоустойчивости.

Отдельно — регресс на баг массового отклонения: оно вызывало одиночное БЕЗ причины, получало
`REASON_REQUIRED` на каждой заявке и возвращало 0. Кнопка «[Emergency] Отклонить» в Unfold
молча не работала.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError

from accounts.models import Company, CompanyMember, CompanyRoleApplication, CompanyType, CustomUser, WorkspaceRole
from accounts.services.applications import (
    BULK_REJECT_REASON,
    approve_role_application,
    bulk_approve_role_applications,
    bulk_reject_role_applications,
    reject_role_application,
)

REVIEWABLE_STATUSES = ["PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"]


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})[0]
    manufacturer = CompanyType.objects.get_or_create(
        code="MANUFACTURER", defaults={"name": "Производитель", "sort_order": 30}
    )[0]
    company = Company.objects.create(name="Заявитель", inn="7000000007")
    owner = CustomUser.objects.create_user(email="owner@apps.test", username="apps_owner", password="pw")
    CompanyMember.objects.create(
        user=owner,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    reviewer = CustomUser.objects.create_user(email="reviewer@apps.test", username="apps_reviewer", password="pw")
    return {
        "company": company,
        "owner": owner,
        "reviewer": reviewer,
        "supplier": supplier,
        "manufacturer": manufacturer,
    }


def _upload(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def _application(world, requested_type=None, status="PENDING", with_docs=False):
    requested_type = requested_type or world["supplier"]
    application = CompanyRoleApplication(
        company=world["company"], requested_type=requested_type, status=status, submitted_by=world["owner"]
    )
    if with_docs:
        if requested_type.code == "SUPPLIER":
            application.contract_file = _upload("contract.pdf")
            application.nda_file = _upload("nda.pdf")
        else:
            application.partnership_agreement = _upload("partnership.pdf")
    application.save()
    return application


# ── Документные гейты: роль не выдаётся без бумаг ─────────────────────────────


@pytest.mark.django_db
class TestApprovalDocumentGates:
    def test_supplier_needs_contract_and_nda(self, world):
        """Без обоих документов роль продавца выдавать нельзя."""
        application = _application(world)
        result, error = approve_role_application(application, world["reviewer"])
        assert result is None
        assert error == "ROLE_APPLICATION_MISSING_CONTRACT_NDA"
        assert world["supplier"] not in world["company"].types.all()

    def test_supplier_with_only_contract_is_rejected(self, world):
        """Один из двух документов — тоже недостаточно."""
        application = _application(world)
        application.contract_file = _upload("contract.pdf")
        application.save()
        result, error = approve_role_application(application, world["reviewer"])
        assert result is None
        assert error == "ROLE_APPLICATION_MISSING_CONTRACT_NDA"

    def test_manufacturer_needs_partnership_agreement(self, world):
        application = _application(world, requested_type=world["manufacturer"])
        result, error = approve_role_application(application, world["reviewer"])
        assert result is None
        assert error == "ROLE_APPLICATION_MISSING_PARTNERSHIP"

    def test_manufacturer_ignores_supplier_documents(self, world):
        """Договор и NDA не заменяют партнёрское соглашение — гейты не взаимозаменяемы."""
        application = _application(world, requested_type=world["manufacturer"])
        application.contract_file = _upload("contract.pdf")
        application.nda_file = _upload("nda.pdf")
        application.save()
        result, error = approve_role_application(application, world["reviewer"])
        assert result is None
        assert error == "ROLE_APPLICATION_MISSING_PARTNERSHIP"


# ── Одобрение: что именно происходит с компанией ──────────────────────────────


@pytest.mark.django_db
class TestApproval:
    def test_approval_grants_the_company_type(self, world):
        """Суть операции: компания получает роль на платформе."""
        application = _application(world, with_docs=True)
        result, error = approve_role_application(application, world["reviewer"])
        assert error is None
        assert result.status == "APPROVED"
        assert result.reviewed_by == world["reviewer"]
        assert result.reviewed_at is not None
        assert world["supplier"] in world["company"].types.all()

    @pytest.mark.parametrize("status", REVIEWABLE_STATUSES)
    def test_all_reviewable_statuses_can_be_approved(self, world, status):
        application = _application(world, status=status, with_docs=True)
        _result, error = approve_role_application(application, world["reviewer"])
        assert error is None

    @pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
    def test_already_reviewed_cannot_be_approved_again(self, world, status):
        """Защита от повторной выдачи роли по уже закрытой заявке."""
        application = _application(world, status=status, with_docs=True)
        result, error = approve_role_application(application, world["reviewer"])
        assert result is None
        assert error == "ROLE_APPLICATION_CANNOT_APPROVE"

    def test_trial_subscription_is_created_for_supplier(self, world):
        application = _application(world, with_docs=True)
        with patch("accounts.services.applications.ensure_trial_subscription") as ensure:
            approve_role_application(application, world["reviewer"])
        ensure.assert_called_once_with(world["company"])

    def test_subscription_failure_does_not_undo_the_approval(self, world):
        """Барьер отказоустойчивости: сбой БД при выдаче триала не должен отменять роль."""
        application = _application(world, with_docs=True)
        with patch("accounts.services.applications.ensure_trial_subscription", side_effect=DatabaseError("нет связи")):
            result, error = approve_role_application(application, world["reviewer"])
        assert error is None
        assert result.status == "APPROVED"
        assert world["supplier"] in world["company"].types.all()

    def test_email_failure_does_not_undo_the_approval(self, world):
        """Барьер отказоустойчивости: недоступный SMTP не должен откатывать выдачу роли."""
        application = _application(world, with_docs=True)
        with patch("accounts.services.applications._send_role_application_email", side_effect=RuntimeError("SMTP лёг")):
            result, error = approve_role_application(application, world["reviewer"])
        assert error is None
        assert result.status == "APPROVED"


# ── Отказ: причина обязательна, она уходит в аудит ────────────────────────────


@pytest.mark.django_db
class TestRejection:
    def test_reason_is_required(self, world):
        application = _application(world)
        result, error = reject_role_application(application, world["reviewer"], reason="   ")
        assert result is None
        assert error == "REASON_REQUIRED"
        application.refresh_from_db()
        assert application.status == "PENDING"

    def test_rejection_stores_the_reason(self, world):
        application = _application(world)
        result, error = reject_role_application(application, world["reviewer"], reason="Документы не читаются")
        assert error is None
        assert result.status == "REJECTED"
        assert result.review_notes == "Документы не читаются"
        assert result.reviewed_by == world["reviewer"]

    def test_rejection_does_not_need_documents(self, world):
        """Отказать можно и без документов — документные гейты только у одобрения."""
        application = _application(world)
        _result, error = reject_role_application(application, world["reviewer"], reason="Не подходит")
        assert error is None

    def test_rejection_does_not_grant_the_type(self, world):
        application = _application(world)
        reject_role_application(application, world["reviewer"], reason="Отказ")
        assert world["supplier"] not in world["company"].types.all()

    @pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
    def test_already_reviewed_cannot_be_rejected_again(self, world, status):
        application = _application(world, status=status)
        result, error = reject_role_application(application, world["reviewer"], reason="Ещё раз")
        assert result is None
        assert error == "ROLE_APPLICATION_CANNOT_REJECT"

    def test_email_failure_does_not_undo_the_rejection(self, world):
        application = _application(world)
        with patch("accounts.services.applications._send_role_application_email", side_effect=RuntimeError("SMTP лёг")):
            result, error = reject_role_application(application, world["reviewer"], reason="Отказ")
        assert error is None
        assert result.status == "REJECTED"


# ── Массовые действия оператора ───────────────────────────────────────────────


@pytest.mark.django_db
class TestBulkActions:
    def test_bulk_reject_actually_rejects(self, world):
        """РЕГРЕСС. Массовое отклонение вызывало одиночное БЕЗ причины, получало
        `REASON_REQUIRED` на каждой заявке и возвращало 0 — кнопка «[Emergency] Отклонить»
        в Unfold молча не работала, показывая оператору «0 заявок отклонено»."""
        first = _application(world)
        second = _application(world, requested_type=world["manufacturer"])

        rejected, errors = bulk_reject_role_applications(CompanyRoleApplication.objects.all(), world["reviewer"])

        assert rejected == 2
        assert errors == []
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == "REJECTED"
        assert second.status == "REJECTED"

    def test_bulk_reject_writes_a_meaningful_reason(self, world):
        """Причина обязательна для аудита — массовый отказ помечается явно, а не пустой строкой."""
        application = _application(world)
        bulk_reject_role_applications(CompanyRoleApplication.objects.all(), world["reviewer"])
        application.refresh_from_db()
        assert application.review_notes == BULK_REJECT_REASON
        assert application.review_notes.strip()

    def test_bulk_reject_accepts_an_explicit_reason(self, world):
        application = _application(world)
        bulk_reject_role_applications(
            CompanyRoleApplication.objects.all(), world["reviewer"], reason="Дубликаты заявок"
        )
        application.refresh_from_db()
        assert application.review_notes == "Дубликаты заявок"

    def test_bulk_reject_skips_already_reviewed(self, world):
        """Уже закрытые заявки не пересматриваются и в счёт не идут."""
        # На пару (компания, роль) стоит уникальное ограничение, поэтому вторая заявка —
        # на другую роль, а не дубль первой.
        _application(world, status="APPROVED")
        _application(world, requested_type=world["manufacturer"], status="PENDING")
        rejected, errors = bulk_reject_role_applications(CompanyRoleApplication.objects.all(), world["reviewer"])
        assert rejected == 1
        assert errors == [], "пропуск уже закрытой заявки — не ошибка"

    def test_bulk_approve_counts_and_reports_errors(self, world):
        """Одну одобрить можно, вторую — нет: счётчик и список ошибок должны это отражать."""
        _application(world, with_docs=True)
        _application(world, requested_type=world["manufacturer"])  # без партнёрского соглашения

        approved, errors = bulk_approve_role_applications(CompanyRoleApplication.objects.all(), world["reviewer"])
        assert approved == 1
        assert errors == ["ROLE_APPLICATION_MISSING_PARTNERSHIP"]

    def test_bulk_approve_skips_already_reviewed(self, world):
        _application(world, status="APPROVED", with_docs=True)
        approved, errors = bulk_approve_role_applications(CompanyRoleApplication.objects.all(), world["reviewer"])
        assert (approved, errors) == (0, [])


# ── Уведомление заявителя ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestApplicantNotification:
    def test_owner_is_notified_on_approval(self, world):
        application = _application(world, with_docs=True)
        with patch("accounts.services.applications.send_templated_email") as send:
            approve_role_application(application, world["reviewer"])
        assert send.call_count == 1
        assert send.call_args.args[0] == "role_application_approved"
        assert send.call_args.kwargs["to"] == [world["owner"].email]

    def test_owner_is_notified_on_rejection(self, world):
        application = _application(world)
        with patch("accounts.services.applications.send_templated_email") as send:
            reject_role_application(application, world["reviewer"], reason="Отказ")
        assert send.call_args.args[0] == "role_application_rejected"

    def test_company_without_primary_owner_is_not_a_crash(self, world):
        """Нет активного основного участника — уведомлять некого, но операция обязана пройти."""
        CompanyMember.objects.filter(company=world["company"]).update(is_active=False)
        application = _application(world, with_docs=True)
        with patch("accounts.services.applications.send_templated_email") as send:
            _result, error = approve_role_application(application, world["reviewer"])
        assert error is None
        send.assert_not_called()
