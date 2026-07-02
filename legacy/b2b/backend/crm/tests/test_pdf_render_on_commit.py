"""F1.6 — PDF rendering moved off the creating transaction.

Document PDFs are no longer rendered synchronously inside the create transaction
(which orphaned a file on rollback and blocked the request). Creation schedules
`render_document_pdf` via transaction.on_commit; downloads render lazily as a
fallback. These tests cover the new wiring (task dispatch + lazy fallback) without
a DB or WeasyPrint — the full create chain is exercised by the golden-path test.
"""

from unittest import mock

from django.test import SimpleTestCase

from crm.models import Act, Contract, Invoice
from crm.tasks import _render_pdf_for, render_document_pdf
from crm.views import billing


class RenderDispatchTest(SimpleTestCase):
    def test_unknown_doc_type_raises(self):
        with self.assertRaises(ValueError):
            _render_pdf_for("nonsense", 1)

    def test_task_delegates_to_dispatch(self):
        with mock.patch("crm.tasks._render_pdf_for") as render:
            result = render_document_pdf.apply(args=["contract", 7]).get()
        render.assert_called_once_with("contract", 7)
        self.assertEqual(result["status"], "rendered")
        self.assertEqual(result["doc_id"], 7)


class LazyStreamFallbackTest(SimpleTestCase):
    def test_renders_on_demand_when_pdf_missing(self):
        # Unsaved instance → pdf_file is empty (falsy). The fallback must render it.
        obj = Contract(id=1)
        with (
            mock.patch("crm.tasks._render_pdf_for") as render,
            mock.patch.object(Contract, "refresh_from_db"),
            mock.patch("crm.views.billing.stream_file_field", return_value="STREAM") as stream,
        ):
            result = billing._stream_or_render_pdf(obj)
        render.assert_called_once_with("contract", 1)  # doc_type derived from model class
        stream.assert_called_once()
        self.assertEqual(result, "STREAM")

    def test_streams_directly_when_pdf_present(self):
        obj = Invoice(id=2)
        obj.pdf_file = "invoices/already.pdf"  # truthy
        with (
            mock.patch("crm.tasks._render_pdf_for") as render,
            mock.patch("crm.views.billing.stream_file_field", return_value="STREAM"),
        ):
            billing._stream_or_render_pdf(obj)
        render.assert_not_called()  # no re-render when the file is ready

    def test_doc_type_map_covers_all_billing_docs(self):
        self.assertEqual(billing._PDF_DOC_TYPE[Contract.__name__], "contract")
        self.assertEqual(billing._PDF_DOC_TYPE[Invoice.__name__], "invoice")
        self.assertEqual(billing._PDF_DOC_TYPE[Act.__name__], "act")
