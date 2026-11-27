"""Тестовые компании (ТЕСТ-1, DECISIONS 2026-11-27): проекция отметки `is_test` компании ERP.

Владелец — ERP; EDS получает снимок `erp.company.updated` и держит по компании последнее известное значение.
Реестр и список писем скрывают документы тестовых компаний по умолчанию; ничего не удаляется.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CompanyMark(Base):
    __tablename__ = "company_marks"

    erp_company_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    is_test: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # `company.updated_at` из снимка: более старый снимок значение не перезаписывает
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
