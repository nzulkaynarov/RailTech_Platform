"""M7 — Unfold QuoteAdmin must be oversight-only (ADR-0002 / Rule 8).

A platform engineer must never AUTHOR or re-price a company's КП from Django Unfold.
QuoteAdmin (and its QuoteItemInline) are locked to read-only inspection, mirroring the
QuoteItemHistoryAdmin precedent.
"""

from django.contrib.admin.sites import AdminSite

from crm.admin import QuoteAdmin, QuoteItemHistoryAdmin
from crm.admin.inlines import QuoteItemInline
from crm.models import Quote, QuoteItemHistory


def test_crm_admin_imports_clean():
    import crm.admin  # noqa: F401


def test_quote_admin_is_oversight_only():
    quote_admin = QuoteAdmin(Quote, AdminSite())
    assert quote_admin.has_add_permission(request=None) is False
    assert quote_admin.has_change_permission(request=None) is False
    assert quote_admin.has_delete_permission(request=None) is False


def test_quote_admin_financial_fields_are_readonly():
    quote_admin = QuoteAdmin(Quote, AdminSite())
    readonly = set(quote_admin.get_readonly_fields(request=None))
    for field in ("vat_rate", "prepared_by", "tax_country"):
        assert field in readonly, f"{field} must be read-only in oversight-only QuoteAdmin"


def test_quote_admin_no_recalc_save_formset():
    # The recalculating save_formset hook (engineer re-pricing path) must be gone.
    assert "save_formset" not in QuoteAdmin.__dict__


def test_quote_item_inline_is_readonly():
    inline = QuoteItemInline(Quote, AdminSite())
    assert inline.has_add_permission(request=None) is False
    assert inline.has_change_permission(request=None) is False
    assert inline.has_delete_permission(request=None) is False
    # Every line/pricing field is rendered read-only.
    assert set(inline.fields) == set(inline.readonly_fields)


def test_quote_item_history_admin_remains_locked():
    history_admin = QuoteItemHistoryAdmin(QuoteItemHistory, AdminSite())
    assert history_admin.has_add_permission(request=None) is False
    assert history_admin.has_change_permission(request=None) is False
    assert history_admin.has_delete_permission(request=None) is False
