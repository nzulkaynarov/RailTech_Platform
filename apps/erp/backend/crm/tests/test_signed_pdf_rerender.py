"""Подпись перерисовывает PDF, и в напечатанном акте видны ПЭП-штампы обеих сторон.

Прогон глазами 2026-08-17: PDF договора рендерился при создании (12:46) и кэшировался,
подписи легли в 13:05, а скачивание отдавало старый файл с ПУСТЫМИ линиями подписи —
хотя шаблон договора умеет штамп «Простая электронная подпись · когда · идентификация».
Акт же не печатал штампы вовсе. Тест закрепляет: шаблон акта печатает штампы выпустившего и принявшего
(перерисовка после подписи договора — в test_signed_contract_pdf_rerender.py; приёмка акта клиентом — портал, FIX-22).
"""

import pytest
from django.template.loader import render_to_string

from crm.tests.test_act_two_sided import act_world, lookups  # noqa: F401 — мир с актом и обеими сторонами


@pytest.mark.django_db
def test_act_template_prints_pep_stamps_for_both_sides(act_world):  # noqa: F811
    """Приёмку акта изнутри ERP делать некому (FIX-13, вернёт портал — FIX-22), поэтому титул
    принявшего проставляется напрямую: проверяется шаблон, а не путь подписи."""
    from django.utils import timezone

    from crm.models import ActStatus

    act = act_world["act"]
    act.status = ActStatus.objects.get(code="SIGNED")
    act.acceptor_signer = act_world["buyer_user"]
    act.acceptor_signed_at = timezone.now()
    act.save(update_fields=["status", "acceptor_signer", "acceptor_signed_at"])
    act.refresh_from_db()
    html = render_to_string(
        "crm/blocks/_signatures_act.html",
        {"act": act, "seller": None, "seller_profile": None, "company": act.deal.company, "contact": None},
    )
    assert html.count("Простая электронная подпись") == 2, html
    assert act.issuer_signer.email in html and act.acceptor_signer.email in html
