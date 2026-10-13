"""Подпись перерисовывает PDF, и в напечатанном акте видны ПЭП-штампы обеих сторон.

Прогон глазами 2026-08-17: PDF договора рендерился при создании (12:46) и кэшировался,
подписи легли в 13:05, а скачивание отдавало старый файл с ПУСТЫМИ линиями подписи —
хотя шаблон договора умеет штамп «Простая электронная подпись · когда · идентификация».
Акт же не печатал штампы вовсе. Тесты закрепляют: (1) подпись договора/акта ставит
перерисовку в очередь после коммита; (2) шаблон акта печатает штампы выпустившего и принявшего.
"""

from unittest.mock import patch

import pytest
from django.template.loader import render_to_string

from crm.tests.test_act_two_sided import act_world, lookups  # noqa: F401 — мир с актом и обеими сторонами


@pytest.mark.django_db
def test_act_sign_enqueues_pdf_rerender(act_world, django_capture_on_commit_callbacks):  # noqa: F811
    from crm.services.billing import sign_act

    world = act_world
    with patch("crm.tasks.render_document_pdf.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            act, err = sign_act(world["act"].id, world["buyer_user"])
        assert err is None, err
    assert ("act", act.id) in [call.args for call in delay.call_args_list]


@pytest.mark.django_db
def test_act_template_prints_pep_stamps_for_both_sides(act_world, django_capture_on_commit_callbacks):  # noqa: F811
    from crm.services.billing import sign_act

    world = act_world
    with patch("crm.tasks.render_document_pdf.delay"):
        with django_capture_on_commit_callbacks(execute=True):
            act, err = sign_act(world["act"].id, world["buyer_user"])
    assert err is None, err
    act.refresh_from_db()
    html = render_to_string(
        "crm/blocks/_signatures_act.html",
        {"act": act, "seller": None, "seller_profile": None, "company": act.deal.company, "contact": None},
    )
    assert html.count("Простая электронная подпись") == 2, html
    assert act.issuer_signer.email in html and act.acceptor_signer.email in html
