"""ШАБЛ-1: шаблон скачивается в Word, правится и загружается обратно; «что изменилось» — до сохранения.

Защиты, без которых тест краснеет (мутационная проверка в PR): круговой обход «скачал и загрузил без правок» (общее
представление блоков), `is_locked` в `apply`, отпечаток `base`, `check_archive` перед разбором, `unknown_placeholders`
в `submit_for_approval`, «проверка ничего не пишет».
"""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from documents.models.documents import DocumentTemplate, DocumentTemplateKind, TemplateApproval

from crm.models import ActivityLog
from crm.services import contract_templates as svc
from crm.services import template_word as word
from crm.tests.projects_world import api, pw  # noqa: F401

pytestmark = pytest.mark.django_db

BODY = (
    "<h1>Договор поставки</h1>"
    "<p>1. Предмет договора: <strong>поставка</strong> товаров для {{counterparty.name}}.</p>"
    "<p>2. Срок и порядок оплаты <em>согласуются</em> в спецификации.</p>"
    "<ul><li>первый пункт</li><li>второй пункт</li></ul>"
    "<ol><li>шаг один</li><li>шаг два</li></ol>"
    "<table><tbody><tr><td>Товар</td><td>Количество</td></tr><tr><td>Болт</td><td>10</td></tr></tbody></table>"
    "{{doc.spec_table}}{{doc.totals}}<p>{{doc.requisites_and_signatures}}</p>"
)
URL = "/api/v1/crm/document-templates/{id}/word/"
DOCX = word.DOCX_MIME


def make(
    pw,  # noqa: F811
    *,
    status=TemplateApproval.DRAFT,
    body=BODY,
    kind="CONTRACT",
    name="Договор с клиентом",
    **extra,
):
    return DocumentTemplate.objects.create(
        company=pw.own,
        name=name,
        kind=DocumentTemplateKind.objects.get(code=kind),
        body_html=body,
        approval_status=status,
        counterparty_kind="client",
        subject="supply",
        is_active=status == TemplateApproval.APPROVED,
        **extra,
    )


def upload(user, template, data: bytes, *, name="t.docx", mode="check", language="ru", base=""):
    url = URL.format(id=template.id) + f"?mode={mode}&language={language}" + (f"&base={base}" if base else "")
    return api(user).post(url, {"file": SimpleUploadedFile(name, data, content_type=DOCX)}, format="multipart")


def download(user, template, language="ru"):
    return api(user).get(URL.format(id=template.id) + f"?language={language}")


def edited(docx: bytes, old: str, new: str) -> bytes:
    from docx import Document

    doc = Document(io.BytesIO(docx))
    hit = False
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)
                hit = True
    assert hit, old
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ── круговой обход ────────────────────────────────────────────────────────────────────────────────────────────────


def test_round_trip_without_edits_says_nothing_changed(pw):  # noqa: F811
    template = make(pw)
    response = download(pw.director, template)
    assert response.status_code == 200
    assert response["Content-Type"] == DOCX
    from urllib.parse import unquote

    assert unquote(response["Content-Disposition"]).endswith("Договор с клиентом, ред. 1 — проект.docx")
    result = upload(pw.director, template, response.content)
    assert result.status_code == 200, result.content
    body = result.json()
    assert body["unchanged"] is True and body["can_apply"] is False
    assert body["changes"]["summary"]["total"] == 0
    assert body["unknown_placeholders"] == []


def test_round_trip_keeps_structure_and_fields(pw):  # noqa: F811
    template = make(pw)
    data = download(pw.director, template).content
    blocks, _ = word.read_upload(data, "a.docx")
    html = word.blocks_to_html(blocks)
    for part in (
        "<h1>Договор поставки</h1>",
        "<strong>поставка</strong>",
        "{{counterparty.name}}",
        "<em>согласуются</em>",
        "<ul><li>первый пункт</li><li>второй пункт</li></ul>",
        "<ol><li>шаг один</li><li>шаг два</li></ol>",
        "<td>Болт</td><td>10</td>",
        "{{doc.requisites_and_signatures}}",
    ):
        assert part in html, part


def test_download_shows_fields_as_labelled_and_blocks_as_own_line(pw):  # noqa: F811
    from docx import Document

    text = "\n".join(p.text for p in Document(io.BytesIO(download(pw.director, make(pw)).content)).paragraphs)
    assert "[Контрагент — название {{counterparty.name}}]" in text
    assert "[Блок: реквизиты и подписи Сторон {{doc.requisites_and_signatures}}]" in text


def test_changed_label_does_not_change_the_field(pw):  # noqa: F811
    template = make(pw)
    data = edited(download(pw.director, template).content, "Контрагент — название", "Покупатель")
    assert upload(pw.director, template, data).json()["unchanged"] is True


