"""Типы входящих писем (MAIL-TYPES) на Postgres: справочник, правила, помощник, действия.

IMAP — фейковый сервер; модель — подставная (платных вызовов нет); адреса и тексты вымышленные.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.inbound_mail import InboundMail
from app.models.mail_types import MailType
from app.services.inbound_mail import InboundMailService
from app.services.inbound_mail_assist import InboundMailAssist
from tests.fake_imap import FakeImapServer
from tests.integration.test_inbound_mail import (
    BUCKET,
    SECRETS_KEY,
    FakeModel,
    Stand,
    _one_mail,
    _staff,
)

pytestmark = pytest.mark.integration

TAX = "info@soliq.example"


@pytest.fixture
def server() -> Iterator[FakeImapServer]:
    with FakeImapServer() as running:
        yield running


@pytest.fixture
def stand(sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> Stand:
    box = Stand(sessions, server)
    box.trusted = [
        "yandex.ru"
    ]  # админ вписал сервер Яндекса: тест-хост не из известных провайдеров
    return box


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, server: FakeImapServer
) -> Iterator[tuple[TestClient, Stand]]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        stand = Stand(sessions, server, container.settings_service)
        container.__dict__["inbound_mail"] = InboundMailService(
            sessions,
            container.settings_service,
            container.mail_service,
            stand.storage,
            BUCKET,
            container.imap_connector.configured,
        )
        yield test_client, stand


async def _types(stand: Stand) -> dict[str, MailType]:
    async with stand.sessions() as session:
        return {t.code: t for t in (await session.scalars(select(MailType))).all()}


async def _row(stand: Stand, mail_id: int) -> InboundMail:
    async with stand.sessions() as session:
        row = await session.get(InboundMail, mail_id)
    assert row is not None
    return row


async def _role_ids(stand: Stand, *codes: str) -> tuple[int, ...]:
    from app.models.platform_roles import PlatformRole

    async with stand.sessions() as session:
        rows = (
            await session.scalars(select(PlatformRole).where(PlatformRole.code.in_(codes)))
        ).all()
    return tuple(r.id for r in rows)


async def _person(stand: Stand, email: str, *codes: str) -> Any:
    """Сотрудник с ролями Платформы (права — по объединению всех его ролей)."""
    from app.security.principal import Principal
    from tests.integration.crm_helpers import make_user

    account, _ = await make_user(stand.sessions, email, ["viewer"])
    return Principal(
        account.id, email, ("viewer",), platform_role_ids=await _role_ids(stand, *codes)
    )


async def _supplier(stand: Stand) -> Any:
    """Снабженец и делопроизводитель в одном лице: может загрузить прайс и разобрать почту."""
    return await _person(stand, "supply-clerk@railtech.uz", "tpl:SUPPLY", "tpl:REGISTRAR")


async def _hide(stand: Stand, code: str) -> None:
    async with stand.sessions() as session, session.begin():
        await session.execute(update(MailType).where(MailType.code == code).values(active=False))


# --- стартовый набор -------------------------------------------------------------------------


async def test_seed_has_nine_types_with_closed_actions(stand: Stand) -> None:
    types = await _types(stand)
    assert set(types) == {
        "client_request",
        "cooperation",
        "meeting",
        "supplier_price",
        "supplier_invoice",
        "supplier_document",
        "official",
        "mailing",
        "spam",
    }
    assert {t.code: t.default_action for t in types.values()} == {
        "client_request": "create_lead",
        "cooperation": "register_incoming",
        "meeting": "reply_template",
        "supplier_price": "supplier_price",
        "supplier_invoice": "to_accountant",
        "supplier_document": "register_incoming",
        "official": "register_incoming",
        "mailing": "archive_mailing",
        "spam": "suspicious",
    }
    assert all(t.active and t.name_uz and t.name_en for t in types.values())


# --- классификация берёт типы из справочника -------------------------------------------------


async def test_assist_prompt_lists_only_active_types_from_the_dictionary(stand: Stand) -> None:
    await _hide(stand, "mailing")
    mail_id = await _one_mail(stand)
    model = FakeModel('{"type": "mailing", "summary": "Реклама шпал"}')
    out = await InboundMailAssist(stand.sessions, stand.settings, model).suggest(
        await stand.principal(), mail_id
    )
    prompt = model.prompts[0]
    block = prompt.rsplit("<types>", 1)[1].split("</types>")[0]
    assert "`client_request`" in block
    assert "`mailing`" not in block, "отключённый тип модели не предлагается"
    assert "Рассылка" not in block
    # модель всё равно назвала отключённый тип: письмо без типа, суть сохранена
    row = await _row(stand, mail_id)
    assert (out.status, out.summary) == ("done", "Реклама шпал")
    assert (row.type_code, row.type_source, row.assist_action) == (None, None, None)


async def test_assist_type_is_taken_from_renamed_dictionary_value(stand: Stand) -> None:
    async with stand.sessions() as session, session.begin():
        await session.execute(
            update(MailType)
            .where(MailType.code == "client_request")
            .values(name_ru="Заказ покупателя", default_action="supplier_price")
        )
    mail_id = await _one_mail(stand)
    model = FakeModel('{"type": "Заказ покупателя", "summary": "Хотят шпалы"}')
    await InboundMailAssist(stand.sessions, stand.settings, model).suggest(
        await stand.principal(), mail_id
    )
    row = await _row(stand, mail_id)
    assert (row.type_code, row.type_source) == ("client_request", "ai")
    assert row.assist_action == "supplier_price", "действие — из данных справочника, не из кода"


# --- правило отправителя побеждает ИИ --------------------------------------------------------


async def _add_rule(stand: Stand, pattern: str, code: str, mail_id: int | None = None) -> Any:
    from app.schemas.mail_types import MailSenderRuleIn
    from app.services.mail_types import MailTypesService

    return await MailTypesService(stand.sessions).add_rule(
        await stand.principal(), MailSenderRuleIn(pattern=pattern, type_code=code, mail_id=mail_id)
    )


AUTH_PASS = (
    "mx.yandex.ru; spf=pass smtp.mailfrom={d}; dkim=pass header.i=@{d}; dmarc=pass header.from={d}"
)


def _signed(n: int, sender: str, auth: str | None = "pass", **kw: Any) -> bytes:
    """Письмо с заголовком `Authentication-Results`, который поставил наш MX (`pass`), или без него.

    `fail` — SPF/DKIM/DMARC не прошли (подделанный `From`)."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = f"Отправитель {n} <{sender}>"
    msg["To"] = "info@company.test"
    msg["Subject"] = f"Письмо {n}"
    msg["Message-ID"] = f"<signed-{n}@example.test>"
    domain = sender.rpartition("@")[2]
    if auth == "pass":
        msg["Authentication-Results"] = AUTH_PASS.format(d=domain)
    elif auth == "foreign":  # заголовок, который написал сам отправитель, с чужим authserv-id
        msg["Authentication-Results"] = f"attacker.example; dmarc=pass header.from={domain}"
    elif auth == "google":  # подделка «от Google» в письме на ящике не у Google
        msg["Authentication-Results"] = f"mx.google.com; dmarc=pass header.from={domain}"
    elif auth == "fail":
        msg["Authentication-Results"] = (
            f"mx.yandex.ru; spf=fail smtp.mailfrom={domain}; dkim=none; "
            f"dmarc=fail header.from={domain}"
        )
    msg.set_content("Текст письма.")
    return msg.as_bytes().replace(b"\n", b"\r\n")


