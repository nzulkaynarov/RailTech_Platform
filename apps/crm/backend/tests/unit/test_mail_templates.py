"""Шаблоны писем (M3-CRM-08): все плейсхолдеры подставлены, язык сотрудника, откат на русский."""

import re
from pathlib import Path

import pytest
import yaml

from app.domain import smtp as domain
from app.domain.errors import MailTemplateMissingError
from app.services import mail_templates, user_invites
from app.services.mail import MailService

CONTEXT = {
    "full_name": "Азиз Каримов",
    "email": "aziz@railtech.uz",
    "temporary_password": "Tmp-pass-4321",
    "crm_url": "https://crm.example.com",
    "company": "RailTech",
}


@pytest.mark.parametrize("template", ["invite", "password_reset"])
@pytest.mark.parametrize("lang", ["ru", "uz", "en"])
def test_renders_every_language_without_leftover_placeholders(template: str, lang: str) -> None:
    rendered = mail_templates.render(template, lang, **CONTEXT)
    assert rendered.lang == lang
    assert rendered.subject
    assert not re.search(r"\$[a-z_]+", rendered.subject + rendered.body)
    assert CONTEXT["temporary_password"] in rendered.body
    assert f"{CONTEXT['crm_url']}/login" in rendered.body


@pytest.mark.parametrize("lang", [None, "", "de", "UZ", "en-US"])
def test_language_resolution(lang: str | None) -> None:
    code = mail_templates.resolve_language(lang)
    assert code in mail_templates.LANGUAGES
    if lang and lang[:2].lower() in mail_templates.LANGUAGES:
        assert code == lang[:2].lower()
    else:
        assert code == "ru"


def test_missing_dictionary_falls_back_to_russian() -> None:
    """У «test» только русский файл: любой язык → русское письмо, `lang` в журнале — `ru`."""
    rendered = mail_templates.render(
        "test", "en", full_name="Админ", host="smtp.example", from_email="crm@example.com"
    )
    assert rendered.lang == "ru"
    assert "smtp.example" in rendered.body


def test_missing_placeholder_fails_loudly() -> None:
    values = dict(CONTEXT)
    values.pop("temporary_password")
    with pytest.raises(KeyError):
        mail_templates.render("invite", "ru", **values)


def test_unknown_template_is_an_error() -> None:
    with pytest.raises(mail_templates.TemplateMissingError):
        mail_templates.render("marketing", "ru")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" SMTP.Example.COM. ", "smtp.example.com"),
        ("smtp://relay.example", "relay.example"),
        ("relay.example/", "relay.example"),
        ("", ""),
    ],
)
def test_host_normalization(raw: str, expected: str) -> None:
    assert domain.normalize_host(raw) == expected


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("smtp.example.com", True),
        ("localhost", True),
        ("", False),
        ("smtp.example.com:587", False),
        ("https://smtp.example.com", False),
        ("smtp exam.com", False),
        ("a..b", False),
        ("x" * 64 + ".com", False),
    ],
)
def test_host_problem(host: str, ok: bool) -> None:
    assert (domain.host_problem(host) is None) is ok


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("crm@example.com", True),
        ("", False),
        ("crm@", False),
        ("crm example@x.com", False),
        ("crm@@example.com", False),
        ("crm@example", False),
    ],
)
def test_email_problem(address: str, ok: bool) -> None:
    assert (domain.email_problem(address) is None) is ok


def test_sender_header() -> None:
    assert domain.format_sender("crm@example.com", 'Rail "Tech"') == '"Rail Tech" <crm@example.com>'
    assert domain.format_sender("crm@example.com", "  ") == "crm@example.com"


# --- C2A-G-3: шаблоны есть там, где их ищет код, и в образе ---------------------------------------

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parents[2]


def _sent_template_names() -> set[str]:
    """Имена шаблонов, на которые ссылается код: `.send("<имя>", …)` и константы user_invites."""
    names = set(
        re.findall(
            r"\.send\(\s*\"(\w+)\"",
            "".join(path.read_text(encoding="utf-8") for path in (_BACKEND / "app").rglob("*.py")),
        )
    )
    return names | {user_invites.INVITE, user_invites.PASSWORD_RESET}


def test_every_template_used_by_code_is_known() -> None:
    assert _sent_template_names() <= set(mail_templates.TEMPLATES)


@pytest.mark.parametrize("name", mail_templates.TEMPLATES)
def test_template_files_exist_and_render(name: str) -> None:
    """Каждое письмо из `TEMPLATES` есть на диске (минимум русское) и рендерится."""
    assert mail_templates.TEMPLATES_DIR.is_dir()
    assert mail_templates.template_path(name, mail_templates.DEFAULT_LANGUAGE).is_file()
    for lang in mail_templates.LANGUAGES:
        path = mail_templates.template_path(name, lang)
        loaded = mail_templates._load(path)
        values = dict.fromkeys(
            loaded.subject.get_identifiers() + loaded.body.get_identifiers(), "x"
        )
        rendered = mail_templates.render(name, lang, **values)
        assert rendered.subject
        assert rendered.body.strip()


async def test_send_without_templates_dir_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Нет каталога шаблонов (dev-стенд без тома): понятная ошибка, не `LookupError`."""
    monkeypatch.setattr(mail_templates, "TEMPLATES_DIR", tmp_path / "nothing")
    service = MailService(*([None] * 7))  # type: ignore[arg-type]  # до рендера ничего не нужно
    with pytest.raises(MailTemplateMissingError) as caught:
        await service.send("invite", "a@example.com", CONTEXT)
    assert str(tmp_path) not in caught.value.message
    assert "invite" not in caught.value.message


def test_prod_image_copies_templates() -> None:
    """Прод-образ (и backup поверх него) содержит `templates/`; контекст сборки их не исключает."""
    dockerfile = (_BACKEND / "Dockerfile").read_text(encoding="utf-8")
    prod = dockerfile.split("FROM deps AS prod", 1)[1].split("\nFROM ", 1)[0]
    assert re.search(r"^COPY\s+(--chown=\S+\s+)?templates\s+\./templates\s*$", prod, re.MULTILINE)
    ignored = (_BACKEND / ".dockerignore").read_text(encoding="utf-8").split()
    assert not {"templates", "templates/", "**/templates", "*.md"} & set(ignored)


def test_dev_stand_mounts_templates_into_crm_services() -> None:
    """dev-стенд: target dev без шаблонов, поэтому том `/app/templates` нужен сервисам CRM."""
    dev = _REPO / "infra" / "compose" / "dev.yml"
    if not dev.is_file():  # тесты запущены вне репозитория (например, внутри образа)
        pytest.skip("infra/compose/dev.yml is not available")
    services = yaml.safe_load(dev.read_text(encoding="utf-8"))["services"]
    for name in ("crm-api", "crm-worker", "crm-migrate"):
        volumes = services[name]["volumes"]
        assert any(
            str(v).endswith("apps/crm/backend/templates:/app/templates:ro") for v in volumes
        ), name
