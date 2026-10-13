"""
Отказ загрузки документа называет причину кодом (находка 89 прогона 20-08).

Замер: оператор выбирает файл с расширением `.pdf`, внутри которого не PDF. Сервер отбивает
загрузку — и отдаёт `{"detail": "[\\"KYC document: file content does not match its '.pdf'
extension (possible spoofing).\\"]"}`, то есть строковое представление СПИСКА Django-ошибок.
Форма ответа проекта — `{"detail": "<CODE>"}`; такую строку витрина не распознаёт и печатает
оператору внутренний код своего HTTP-клиента: два тоста, «Не удалось загрузить документ» и
«ERR_BAD_REQUEST». Единственная полезная информация — почему файл отвергнут — выбрасывалась,
и оператор грузил тот же файл снова.

Эталон Salesforce SF-BLOCKER-NAMED: отказ называет конкретную причину. Сама проверка
magic-bytes при этом работала и работает — файл не сохраняется.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import Company, CustomUser, KYCDocument, SystemRole

PDF_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        email="upload.operator@test.uz",
        username="upload_operator",
        password="Probe1234!",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )


@pytest.fixture
def company(db):
    return Company.objects.create(name="Компания загрузки", inn="908400001")


def _upload(operator, company, filename, content):
    client = APIClient()
    client.force_authenticate(user=operator)
    return client.post(
        f"/api/v1/accounts/companies/{company.pk}/upload-document/",
        {"file": SimpleUploadedFile(filename, content, content_type="application/pdf")},
        format="multipart",
    )


def test_content_mismatch_answers_with_a_code(operator, company):
    """`.pdf`, внутри которого HTML — подмена содержимого."""
    resp = _upload(operator, company, "charter.pdf", b"<html><body>not a pdf</body></html>")

    assert resp.status_code == 400
    assert resp.json() == {"detail": "FILE_CONTENT_MISMATCH"}
    assert not KYCDocument.objects.filter(company=company).exists(), "файл не сохраняется — это и было верно"


def test_a_disallowed_extension_answers_with_its_own_code(operator, company):
    """Два разных отказа — два разных кода: «не тот тип файла» и «содержимое не то» человек
    исправляет по-разному."""
    resp = _upload(operator, company, "script.exe", b"MZ\x90\x00")

    assert resp.status_code == 400
    assert resp.json() == {"detail": "FILE_EXTENSION_NOT_ALLOWED"}


def test_the_detail_is_a_code_not_a_python_list(operator, company):
    """Ровно та форма, которая ломала витрину: `str(ValidationError)` — это `["...текст..."]`."""
    detail = _upload(operator, company, "charter.pdf", b"<html>").json()["detail"]

    assert not detail.startswith("["), detail
    assert detail.replace("_", "").isalpha() and detail.isupper(), f"код, а не фраза: {detail!r}"


def test_a_real_pdf_still_uploads(operator, company):
    """Обратная сторона: годный файл проходит — запрет не превратился в «нельзя ничего»."""
    resp = _upload(operator, company, "charter.pdf", PDF_HEADER + b"1 0 obj\n<<>>\nendobj\n")

    assert resp.status_code == 201, resp.content
    assert KYCDocument.objects.filter(company=company).count() == 1


def test_the_code_matches_the_one_the_import_path_already_uses(operator, company):
    """Код не выдуман: `FILE_CONTENT_MISMATCH` уже канонизирован путём импорта
    (`sourcing/views_imports.py`) и переведён. Два кода на одно событие снова заставили бы
    витрину гадать."""
    import re
    from pathlib import Path

    source = Path("/app/sourcing/views_imports.py").read_text(encoding="utf-8")

    assert re.search(r'"detail":\s*"FILE_CONTENT_MISMATCH"', source), "канон кода переехал — сверить перевод"