async def test_domain_rule_sets_type_only_for_a_verified_sender_and_beats_the_model(
    stand: Stand,
) -> None:
    await _add_rule(stand, "*@soliq.example", "official")
    await stand.configure()
    stand.server.box.add(1, _signed(1, TAX))
    stand.server.box.add(2, _signed(2, "shop@other.example"))
    stand.server.box.add(3, _signed(3, "fake@soliq.example", "fail"))  # подделанный From
    stand.server.box.add(4, _signed(4, "nohdr@soliq.example", None))  # проверить нельзя
    await stand.ingest.poll()
    first, second, forged, unknown = await stand.mails()
    assert (first.type_code, first.type_source, first.sender_auth) == (
        "official",
        "rule",
        "verified",
    )
    assert (second.type_code, second.type_source) == (None, None)
    assert (forged.type_code, forged.sender_auth, forged.rule_skipped) == (None, "unverified", True)
    assert (unknown.type_code, unknown.sender_auth, unknown.rule_skipped) == (None, "unknown", True)
    card = await stand.service().get(await stand.clerk(), forged.id)
    assert card.sender_check == "unverified"
    assert (await stand.service().get(await stand.clerk(), unknown.id)).sender_check == "unknown"
    assert (await stand.service().get(await stand.clerk(), first.id)).sender_check is None

    model = FakeModel('{"type": "client_request", "summary": "Просят КП"}')
    assist = InboundMailAssist(stand.sessions, stand.settings, model)
    await assist.suggest(await stand.principal(), first.id)
    await assist.suggest(await stand.principal(), second.id)
    first, second = await _row(stand, first.id), await _row(stand, second.id)
    assert (first.type_code, first.type_source) == ("official", "rule"), "правило сильнее ИИ"
    assert first.assist_action == "create_lead", "что сказал ИИ — в подсказке, но тип прежний"
    assert (second.type_code, second.type_source) == ("client_request", "ai")