def test_edit_is_shown_before_saving_and_nothing_is_saved_by_check(pw):  # noqa: F811
    template = make(pw)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    body = upload(pw.director, template, data).json()
    assert body["unchanged"] is False and body["can_apply"] is True
    item = body["changes"]["items"][0]
    assert item["kind"] == "changed" and item["point"] == "1"
    assert "продажа" in item["theirs"] and "поставка" in item["ours"]
    template.refresh_from_db()
    assert template.body_html == BODY  # проверка ничего не пишет
    assert not ActivityLog.objects.filter(event_code="document_template.word_uploaded").exists()


def test_apply_saves_and_writes_the_journal(pw):  # noqa: F811
    template = make(pw)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    base = upload(pw.director, template, data).json()["base"]
    response = upload(pw.director, template, data, mode="apply", base=base, name="Правки юриста.docx")
    assert response.status_code == 200, response.content
    template.refresh_from_db()
    assert "<strong>продажа</strong>" in template.body_html and "{{counterparty.name}}" in template.body_html
    assert template.placeholders_used and "counterparty.name" in template.placeholders_used
    log = ActivityLog.objects.get(event_code="document_template.word_uploaded")
    assert log.user_id == pw.director.id and log.event_params["file"] == "Правки юриста.docx"
    assert log.event_params["changed"] == 1
    # после принятия тот же файл — «изменений нет»
    assert upload(pw.director, template, data).json()["unchanged"] is True


def test_apply_refuses_when_the_text_changed_after_the_check(pw):  # noqa: F811
    template = make(pw)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    base = upload(pw.director, template, data).json()["base"]
    DocumentTemplate.objects.filter(pk=template.pk).update(body_html=BODY + "<p>3. Ещё.</p>")
    response = upload(pw.director, template, data, mode="apply", base=base)
    assert response.status_code == 409 and response.json()["detail"] == "WORD_BASE_CHANGED"
    template.refresh_from_db()
    assert "продажа" not in template.body_html


# ── языки ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_each_language_has_its_own_text(pw):  # noqa: F811
    template = make(pw, body_html_uz="<p>1. Shartnoma predmeti.</p>")
    uz = download(pw.director, template, "uz")
    from urllib.parse import unquote

    assert "(UZ), ред. 1" in unquote(uz["Content-Disposition"])
    assert upload(pw.director, template, uz.content, language="uz").json()["unchanged"] is True
    data = edited(uz.content, "predmeti", "mavzusi")
    base = upload(pw.director, template, data, language="uz").json()["base"]
    assert upload(pw.director, template, data, language="uz", mode="apply", base=base).status_code == 200
    template.refresh_from_db()
    assert "mavzusi" in template.body_html_uz and template.body_html == BODY and template.body_html_en == ""


def test_empty_language_starts_from_the_russian_text(pw):  # noqa: F811
    template = make(pw)
    data = download(pw.director, template, "en").content
    body = upload(pw.director, template, data, language="en").json()
    assert body["changes"]["summary"]["total"] > 0 and body["changes"]["items"][0]["kind"] == "added"


def test_unknown_language_is_refused(pw):  # noqa: F811
    assert download(pw.director, make(pw), "de").status_code == 400


# ── закреплённый шаблон ───────────────────────────────────────────────────────────────────────────────────────────


def test_approved_template_downloads_but_never_changes(pw):  # noqa: F811
    template = make(pw, status=TemplateApproval.APPROVED)
    response = download(pw.director, template)
    assert response.status_code == 200
    data = edited(response.content, "поставка", "продажа")
    checked = upload(pw.director, template, data).json()
    assert checked["locked"] is True and checked["can_apply"] is False
    applied = upload(pw.director, template, data, mode="apply", base=checked["base"])
    assert applied.status_code == 400 and applied.json()["detail"] == "TEMPLATE_LOCKED"
    template.refresh_from_db()
    assert template.body_html == BODY
    assert not ActivityLog.objects.filter(event_code="document_template.word_uploaded").exists()


def test_new_edition_accepts_the_upload(pw):  # noqa: F811
    template = make(pw, status=TemplateApproval.APPROVED)
    copy, error = svc.new_edition(template, pw.director)
    assert error is None
    data = edited(download(pw.director, copy).content, "поставка", "продажа")
    base = upload(pw.director, copy, data).json()["base"]
    assert upload(pw.director, copy, data, mode="apply", base=base).status_code == 200
    template.refresh_from_db()
    assert "продажа" not in template.body_html  # прежняя редакция не тронута


def test_sample_and_foreign_templates_cannot_be_uploaded(pw):  # noqa: F811
    template = make(pw)
    DocumentTemplate.objects.filter(pk=template.pk).update(company=None, is_sample=True, is_active=True)
    data = download(pw.director, template).content
    assert upload(pw.director, template, data).status_code == 403


def test_role_without_rights_cannot_upload_but_can_download(pw):  # noqa: F811
    template = make(pw)
    assert download(pw.manager, template).status_code == 200
    data = download(pw.director, template).content
    assert upload(pw.manager, template, data).status_code == 403


