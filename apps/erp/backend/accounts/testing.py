"""Помощники тестов: сделать компанию «своей» (единственным продавцом ERP) и выдать сотруднику роль.

После FIX-13 «владельца компании-клиента» в ERP нет: правку настроек, профиля документов, команды и
каталога делает только сотрудник своей компании по праву роли. Тесты, которым нужен «владелец», делают
из своей компании продавца и выдают пользователю системную роль «Руководитель».
"""

from accounts.models import CompanyMember, CompanyType
from accounts.services.roles import ensure_default_company_roles


def make_own_company(company):
    """Тип SUPPLIER делает компанию «своей» (`core.tenant.own_company`), если у неё есть участники."""
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})
    company.types.add(supplier)
    return company


def grant_head(user, company):
    """Системная роль «Руководитель» (все права) участнику компании."""
    membership = CompanyMember.objects.get(user=user, company=company)
    membership.company_roles.add(ensure_default_company_roles(company)["HEAD"])
    return membership


def make_cashier(email="cashier@erp.test"):
    """Администратор, фиксирующий оплату изнутри ERP: клиентских аккаунтов, платящих сами, нет (FIX-13)."""
    from accounts.models import CustomUser

    user = CustomUser.objects.filter(email=email).first()
    if user is None:
        user = CustomUser.objects.create_superuser(email=email, username=email, password="x")
    return user
