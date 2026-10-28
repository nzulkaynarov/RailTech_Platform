"""Мир тестов D2-5: своя компания с сотрудниками по ролям каталога Платформы, клиент и сделка-проект.

Роли (права ERP из `packages/contracts/platform-rbac.yaml`, раздел `eds.projects`): директор и бухгалтер — `full`
(`contract.manage`, `contract.sign`, `fulfillment.act`); менеджер, снабженец — `read` (прав ERP на действия нет);
администратор платформы (`is_superuser`) — всё. `outsider` — участник компании клиента этой сделки (не сотрудник), `stranger` — участник чужой компании.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from integration.tests import world as w
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.constants import ContractStatusCode, DealStageCode, QuoteStatusCode

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
FULL = ("contract.manage", "contract.sign", "fulfillment.act")


def api(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def scan(name="scan.pdf", content=PDF, content_type="application/pdf"):
    """Файл скана: годится и для multipart-загрузки, и для прямого вызова сервиса."""
    return SimpleUploadedFile(name, content, content_type=content_type)


@dataclass
class ProjectWorld:
    own: Company
    client: Company
    deal: object
    quote: object
    director: CustomUser
    accountant: CustomUser
    manager: CustomUser
    supply: CustomUser
    admin: CustomUser
    outsider: CustomUser
    stranger: CustomUser


def _staff(own, email, owner_role):
    user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
    CompanyMember.objects.create(user=user, company=own, role=owner_role, is_active=True, is_primary=True)
    return user


@pytest.fixture
def pw(db, grant):
    owner = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    own = Company.objects.create(name="Своя компания", inn="300000001")
    own.types.add(CompanyType.objects.get(code="SUPPLIER"))
    director = _staff(own, "director@own.test", owner)
    accountant = _staff(own, "accountant@own.test", owner)
    manager = _staff(own, "manager@own.test", owner)
    supply = _staff(own, "supply@own.test", owner)
    grant(director, *FULL)
    grant(accountant, *FULL)
    grant(manager, "deal.manage", "quote.send")  # менеджер: eds.projects read — действий по договору и акту нет
    grant(supply, "quote.build")
    admin = CustomUser.objects.create_superuser(email="admin@own.test", username="admin@own.test", password="x")
    client = w.make_company("ООО Клиент", crm_client_id=9001)
    outsider = CustomUser.objects.create_user(email="out@client.test", username="out@client.test", password="x")
    CompanyMember.objects.create(user=outsider, company=client, role=owner, is_active=True, is_primary=True)
    other = w.make_company("ООО Чужой", crm_client_id=9002)
    stranger = CustomUser.objects.create_user(email="str@other.test", username="str@other.test", password="x")
    CompanyMember.objects.create(user=stranger, company=other, role=owner, is_active=True, is_primary=True)
    deal = w.make_deal(client, DealStageCode.CONTRACT_SIGNED, title="Поставка рельсов")
    deal.manager = manager
    deal.save(update_fields=["manager"])
    quote = w.add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    return ProjectWorld(own, client, deal, quote, director, accountant, manager, supply, admin, outsider, stranger)


def contract_in(pw, status=ContractStatusCode.PENDING_CLIENT, **fields):
    """Договор проекта в нужном статусе ERP."""
    return w.add_contract(pw.deal, pw.quote, status, **fields)