async def test_foreign_authserv_id_is_not_believed_unless_the_admin_trusts_it(stand: Stand) -> None:
    await _add_rule(stand, "soliq.example", "official")
    await stand.configure()
    stand.server.box.add(1, _signed(1, "a@soliq.example", "foreign"))
    await stand.ingest.poll()
    (first,) = await stand.mails()
    assert (first.type_code, first.sender_auth, first.rule_skipped) == (None, "unknown", True)

    # админ внёс свой сервер в «Доверенные серверы» («Почта»): его заголовку верим
    current = (await stand.settings.get()).integrations.model_dump(mode="json")
    current["imap"]["trusted_auth_servers"] = ["attacker.example"]
    await stand.settings.update("integrations", current, None)
    stand.server.box.add(2, _signed(2, "b@soliq.example", "foreign"))
    await stand.ingest.poll()
    second = (await stand.mails())[1]
    assert (second.type_code, second.sender_auth) == ("official", "verified")


async def test_exact_address_rule_is_verified_too(stand: Stand) -> None:
    await _add_rule(stand, "boss@soliq.example", "official")
    await stand.configure()
    stand.server.box.add(1, _signed(1, "boss@soliq.example"))
    stand.server.box.add(2, _signed(2, "boss@soliq.example", "fail"))
    stand.server.box.add(3, _signed(3, "xboss@soliq.example"))  # другой адрес — не подходит
    await stand.ingest.poll()
    ok, forged, other = await stand.mails()
    assert [m.type_code for m in (ok, forged, other)] == ["official", None, None]
    assert (forged.rule_skipped, other.rule_skipped) == (True, False)


async def test_rule_of_hidden_type_is_silent(stand: Stand) -> None:
    await _add_rule(stand, "soliq.example", "official")
    await _hide(stand, "official")
    await stand.configure()
    stand.server.box.add(1, _signed(1, TAX))
    await stand.ingest.poll()
    (mail,) = await stand.mails()
    assert mail.type_code is None


async def test_rule_from_card_types_this_mail_and_open_verified_new_ones(stand: Stand) -> None:
    await stand.configure()
    stand.server.box.add(1, _signed(1, "u1@soliq.example"))
    stand.server.box.add(2, _signed(2, "u2@soliq.example"))
    stand.server.box.add(3, _signed(3, "u3@soliq.example"))
    stand.server.box.add(4, _signed(4, "other@elsewhere.example"))
    stand.server.box.add(5, _signed(5, "x@evil-soliq.example"))  # чужой домен с тем же окончанием
    stand.server.box.add(6, _signed(6, "u6@soliq.example", "fail"))  # подделка
    await stand.ingest.poll()
    one, two, three, four, evil, forged = await stand.mails()
    who = await stand.principal()
    # третье письмо человек уже разметил сам — правило его не трогает
    await stand.actions().set_type(who, three.id, "cooperation")

    out = await _add_rule(stand, "@Soliq.Example", "official", mail_id=one.id)

    assert (out.pattern, out.applied) == ("soliq.example", 2)
    types = {m.id: (m.type_code, m.type_source) for m in await stand.mails()}
    assert types[one.id] == ("official", "rule")
    assert types[two.id] == ("official", "rule")
    assert types[three.id] == ("cooperation", "manual")
    assert types[four.id] == (None, None)
    assert types[evil.id] == (None, None), "evil-soliq.example — не поддомен soliq.example"
    assert types[forged.id] == (None, None), "подделанный From типа по правилу не получает"
    assert (await _row(stand, forged.id)).rule_skipped is True
    assert (await _row(stand, evil.id)).rule_skipped is False


async def test_rule_from_card_checks_the_mail(stand: Stand) -> None:
    from app.domain.errors import ValidationFailedError

    await stand.configure()
    stand.server.box.add(1, _signed(1, "a@soliq.example"))
    stand.server.box.add(2, _signed(2, "b@other.example"))
    await stand.ingest.poll()
    one, two = await stand.mails()
    with pytest.raises(ValidationFailedError):  # письмо не от этого отправителя
        await _add_rule(stand, "soliq.example", "official", mail_id=two.id)
    await stand.service().archive(await stand.principal(), one.id, "рассылка")
    with pytest.raises(ConflictError):  # письмо уже разобрано
        await _add_rule(stand, "soliq.example", "official", mail_id=one.id)
    assert await _rules_count(stand) == 0, "ошибка не оставляет правила"


async def _rules_count(stand: Stand) -> int:
    from app.models.mail_types import MailSenderRule

    async with stand.sessions() as session:
        return len((await session.scalars(select(MailSenderRule))).all())


