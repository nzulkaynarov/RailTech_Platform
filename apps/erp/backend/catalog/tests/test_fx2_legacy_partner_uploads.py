"""FX-2: миграция `0013` убирает у клиентов старые загрузки партнёров (до FX-2 они сразу получали `client_visible=True`)."""

import datetime
import importlib

import pytest
from django.apps import apps
from django.core.files.base import ContentFile
from django.utils import timezone
from parties.models import Company

from catalog.models import Product, TechDocument

pytestmark = pytest.mark.django_db

migration = importlib.import_module("catalog.migrations.0013_fx2_partner_document_review")
AFTER = migration.PARTNER_UPLOADS_SINCE + datetime.timedelta(hours=1)
BEFORE = migration.PARTNER_UPLOADS_SINCE - datetime.timedelta(days=30)


def make(product, *, at, visible=True, uploaded_by=None, source=None, title="doc"):
    doc = TechDocument(
        kind="certificate",
        title=title,
        original_name=f"{title}.pdf",
        product=product,
        client_visible=visible,
        uploaded_by=uploaded_by,
        source_supplier=source,
    )
    doc.file.save(f"{title}.pdf", ContentFile(b"%PDF-1.4"), save=True)
    TechDocument.objects.filter(pk=doc.pk).update(created_at=at)
    return doc


@pytest.fixture
def cards(db):
    partner = Company.objects.create(name="Завод Север", inn="300000111")
    return {
        "partner": partner,
        "partner_card": Product.objects.create(name="Карточка партнёра", source_supplier=partner),
        "own_card": Product.objects.create(name="Наша карточка"),
    }


def state(doc):
    doc.refresh_from_db()
    return doc.review_state, doc.client_visible


def run():
    migration.quarantine_legacy_partner_uploads(apps, None)


def test_old_partner_upload_goes_back_to_review(cards):
    legacy = make(cards["partner_card"], at=AFTER, title="legacy")
    run()
    assert state(legacy) == ("pending", False)


@pytest.mark.parametrize(
    "case",
    ["copy_from_0011", "staff_upload", "own_card", "hidden_already", "new_partner_upload"],
)
def test_other_rows_are_untouched(cards, django_user_model, case):
    staff = django_user_model.objects.create_user(email="s@staff.example", username="s", password="x")
    docs = {
        # копия старого паспорта изделия из 0011: created_at = старый uploaded_at, до K3
        "copy_from_0011": make(cards["partner_card"], at=BEFORE),
        "staff_upload": make(cards["partner_card"], at=AFTER, uploaded_by=staff),
        "own_card": make(cards["own_card"], at=AFTER),
        "hidden_already": make(cards["partner_card"], at=AFTER, visible=False),
        "new_partner_upload": make(cards["partner_card"], at=AFTER, source=cards["partner"]),
    }
    before = state(docs[case])
    run()
    assert state(docs[case]) == before == ("approved", docs[case].client_visible)


def test_reverse_restores_visibility_only_of_quarantined_rows(cards):
    legacy = make(cards["partner_card"], at=AFTER)
    new = make(cards["partner_card"], at=AFTER, source=cards["partner"])
    TechDocument.objects.filter(pk=new.pk).update(review_state="pending", client_visible=False)
    run()
    migration.restore_legacy_partner_uploads(apps, None)
    assert state(legacy) == ("approved", True)
    assert state(new) == ("pending", False)  # документ FX-2 не трогается
    assert timezone.now()
