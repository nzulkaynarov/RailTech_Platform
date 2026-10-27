"""Чек-лист настройки: порядок и ключи (W13C-F1: шаги Платформы `erp`, `mail`, `first_employee`)."""

from dataclasses import replace

from app.services import setup_checklist as checks

NONE = checks.SetupFacts(
    company_saved=False,
    business_hours_saved=False,
    models_ok=False,
    bot_running=False,
    channel_set=False,
    kb_indexed=False,
    teammate_with_telegram=False,
    lead_message_exists=False,
    erp_connected=False,
    mail_configured=False,
    colleague_exists=False,
)


def test_every_key_has_a_link() -> None:
    keys = [key for key, _ in checks.checklist(NONE)]
    assert keys[-3:] == ["erp", "mail", "first_employee"]
    assert len(set(keys)) == len(keys)
    assert all(checks.LINKS[key] for key in keys)


def test_platform_steps_follow_their_facts() -> None:
    assert not any(done for _, done in checks.checklist(NONE))
    facts = replace(NONE, erp_connected=True, colleague_exists=True)
    state = dict(checks.checklist(facts))
    assert state["erp"] is True
    assert state["mail"] is False
    assert state["first_employee"] is True
    assert state["team"] is False  # коллега без Telegram — отдельный шаг CRM