async def test_public_domain_rule_comes_with_a_warning(stand: Stand) -> None:
    gmail = await _add_rule(stand, "*@gmail.com", "mailing")
    firm = await _add_rule(stand, "firma.example", "mailing")
    assert (gmail.caution, firm.caution) == ("public_domain", None)


async def test_assist_does_not_set_a_type_hidden_in_the_meantime(stand: Stand) -> None:
    """Тип отключили, пока модель отвечала: письмо не получает отключённый тип."""
    mail_id = await _one_mail(stand)

    class HidingModel(FakeModel):
        async def complete(self, messages: Any, **kw: Any) -> Any:
            await _hide(stand, "client_request")
            return await super().complete(messages, **kw)

    model = HidingModel('{"type": "client_request", "summary": "Просят КП"}')
    await InboundMailAssist(stand.sessions, stand.settings, model).suggest(
        await stand.principal(), mail_id
    )
    row = await _row(stand, mail_id)
    assert (row.type_code, row.type_source, row.assist_status) == (None, None, "done")


async def test_rule_validation(stand: Stand) -> None:
    from app.domain.errors import ValidationFailedError

    await _add_rule(stand, "soliq.example", "official")
    with pytest.raises(ConflictError):
        await _add_rule(stand, "*@SOLIQ.example", "spam")
    with pytest.raises(ValidationFailedError):
        await _add_rule(stand, "не адрес", "official")
    with pytest.raises(ValidationFailedError):
        await _add_rule(stand, "x.example", "no_such_type")
    await _hide(stand, "mailing")
    with pytest.raises(ConflictError):
        await _add_rule(stand, "news.example", "mailing")


# --- человек меняет тип — журнал -------------------------------------------------------------


async def test_human_type_change_is_journaled_and_beats_ai_and_rule(stand: Stand) -> None:
    mail_id = await _one_mail(stand, sender=TAX)
    who = await stand.principal()
    await stand.actions().set_type(who, mail_id, "meeting")
    row = await _row(stand, mail_id)
    assert (row.type_code, row.type_source, row.status) == ("meeting", "manual", "new")

    model = FakeModel('{"type": "official", "summary": "Письмо"}')
    await InboundMailAssist(stand.sessions, stand.settings, model).suggest(who, mail_id)
    assert (await _row(stand, mail_id)).type_code == "meeting", "выбор человека ИИ не перебивает"

    await stand.actions().set_type(who, mail_id, None)
    row = await _row(stand, mail_id)
    assert (row.type_code, row.type_source) == (None, None)

    async with stand.sessions() as session:
        entries = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "inbound_mail.type"))
        ).all()
    assert [(e.before, e.after) for e in entries] == [
        ({"type": None}, {"type": "meeting", "type_name": "Приглашение на встречу"}),
        ({"type": "meeting"}, {"type": None, "type_name": "—"}),
    ]
    assert all(e.actor_user_id == who.user_id for e in entries)
    card = await stand.service().get(await stand.clerk(), mail_id)
    assert [(e.action, e.detail) for e in card.journal if e.action == "type"] == [
        ("type", "Приглашение на встречу"),
        ("type", "—"),
    ]


async def test_cannot_pick_hidden_or_unknown_type(stand: Stand) -> None:
    from app.domain.errors import ValidationFailedError

    mail_id = await _one_mail(stand)
    who = await stand.principal()
    await _hide(stand, "spam")
    with pytest.raises(ConflictError):
        await stand.actions().set_type(who, mail_id, "spam")
    with pytest.raises(ValidationFailedError):
        await stand.actions().set_type(who, mail_id, "nope")


# --- оформленные письма не висят во входящих -------------------------------------------------


async def _new_ids(stand: Stand) -> list[int]:
    page = await stand.service().page(await stand.clerk(), "new")
    return [i.id for i in page.items]


async def test_done_actions_remove_mail_from_new_and_counts(stand: Stand) -> None:
    from tests.integration.test_inbound_mail import _raw

    await stand.configure()
    for n in range(1, 5):
        stand.server.box.add(n, _raw(n))
    await stand.ingest.poll()
    ids = [m.id for m in await stand.mails()]
    who = await stand.principal()
    assert await _new_ids(stand) == sorted(ids, reverse=True)

    await stand.service().create_lead(who, ids[0])
    await stand.service().archive(who, ids[1], "рассылка")
    await stand.actions().supplier_price(await _supplier(stand), ids[2], first_line=True)
    await stand.actions().suspicious(who, ids[3])

    assert await _new_ids(stand) == [], "оформленные письма во «Входящих» не висят"
    page = await stand.service().page(await stand.clerk(), "done")
    outcomes = {i.id: i.result.outcome for i in page.items if i.result}
    assert outcomes == {ids[0]: "lead", ids[1]: "archived", ids[2]: "price"}
    assert page.counts.new == 0
    assert page.counts.done == 3
    assert page.counts.spam == 1
    assert (await stand.service().page(await stand.clerk(), "spam")).items[0].id == ids[3]
    assert (await stand.service().page(await stand.clerk(), "all")).total == 3


