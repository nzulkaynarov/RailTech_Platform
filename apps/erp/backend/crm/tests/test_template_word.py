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
    "<p>3. Ответственность сторон определяется законом.</p>"
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


def upload(user, template, data: bytes, *, name="t.docx", mode="check", language="ru", base="", sha=""):
    url = URL.format(id=template.id) + f"?mode={mode}&language={language}" + (f"&base={base}" if base else "")
    sha = sha or (word.file_sha(data) if mode == "apply" else "")
    url += f"&file_sha={sha}" if sha else ""
    return api(user).post(url, {"file": SimpleUploadedFile(name, data, content_type=DOCX)}, format="multipart")


def download(user, template, language="ru"):
    return api(user).get(URL.format(id=template.id) + f"?language={language}")


def untagged(docx: bytes) -> bytes:
    """Файл без метки «откуда» (сделан не нашей выгрузкой): проверка свежести его не касается."""
    from docx import Document

    doc = Document(io.BytesIO(docx))
    doc.core_properties.keywords = ""
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


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
    # файл скачан до принятия, текст с тех пор изменился: старый файл не принимается, свежий — «изменений нет»
    assert upload(pw.director, template, data).json() == {"detail": "WORD_STALE"}
    assert upload(pw.director, template, download(pw.director, template).content).json()["unchanged"] is True


def test_apply_refuses_when_the_text_changed_after_the_check(pw):  # noqa: F811
    template = make(pw)
    data = untagged(edited(download(pw.director, template).content, "поставка", "продажа"))
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


def test_unknown_placeholders_are_named_but_do_not_stop_approval(pw):  # noqa: F811
    template = make(pw, body=BODY + "<p>Склад: {{warehouse.name}} и {{deal.sum}}.</p>")
    body = upload(pw.director, template, download(pw.director, template).content).json()
    assert body["unknown_placeholders"] == ["warehouse.name", "deal.sum"]
    response = api(pw.director).post(f"/api/v1/crm/document-templates/{template.id}/submit/")
    assert response.status_code == 200
    # заметка «исправить» едет вместе с результатом, работа не стоит
    assert response.json()["unknown_placeholders"] == ["warehouse.name", "deal.sum"]
    template.refresh_from_db()
    assert template.approval_status == TemplateApproval.ON_APPROVAL


def test_unknown_placeholder_in_another_language_is_listed(pw):  # noqa: F811
    template = make(pw, body_html_en="<p>{{nope.code}}</p>")
    row = api(pw.director).get("/api/v1/crm/document-templates/contracts/").json()
    assert next(r for r in row if r["id"] == template.id)["unknown_placeholders"] == ["nope.code"]
    _template, error = svc.submit_for_approval(template, pw.director)
    assert error is None


def test_template_with_known_placeholders_goes_to_approval(pw):  # noqa: F811
    template, error = svc.submit_for_approval(make(pw), pw.director)
    assert error is None
    assert word.unknown_placeholders(template.body_html) == []


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


# ── ШАБЛ-1, возврат ревью: поля, правки с записью исправлений, потери, пределы ─────────────────────────────────────


def with_paragraph(src: bytes, needle: str, change) -> bytes:
    """DOCX с правкой абзаца, в тексте которого есть `needle` (change получает python-docx абзац)."""
    from docx import Document

    doc = Document(io.BytesIO(src))
    target = next(p for p in doc.paragraphs if needle in p.text)
    change(target, doc)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def checked(pw, template, data, **kw):  # noqa: F811
    response = upload(pw.director, template, data, **kw)
    assert response.status_code == 200, response.content
    return response.json()


def xml(text: str):
    import re

    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    if "xmlns:w=" not in text:
        text = re.sub(r"^<([\w:]+)", lambda m: f"<{m.group(1)} {nsdecls('w')}", text, count=1)
    return parse_xml(text)