# ── подстановки ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_unknown_placeholders_are_reported_by_name_and_block_approval(pw):  # noqa: F811
    template = make(pw, body=BODY + "<p>Склад: {{warehouse.name}} и {{deal.sum}}.</p>")
    body = upload(pw.director, template, download(pw.director, template).content).json()
    assert body["unknown_placeholders"] == ["warehouse.name", "deal.sum"]
    response = api(pw.director).post(f"/api/v1/crm/document-templates/{template.id}/submit/")
    assert response.status_code == 400
    assert response.json() == {
        "detail": "TEMPLATE_UNKNOWN_PLACEHOLDERS",
        "unknown_placeholders": ["warehouse.name", "deal.sum"],
    }
    template.refresh_from_db()
    assert template.approval_status == TemplateApproval.DRAFT


def test_unknown_placeholder_in_another_language_blocks_approval_too(pw):  # noqa: F811
    template = make(pw, body_html_en="<p>{{nope.code}}</p>")
    _template, error = svc.submit_for_approval(template, pw.director)
    assert error == "TEMPLATE_UNKNOWN_PLACEHOLDERS"


def test_template_with_known_placeholders_goes_to_approval(pw):  # noqa: F811
    _template, error = svc.submit_for_approval(make(pw), pw.director)
    assert error is None


def test_active_legal_template_cannot_lose_its_blocks_by_upload(pw, grant):  # noqa: F811
    grant(pw.director, "settings.edit")
    template = make(
        pw,
        kind="INVOICE",
        body="<p>x</p><p>{{doc.items_table}}</p><p>{{doc.totals}}</p><p>{{doc.payment_requisites}}</p>",
    )
    DocumentTemplate.objects.filter(pk=template.pk).update(is_active=True)
    template.refresh_from_db()
    data = download(pw.director, template).content
    from docx import Document

    doc = Document(io.BytesIO(data))
    for paragraph in list(doc.paragraphs):
        if "doc.totals" in paragraph.text:
            paragraph._p.getparent().remove(paragraph._p)
    out = io.BytesIO()
    doc.save(out)
    body = upload(pw.director, template, out.getvalue()).json()
    assert [b["code"] for b in body["missing_blocks"]] == ["doc.totals"] and body["can_apply"] is False
    applied = upload(pw.director, template, out.getvalue(), mode="apply", base=body["base"])
    assert applied.status_code == 400 and applied.json()["detail"] == "TEMPLATE_MISSING_REQUIRED_BLOCKS"


# ── враждебные файлы ──────────────────────────────────────────────────────────────────────────────────────────────


def _zip(files: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("a.pdf", b"%PDF-1.4", "WORD_ONLY_DOCX"),
        ("a.docx", b"", "WORD_EMPTY"),
        ("a.docx", b"not a zip at all", "WORD_HOSTILE"),
        ("a.docx", _zip({"x.txt": b"hello"}), "WORD_UNREADABLE"),
        ("a.docx", _zip({"word/document.xml": b"\0" * (80 * 1024 * 1024)}), "WORD_HOSTILE"),  # бомба
        ("a.docx", _zip({f"p{i}.xml": b"x" for i in range(2500)}), "WORD_HOSTILE"),  # слишком много частей
        ("a.docx", b"PK" + b"\0" * (6 * 1024 * 1024), "WORD_TOO_BIG"),
    ],
    ids=["not-docx", "empty", "not-zip", "no-word-part", "zip-bomb", "too-many-parts", "too-big"],
)
def test_hostile_files_are_refused_with_a_code(pw, name, data, code):  # noqa: F811
    template = make(pw)
    for mode in ("check", "apply"):
        response = upload(pw.director, template, data, name=name, mode=mode, base="x")
        assert response.status_code == 400, (mode, response.content)
        assert response.json() == {"detail": code}
    template.refresh_from_db()
    assert template.body_html == BODY


def test_empty_document_is_refused(pw):  # noqa: F811
    from docx import Document

    out = io.BytesIO()
    Document().save(out)
    assert upload(pw.director, make(pw), out.getvalue()).json() == {"detail": "WORD_EMPTY"}


def test_scripts_and_styles_do_not_reach_the_template(pw):  # noqa: F811
    from docx import Document

    doc = Document()
    doc.add_paragraph("1. Обычный пункт <script>alert(1)</script> и <b>тег</b>.")
    out = io.BytesIO()
    doc.save(out)
    html = word.blocks_to_html(word.read_upload(out.getvalue(), "a.docx")[0])
    assert "<script>" not in word.sanitize_template_html(html) and "&lt;script&gt;" in html


def test_download_without_a_file_is_refused(pw):  # noqa: F811
    response = api(pw.director).post(URL.format(id=make(pw).id) + "?mode=check", {}, format="multipart")
    assert response.status_code == 400 and response.json() == {"detail": "WORD_FILE_REQUIRED"}


def test_file_name_rule():
    class T:
        name = 'Договор: "поставка"/2026'
        edition = 3

    assert word.download_name(T, "ru") == "Договор поставка 2026, ред. 3 — проект.docx"
    assert word.download_name(T, "uz", "pdf") == "Договор поставка 2026 (UZ), ред. 3 — проект.pdf"