async def test_supplier_price_closes_mail_with_price_outcome(stand: Stand) -> None:
    mail_id = await _one_mail(stand)
    who = await stand.principal()
    await InboundMailAssist(
        stand.sessions, stand.settings, FakeModel('{"type": "supplier_price", "summary": "Прайс"}')
    ).suggest(who, mail_id)
    supplier = await _supplier(stand)
    await stand.actions().supplier_price(supplier, mail_id, first_line=True)
    row = await _row(stand, mail_id)
    assert (row.status, row.outcome, row.handled_by) == ("done", "price", supplier.user_id)
    with pytest.raises(ConflictError):
        await stand.actions().supplier_price(supplier, mail_id, first_line=True)
    async with stand.sessions() as session:
        decision = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "ai.mail_assist.decision")
            )
        ).one()
    assert decision.after is not None
    assert (decision.after["decision"], decision.after["action"]) == ("accepted", "supplier_price")


async def test_handover_goes_to_a_payment_confirming_colleague_only(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.security.principal import Principal
    from tests.integration.crm_helpers import make_user

    mail_id = await _one_mail(stand)
    who = await stand.principal()
    assert (await stand.actions().handover_targets()).items == []
    with pytest.raises(ConflictError):  # некому передать: ни одна роль не подтверждает оплату
        await stand.actions().handover(who, mail_id, who.user_id)

    account, _ = await make_user(sessions, "acc@railtech.uz", ["viewer"])
    async with sessions() as session, session.begin():
        from app.models.platform_roles import PlatformRole, UserPlatformRole

        role = (
            await session.scalars(select(PlatformRole).where(PlatformRole.code == "tpl:ACCOUNTANT"))
        ).one()
        session.add(UserPlatformRole(user_id=account.id, role_id=role.id))
    targets = (await stand.actions().handover_targets()).items
    assert [t.id for t in targets] == [account.id]

    with pytest.raises(ConflictError):  # коллега без права подтверждать оплату — не адресат
        await stand.actions().handover(who, mail_id, who.user_id)
    await stand.actions().handover(who, mail_id, account.id)

    row = await _row(stand, mail_id)
    assert (row.status, row.assignee_id) == ("in_work", account.id)
    assert await _new_ids(stand) == []
    mine = await stand.service().page(
        __import__("app.services.inbound_mail", fromlist=["MailAccess"]).MailAccess(
            Principal(account.id, "Бухгалтер", ("viewer",)), False
        ),
        "mine",
    )
    assert [i.id for i in mine.items] == [mail_id]


# --- фильтр по типу --------------------------------------------------------------------------


async def test_list_filter_by_type_and_counts_stay(stand: Stand) -> None:
    from tests.integration.test_inbound_mail import _raw

    await stand.configure()
    for n in (1, 2, 3):
        stand.server.box.add(n, _raw(n))
    await stand.ingest.poll()
    a, b, c = [m.id for m in await stand.mails()]
    who = await stand.principal()
    await stand.actions().set_type(who, a, "meeting")
    await stand.actions().set_type(who, b, "meeting")
    await stand.actions().set_type(who, c, "spam")
    clerk = await stand.clerk()
    page = await stand.service().page(clerk, "new", type_code="meeting")
    assert sorted(i.id for i in page.items) == [a, b]
    assert page.total == 2
    assert page.counts.new == 3, "счётчики вкладок не зависят от фильтра типа"
    assert page.items[0].type is not None
    assert (page.items[0].type.code, page.items[0].type.default_action) == (
        "meeting",
        "reply_template",
    )
    assert page.items[0].type.source == "manual"


# --- API: права ------------------------------------------------------------------------------


async def test_api_dictionary_and_rules_are_admin_only_type_change_for_clerk(
    client: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = client
    admin = await _staff(http, sessions, "admin-t@railtech.uz", "ADMIN")
    clerk = await _staff(http, sessions, "clerk-t@railtech.uz", "tpl:REGISTRAR")
    seller = await _staff(http, sessions, "seller-t@railtech.uz", "tpl:MANAGER_ALL")
    dictionary = "/api/v1/dictionaries/mail-types"
    body = {
        "name": {"ru": "Жалоба", "uz": "", "en": "Complaint"},
        "attrs": {"default_action": "create_lead"},
    }

    # читает любой сотрудник, меняет только админ
    for who in (admin, clerk, seller):
        assert http.get(dictionary, headers=who).status_code == 200
    assert http.post(dictionary, json=body, headers=clerk).status_code == 403
    created = http.post(dictionary, json=body, headers=admin)
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    assert created.json()["attrs"] == {
        "default_action": "create_lead",
        "color": "default",
        "icon": "mail",
        "letter_kind": None,
    }
    assert http.post(dictionary, json=body, headers=admin).status_code == 409
    bad = {"name": {"ru": "Другое"}, "attrs": {"default_action": "delete_everything"}}
    assert http.post(dictionary, json=bad, headers=admin).status_code == 422
    assert (
        http.post(dictionary, json={"name": {"ru": "Без действия"}}, headers=admin).status_code
        == 422
    )
    assert http.get("/api/v1/dictionaries/other-kind", headers=admin).status_code == 404

    rule = {"pattern": "*@soliq.example", "type_code": "official"}
    assert http.post("/api/v1/mail-sender-rules", json=rule, headers=clerk).status_code == 403
    assert http.post("/api/v1/mail-sender-rules", json=rule, headers=admin).status_code == 201
    assert http.post("/api/v1/mail-sender-rules", json=rule, headers=admin).status_code == 409
    assert http.get("/api/v1/mail-sender-rules", headers=seller).status_code == 403
    listed = http.get("/api/v1/mail-sender-rules", headers=clerk).json()["items"]
    assert [(r["pattern"], r["type_code"], r["created_by"] is not None) for r in listed] == [
        ("soliq.example", "official", True)
    ]
    assert (
        http.delete(f"/api/v1/mail-sender-rules/{listed[0]['id']}", headers=clerk).status_code
        == 403
    )
    assert (
        http.delete(f"/api/v1/mail-sender-rules/{listed[0]['id']}", headers=admin).status_code
        == 204
    )

    mail_id = await _one_mail(stand)
    url = f"/api/v1/inbound-mail/{mail_id}/type"
    assert http.put(url, json={"type_code": code}, headers=seller).status_code == 403
    assert http.put(url, json={"type_code": code}, headers=clerk).status_code == 204
    card = http.get(f"/api/v1/inbound-mail/{mail_id}", headers=clerk).json()
    assert (card["type"]["code"], card["type"]["source"]) == (code, "manual")
    assert http.put(url, json={"type_code": "nope"}, headers=clerk).status_code == 422
    listed_mail = http.get("/api/v1/inbound-mail", params={"type": code}, headers=clerk).json()
    assert [i["id"] for i in listed_mail["items"]] == [mail_id]
    assert (
        http.get("/api/v1/inbound-mail", params={"type": "spam"}, headers=clerk).json()["items"]
        == []
    )

    # использованный тип не удаляется, неиспользованный — да
    assert http.delete(f"{dictionary}/{code}", headers=admin).status_code == 409
    assert http.delete(f"{dictionary}/meeting", headers=admin).status_code == 204
    hidden = http.patch(f"{dictionary}/{code}", json={"active": False}, headers=admin)
    assert hidden.status_code == 200
    visible = http.get(dictionary, headers=clerk).json()["items"]
    assert code not in {i["code"] for i in visible}
    assert (
        http.get(dictionary, params={"include_hidden": "true"}, headers=admin).json()["items"][-1][
            "used"
        ]
        is True
    )

    for path, clerk_status in (("price", 403), ("suspicious", 204)):
        other = await _one_mail(stand, 2 if path == "price" else 3)
        forbidden = http.post(f"/api/v1/inbound-mail/{other}/{path}", headers=seller)
        assert forbidden.status_code == 403
        # «прайс загружен» делопроизводителю без права на каталог не закрыть: ничего не загружено
        assert (
            http.post(f"/api/v1/inbound-mail/{other}/{path}", headers=clerk).status_code
            == clerk_status
        )
    targets = http.get("/api/v1/inbound-mail/handover-targets", headers=clerk).json()["items"]
    assert [t["name"] for t in targets] == ["seller-t"], "роль подтверждает оплату — адресат"


async def test_price_handover_goes_to_a_colleague_who_may_load_prices(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.models.platform_roles import PlatformRole, UserPlatformRole
    from tests.integration.crm_helpers import make_user

    mail_id = await _one_mail(stand)
    who = await stand.principal()
    assert (await stand.actions().handover_targets("price")).items == []
    supply, _ = await make_user(sessions, "supply@railtech.uz", ["viewer"])
    engineer, _ = await make_user(sessions, "engineer2@railtech.uz", ["viewer"])
    async with sessions() as session, session.begin():
        roles = {
            r.code: r
            for r in (await session.scalars(select(PlatformRole))).all()
            if r.code in ("tpl:SUPPLY", "tpl:ENGINEER")
        }
        session.add(UserPlatformRole(user_id=supply.id, role_id=roles["tpl:SUPPLY"].id))
        # инженер ведёт каталог, но цен поставщиков не видит — прайс поставщика не его
        session.add(UserPlatformRole(user_id=engineer.id, role_id=roles["tpl:ENGINEER"].id))
    price = (await stand.actions().handover_targets("price")).items
    payments = (await stand.actions().handover_targets("payments")).items
    assert [t.id for t in price] == [supply.id]
    assert supply.id not in {t.id for t in payments}
    assert engineer.id not in {t.id for t in price}

    with pytest.raises(ConflictError):  # снабженцу счёт не передать: он не подтверждает оплату
        await stand.actions().handover(who, mail_id, supply.id, "payments")
    await stand.actions().handover(who, mail_id, supply.id, "price")
    row = await _row(stand, mail_id)
    assert (row.status, row.assignee_id) == ("in_work", supply.id)


async def test_price_outcome_can_be_returned_to_new(stand: Stand) -> None:
    mail_id = await _one_mail(stand)
    await stand.actions().supplier_price(await _supplier(stand), mail_id, first_line=True)
    await stand.service().release(await stand.clerk(), mail_id)
    row = await _row(stand, mail_id)
    assert (row.status, row.outcome) == ("new", None)


async def test_letter_kind_is_an_optional_attr_of_a_type(stand: Stand) -> None:
    from app.domain.errors import ValidationFailedError
    from app.schemas.mail_types import DictionaryItemIn, DictionaryItemPatch, LocalizedNameIn
    from app.services.mail_types import MailTypesService

    service = MailTypesService(stand.sessions)
    who = await stand.principal()
    seeded = {t.code: t.letter_kind for t in (await _types(stand)).values()}
    assert (seeded["official"], seeded["supplier_document"], seeded["mailing"]) == (
        "government",
        "supplier",
        None,
    )
    made = await service.create(
        who,
        "mail-types",
        DictionaryItemIn(
            name=LocalizedNameIn(ru="Жалоба"),
            attrs={"default_action": "create_lead", "letter_kind": "counterparty"},
        ),
    )
    assert made.attrs["letter_kind"] == "counterparty"
    cleared = await service.update(
        who, "mail-types", made.code, DictionaryItemPatch(attrs={"letter_kind": None})
    )
    assert cleared.attrs["letter_kind"] is None
    with pytest.raises(ValidationFailedError):
        await service.update(
            who, "mail-types", made.code, DictionaryItemPatch(attrs={"letter_kind": "Bad Kind!"})
        )
    mail_id = await _one_mail(stand)
    await stand.actions().set_type(who, mail_id, "official")
    card = await stand.service().get(await stand.clerk(), mail_id)
    assert card.type is not None
    assert card.type.letter_kind == "government"


async def test_supplier_with_only_the_supply_role_closes_the_mail_handed_to_him(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.domain.errors import ForbiddenError
    from app.models.platform_roles import UserPlatformRole

    mail_id = await _one_mail(stand)
    clerk = await stand.principal()
    supply = await _person(stand, "supply-only@railtech.uz", "tpl:SUPPLY")  # без первой линии
    (supply_role,) = await _role_ids(stand, "tpl:SUPPLY")
    async with sessions() as session, session.begin():
        session.add(UserPlatformRole(user_id=supply.user_id, role_id=supply_role))
    await stand.actions().handover(clerk, mail_id, supply.user_id, "price")

    # делопроизводитель без права на каталог закрыть «прайс загружен» не может: ничего не загружено
    with pytest.raises(ForbiddenError):
        await stand.actions().supplier_price(clerk, mail_id, first_line=True)
    # чужой снабженец (не исполнитель, не первая линия) — тоже нет
    other = await _person(stand, "supply-other@railtech.uz", "tpl:SUPPLY")
    with pytest.raises(ForbiddenError):
        await stand.actions().supplier_price(other, mail_id, first_line=False)

    await stand.actions().supplier_price(supply, mail_id, first_line=False)
    row = await _row(stand, mail_id)
    assert (row.status, row.outcome, row.handled_by) == ("done", "price", supply.user_id)


async def test_price_right_is_the_union_of_all_roles_of_a_person(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.models.platform_roles import PlatformRole, UserPlatformRole

    # инженер: каталог, но цен поставщиков не видит; ещё одна роль даёт «видит цены» без каталога
    async with sessions() as session, session.begin():
        prices = PlatformRole(
            name="Видит цены поставщиков", access={}, restricted_fields=["supplier_prices"]
        )
        session.add(prices)
    engineer = await _person(stand, "eng-prices@railtech.uz", "tpl:ENGINEER")
    assert not await _can(stand, engineer, "price"), "одной роли инженера мало"
    async with sessions() as session:
        extra = (
            await session.scalars(select(PlatformRole).where(PlatformRole.name == prices.name))
        ).one()
    both = type(engineer)(
        engineer.user_id,
        engineer.full_name,
        engineer.roles,
        platform_role_ids=(*engineer.platform_role_ids, extra.id),
    )
    assert await _can(stand, both, "price"), "права двух ролей складываются"
    async with sessions() as session, session.begin():
        (eng_role,) = await _role_ids(stand, "tpl:ENGINEER")
        session.add(UserPlatformRole(user_id=engineer.user_id, role_id=eng_role))
        session.add(UserPlatformRole(user_id=engineer.user_id, role_id=extra.id))
    targets = {t.id for t in (await stand.actions().handover_targets("price")).items}
    assert engineer.user_id in targets, "кандидаты — тоже по объединению ролей"


async def _can(stand: Stand, person: Any, purpose: str) -> bool:
    from app.repositories import mail_types as repo

    async with stand.sessions() as session:
        return await repo.has_capability(session, person.platform_role_ids, purpose)


async def test_accountant_without_the_first_line_closes_the_mail_handed_to_him(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.domain.errors import ForbiddenError
    from app.models.platform_roles import UserPlatformRole

    mail_id = await _one_mail(stand)
    clerk = await stand.principal()
    accountant = await _person(stand, "acc-only@railtech.uz", "tpl:ACCOUNTANT")
    (role,) = await _role_ids(stand, "tpl:ACCOUNTANT")
    async with sessions() as session, session.begin():
        session.add(UserPlatformRole(user_id=accountant.user_id, role_id=role))
    await stand.actions().handover(clerk, mail_id, accountant.user_id, "payments")

    with pytest.raises(ForbiddenError):  # не исполнитель
        await stand.actions().complete(clerk, mail_id)
    await stand.actions().complete(accountant, mail_id)
    row = await _row(stand, mail_id)
    assert (row.status, row.outcome, row.handled_by) == ("done", "handled", accountant.user_id)
    with pytest.raises(ConflictError):  # второй раз — уже обработано
        await stand.actions().complete(accountant, mail_id)
    # ошибочно закрытое письмо первая линия вернёт в «Новые»
    await stand.service().release(await stand.clerk(), mail_id)
    assert (await _row(stand, mail_id)).status == "new"


async def test_complete_is_only_for_a_mail_handed_over_not_one_taken_by_oneself(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """«Готово — убрать из очереди» — для переданного письма; взявший письмо сам разбирает его
    обычными действиями, а не закрывает «просто так»."""
    from app.domain.errors import ForbiddenError
    from app.models.platform_roles import UserPlatformRole

    mail_id = await _one_mail(stand)
    accountant = await _person(stand, "acc-self@railtech.uz", "tpl:ACCOUNTANT")
    (role,) = await _role_ids(stand, "tpl:ACCOUNTANT")
    async with sessions() as session, session.begin():
        session.add(UserPlatformRole(user_id=accountant.user_id, role_id=role))
    await stand.service().take(accountant, mail_id)  # взял сам, не передано
    with pytest.raises(ForbiddenError):
        await stand.actions().complete(accountant, mail_id)
    assert (await _row(stand, mail_id)).status == "in_work"

    # вернул и затем получил письмо передачей — закрывает
    clerk = await stand.principal()
    from app.services.inbound_mail import MailAccess

    await stand.service().release(MailAccess(accountant, False), mail_id)
    await stand.actions().handover(clerk, mail_id, accountant.user_id, "payments")
    await stand.actions().complete(accountant, mail_id)
    assert (await _row(stand, mail_id)).outcome == "handled"


async def test_no_trusted_servers_and_unknown_host_means_nobody_is_believed(stand: Stand) -> None:
    """Сервер компании не ставит Authentication-Results: подделка «от Google» и даже «от Яндекса»
    в самом письме не делает отправителя подтверждённым."""
    stand.trusted = []  # админ ничего не вписал; хост 127.0.0.1 — не провайдер из таблицы
    await _add_rule(stand, "soliq.example", "official")
    await stand.configure()
    stand.server.box.add(1, _signed(1, "a@soliq.example", "google"))
    stand.server.box.add(2, _signed(2, "b@soliq.example"))  # заголовок «от Яндекса»
    await stand.ingest.poll()
    first, second = await stand.mails()
    for mail in (first, second):
        assert (mail.type_code, mail.sender_auth, mail.rule_skipped) == (None, "unknown", True)