def test_field_with_formatting_inside_the_code_stays_whole(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content

    def retype(p, doc):
        for run in p.runs:
            if "counterparty.name" in run.text:
                run.text = "{{counter"
                second = xml("<w:r><w:rPr><w:i/></w:rPr><w:t>party.</w:t></w:r>")
                run._r.addnext(second)
                second.addnext(xml("<w:r><w:t>name}}</w:t></w:r>"))
                return

    body = checked(pw, template, with_paragraph(src, "1. Предмет", retype))
    assert (
        "{{counterparty.name}}" in body["body_html"]
        and "<em>" not in body["body_html"].split("{{counterparty.name}}")[0][-8:]
    )
    assert body["unknown_placeholders"] == []


@pytest.mark.parametrize(
    "bad,named",
    [
        ("{{counterparty.name}", "{{counterparty.name}"),
        ("{{counterparty name}}", "{{counterparty name}}"),
        ("{{контрагент.имя}}", "{{контрагент.имя}}"),
        ("{{counterparty.nme}}", "counterparty.nme"),
    ],
)
def test_broken_fields_are_named_and_stop_only_the_document(pw, bad, named):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content

    def ruin(p, doc):
        for run in p.runs:
            if "counterparty.name" in run.text:
                run.text = run.text.replace("[Контрагент — название {{counterparty.name}}]", bad)

    body = checked(pw, template, with_paragraph(src, "1. Предмет", ruin))
    assert named in body["unknown_placeholders"]
    # шаблон с таким текстом сохраняется и уходит на утверждение, обрывок назван
    DocumentTemplate.objects.filter(pk=template.pk).update(body_html=body["body_html"])
    template.refresh_from_db()
    assert word.unknown_placeholders(template.body_html) == body["unknown_placeholders"]
    _t, error = svc.submit_for_approval(template, pw.director)
    assert error is None


def test_erased_opening_bracket_leaves_a_named_leftover(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content

    def ruin(p, doc):
        for run in p.runs:
            if "counterparty.name" in run.text:
                run.text = run.text.replace("[Контрагент — название", "Контрагент — название")

    body = checked(pw, template, with_paragraph(src, "1. Предмет", ruin))
    assert body["unknown_placeholders"] == ["Контрагент — название {{counterparty.name}}]"]


def test_tracked_changes_and_content_controls_are_read_not_lost(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content

    def track(p, doc):
        p._p.append(
            xml(
                '<w:ins w:id="1" w:author="Ю" w:date="2026-11-26T00:00:00Z"><w:r><w:t> Вставка юриста.</w:t></w:r></w:ins>'
            )
        )
        p._p.append(
            xml(
                '<w:del w:id="2" w:author="Ю" w:date="2026-11-26T00:00:00Z"><w:r><w:delText> Удалённое.</w:delText></w:r></w:del>'
            )
        )
        p._p.addnext(
            xml(
                "<w:sdt><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>5. Пункт в элементе управления.</w:t></w:r></w:p></w:sdtContent></w:sdt>"
            )
        )
        p._p.append(xml('<w:customXml w:element="x"><w:r><w:t> Дополнение.</w:t></w:r></w:customXml>'))

    body = checked(pw, template, with_paragraph(src, "3. Ответственность", track))
    html = body["body_html"]
    assert "Вставка юриста." in html and "Удалённое" not in html
    assert "5. Пункт в элементе управления." in html and "Дополнение." in html
    assert body["unchanged"] is False and body["can_apply"] is True


def test_moved_clause_is_not_lost(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content

    def move(p, doc):
        text = p.text
        for run in list(p.runs):
            run._r.getparent().remove(run._r)
        p._p.append(
            xml(
                f'<w:moveFrom w:id="5" w:author="Ю" w:date="2026-11-26T00:00:00Z"><w:r><w:t>{text}</w:t></w:r></w:moveFrom>'
            )
        )
        p._p.addprevious(
            xml(
                f'<w:p><w:moveTo w:id="6" w:author="Ю" w:date="2026-11-26T00:00:00Z"><w:r><w:t>{text}</w:t></w:r></w:moveTo></w:p>'
            )
        )

    body = checked(pw, template, with_paragraph(src, "3. Ответственность", move))
    assert body["body_html"].count("3. Ответственность сторон определяется законом.") == 1


def test_nested_table_and_text_box_are_read(pw):  # noqa: F811
    from docx import Document

    template = make(pw)
    src = download(pw.director, template).content
    doc = Document(io.BytesIO(src))
    inner = doc.tables[0].cell(1, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Вложенная строка"
    target = next(p for p in doc.paragraphs if "3. Ответственность" in p.text)
    target._p.append(
        xml(
            '<w:r xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:drawing><wp:inline>'
            '<wp:extent cx="1" cy="1"/><wp:docPr id="9" name="tb"/><a:graphic>'
            '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp><wps:txbx>'
            "<w:txbxContent><w:p><w:r><w:t>Текст в надписи</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>"
            "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )
    )
    out = io.BytesIO()
    doc.save(out)
    body = checked(pw, template, out.getvalue())
    assert "Вложенная строка" in body["body_html"] and "Текст в надписи" in body["body_html"]
    assert {"kind": "images", "count": 1} not in body["dropped"]  # надпись — не рисунок


def test_what_is_dropped_is_named_and_unchanged_needs_nothing_dropped(pw):  # noqa: F811
    from docx.shared import RGBColor

    template = make(pw)
    src = download(pw.director, template).content

    def decorate(p, doc):
        run = p.runs[0]
        run.font.color.rgb = RGBColor(255, 0, 0)
        run.font.name = "Times New Roman"
        from docx.enum.text import WD_COLOR_INDEX

        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        p._p.append(
            xml('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="1"/></w:r>')
        )
        p._p.append(xml('<w:r><w:commentReference w:id="0"/></w:r>'))

    body = checked(pw, template, with_paragraph(src, "3. Ответственность", decorate))
    kinds = {d["kind"] for d in body["dropped"]}
    assert {"colors", "fonts", "highlights", "notes", "comments"} <= kinds
    assert body["unchanged"] is False and body["can_apply"] is False  # текст тот же — применять нечего
    assert body["changes"]["summary"]["total"] == 0


def test_markup_word_cannot_keep_is_listed_and_accepting_is_not_delayed(pw):  # noqa: F811
    rich = BODY.replace(
        "<p>2.",
        '<p>0. См. <a href="https://lex.uz/docs/1">закон</a>.</p><hr /><p><img src="data:image/png;base64,iVBORw0KGgo=" alt="x" /></p>'
        '<table><tbody><tr><td colspan="2">Итого</td></tr></tbody></table><ul><li>а<ul><li>б</li></ul></li></ul><p>2.',
    )
    template = make(pw, body=rich)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    body = checked(pw, template, data)
    kinds = {m["kind"] for m in body["lost_markup"]}
    assert {"links", "rules", "pictures", "merged_cells", "nested_lists"} <= kinds
    done = upload(pw.director, template, data, mode="apply", base=body["base"])
    assert done.status_code == 200
    template.refresh_from_db()
    assert "lex.uz" not in template.body_html and "продажа" in template.body_html
    # прежний текст остаётся в записи журнала
    log = ActivityLog.objects.get(event_code="document_template.word_uploaded")
    assert "lex.uz" in log.event_params["previous"]


def test_a_contract_with_a_broken_field_is_stopped_at_generation_with_a_plain_reason(pw):  # noqa: F811
    from crm.services.contracts import generate_contract_from_quote

    template = make(
        pw, status=TemplateApproval.APPROVED, body=BODY + "<p>Срок: {{deal.unknown_term}} и {{counterparty.name}</p>"
    )
    contract, error = generate_contract_from_quote(pw.quote.id, actor=None, template_id=template.id)
    assert (contract, error) == (None, "CONTRACT_TEMPLATE_UNFILLED")
    missing = ActivityLog.objects.get(event_code="contract.template_unfilled").event_params["missing"]
    assert "deal.unknown_term" in missing and "{{counterparty.name}" in missing


def test_a_file_downloaded_before_someones_edit_is_refused(pw):  # noqa: F811
    template = make(pw)
    old = download(pw.director, template).content
    DocumentTemplate.objects.filter(pk=template.pk).update(body_html=BODY.replace("поставка", "ПОСТАВКА КОЛЛЕГИ"))
    for mode in ("check", "apply"):
        response = upload(pw.director, template, old, mode=mode, base="0" * 16)
        assert response.status_code == 400 and response.json() == {"detail": "WORD_STALE"}


def test_apply_refuses_a_file_other_than_the_checked_one(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content
    first = edited(src, "поставка", "продажа")
    other = edited(src, "поставка", "ПОДМЕНА")
    body = checked(pw, template, first)
    response = upload(pw.director, template, other, mode="apply", base=body["base"], sha=body["file_sha"])
    assert response.status_code == 409 and response.json() == {"detail": "WORD_FILE_CHANGED"}
    assert (
        upload(pw.director, template, first, mode="apply", base=body["base"], sha=body["file_sha"]).status_code == 200
    )


def _big(src: bytes, kind: str, count: int = 10_000) -> bytes:
    """Тело документа из `count` пунктов списка или строк таблицы — собрано XML-ом (python-docx строит такое минутами)."""
    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(src)) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    root = etree.fromstring(files["word/document.xml"])
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = root.find(f"{{{ns}}}body")
    for child in list(body):
        if not child.tag.endswith("sectPr"):
            body.remove(child)
    if kind == "list":
        rows = "".join(
            f'<w:p><w:pPr><w:pStyle w:val="ListNumber"/></w:pPr><w:r><w:t>п{i}</w:t></w:r></w:p>' for i in range(count)
        )
    else:
        rows = (
            "<w:tbl>"
            + "".join(f"<w:tr><w:tc><w:p><w:r><w:t>r{i}</w:t></w:r></w:p></w:tc></w:tr>" for i in range(count))
            + "</w:tbl>"
        )
    fragment = etree.fromstring(f'<w:body xmlns:w="{ns}">{rows}</w:body>')
    for k, child in enumerate(list(fragment)):
        body.insert(k, child)
    files["word/document.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            out.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("kind", ["list", "rows"])
def test_ten_thousand_items_are_refused_fast(pw, kind):  # noqa: F811
    import time

    template = make(pw)
    data = _big(download(pw.director, template).content, kind)
    for mode in ("check", "apply"):
        started = time.monotonic()
        response = upload(pw.director, template, data, mode=mode, base="0" * 16)
        assert response.status_code == 400 and response.json() == {"detail": "WORD_TOO_BIG"}
        assert time.monotonic() - started < 5
    template.refresh_from_db()
    assert template.body_html == BODY


def test_parse_has_a_wall_clock_limit(pw, monkeypatch):  # noqa: F811
    template = make(pw)
    data = download(pw.director, template).content
    monkeypatch.setattr(word, "MAX_PARSE_SECONDS", -1.0)
    assert upload(pw.director, template, data).json() == {"detail": "WORD_TOO_COMPLEX"}


def test_too_costly_comparison_is_a_plain_refusal_and_apply_still_works(pw, monkeypatch):  # noqa: F811
    from crm.services import contract_compare

    template = make(pw)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    base = checked(pw, template, data)["base"]

    def boom(*_args, **_kwargs):
        raise contract_compare.TooBig("slow")

    monkeypatch.setattr(contract_compare, "compare", boom)
    assert upload(pw.director, template, data).json() == {"detail": "WORD_TOO_COMPLEX"}
    # принятие после проверки не падает 500: текст сохранён, число пунктов в журнал не пишется
    assert upload(pw.director, template, data, mode="apply", base=base).status_code == 200


def test_apply_without_the_file_fingerprint_is_refused(pw):  # noqa: F811
    template = make(pw)
    data = edited(download(pw.director, template).content, "поставка", "продажа")
    base = checked(pw, template, data)["base"]
    url = URL.format(id=template.id) + f"?mode=apply&language=ru&base={base}"
    response = api(pw.director).post(url, {"file": SimpleUploadedFile("t.docx", data)}, format="multipart")
    assert response.status_code == 409 and response.json() == {"detail": "WORD_FILE_CHANGED"}


# ── ревью #924, второй круг: длинный абзац, чужой файл ─────────────────────────────────────────────────────────────


def _one_paragraph(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_a_million_character_paragraph_is_refused_fast(pw):  # noqa: F811
    import time

    template = make(pw)
    data = _one_paragraph(" ".join(str(i * 7919) for i in range(200_000)))
    for mode in ("check", "apply"):
        started = time.monotonic()
        response = upload(pw.director, template, data, mode=mode, base="0" * 16)
        assert response.status_code == 400 and response.json() == {"detail": "WORD_TOO_BIG"}
        assert time.monotonic() - started < 2
    template.refresh_from_db()
    assert template.body_html == BODY


def test_a_long_but_allowed_paragraph_is_processed_linearly(pw):  # noqa: F811
    import time

    text = ("слово [ " * 6_000)[:49_000]  # скобки не рвут разбор полей: линейно и с ними
    data = _one_paragraph(text)
    started = time.monotonic()
    blocks, _meta = word.read_upload(data, "a.docx")
    assert time.monotonic() - started < 1
    assert len(word.paragraphs_of(blocks)[0]) > 40_000
    assert checked(pw, make(pw), data)["can_apply"] is True


def test_many_runs_of_one_format_are_joined_linearly():
    import time

    runs = [word.Run("а") for _ in range(100_000)]
    started = time.monotonic()
    assert len(word._squash(runs)[0].text) == 100_000
    assert time.monotonic() - started < 1


def test_a_file_of_another_template_or_language_is_refused(pw):  # noqa: F811
    a = make(pw, body_html_uz="<p>1. Shartnoma.</p>")
    b = make(pw, name="Другой договор")
    ru_of_a = download(pw.director, a).content
    for mode in ("check", "apply"):
        other_language = upload(pw.director, a, ru_of_a, language="uz", mode=mode, base="0" * 16)
        assert other_language.status_code == 400 and other_language.json() == {"detail": "WORD_OTHER_LANGUAGE"}
        other_template = upload(pw.director, b, ru_of_a, mode=mode, base="0" * 16)
        assert other_template.status_code == 400 and other_template.json() == {"detail": "WORD_OTHER_TEMPLATE"}
    a.refresh_from_db()
    assert a.body_html_uz == "<p>1. Shartnoma.</p>"


def test_a_file_without_our_marker_is_accepted_and_marked_as_from_elsewhere(pw):  # noqa: F811
    template = make(pw)
    src = download(pw.director, template).content
    assert checked(pw, template, src)["from_elsewhere"] is False
    assert checked(pw, template, untagged(src))["from_elsewhere"] is True
