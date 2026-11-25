"""Тестовые помощники ПД-1: заявка с уже подготовленным договором (состояние «шаблон выбран, файл собран»)."""

from django.core.files.base import ContentFile
from parties.models import PartnerContractSource

PDF = b"%PDF-1.4\n% pd1 test contract\n"


def prepare(app, *, source=PartnerContractSource.TEMPLATE, content=PDF, name="contract.pdf"):
    """Как после «Подготовить договор» по шаблону без отступлений: файл на месте, согласования не нужно."""
    app.contract_source = source
    app.contract_file.save(name, ContentFile(content), save=False)
    app.save()
    return app


def with_scan(app, content=PDF):
    """Кандидат согласился и загрузил скан подписанного: подтверждать есть что."""
    from django.utils import timezone

    app.signed_scan.save("signed.pdf", ContentFile(content), save=False)
    app.signed_scan_at = timezone.now()
    app.save()
    return app
