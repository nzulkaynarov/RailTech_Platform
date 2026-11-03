"""Типы входящих писем (MAIL-TYPES): справочник, правила отправителя, действия по типу.

Справочник — ресурс `/api/v1/dictionaries` в той же форме, что у EDS: Платформа собирает справочники
доменов в один экран. Читает любой сотрудник (название и цвет тега не секрет), меняет администратор
— `integrations:write`, как карточку «Почта». Смена типа письма и действия по типу —
`mail_inbox:work` (кто работает с ящиком).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.deps import ContainerDep, PrincipalDep, get_rbac, require
from app.domain.errors import ForbiddenError, PasswordChangeRequiredError
from app.schemas.mail_types import (
    DICTIONARY_KIND,
    Code,
    DictionaryItem,
    DictionaryItemIn,
    DictionaryItemList,
    DictionaryItemPatch,
    DictionaryList,
    DictionaryOrderIn,
    HandoverPurpose,
    InboundMailHandoverIn,
    InboundMailHandoverTargets,
    InboundMailTypeIn,
    MailSenderRuleIn,
    MailSenderRuleList,
    MailSenderRuleOut,
)
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services import mail_types as catalog

router = APIRouter(prefix="/api/v1", tags=["mail-types"])

Admin = Annotated[Principal, Depends(require("integrations", "write"))]
Worker = Annotated[Principal, Depends(require("mail_inbox", "work"))]
Kind = Annotated[str, Path(pattern=DICTIONARY_KIND)]
MailId = Annotated[int, Path(ge=1)]


async def staff(principal: PrincipalDep) -> Principal:
    """Любой сотрудник со своим паролем: справочник нужен и для фильтра списка, и для тега в
    карточке.
    """
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    return principal


Reader = Annotated[Principal, Depends(staff)]


async def rules_reader(
    principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
) -> Principal:
    """Правила видит первая линия (`mail_inbox:read`) и тот, кто читает «Почту» в подключениях
    (`integrations:read`): чужим сотрудникам список адресов отправителей ни к чему."""
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    roles, platform = principal.rbac_roles, principal.platform_role_ids
    if not (
        rbac.allowed(roles, "mail_inbox", "read", platform)
        or rbac.allowed(roles, "integrations", "read", platform)
    ):
        raise ForbiddenError(
            "mail_inbox:read or integrations:read is required", resource="mail_inbox"
        )
    return principal


RulesReader = Annotated[Principal, Depends(rules_reader)]


@router.get("/dictionaries", response_model=DictionaryList)
async def list_dictionaries(_: Reader) -> DictionaryList:
    """Справочники CRM: «Типы входящих писем» (`mail-types`) — поля вида `default_action`,
    `color`, `icon`.
    """
    return catalog.catalog()


@router.get("/dictionaries/{kind}", response_model=DictionaryItemList)
async def list_dictionary_items(
    _: Reader,
    container: ContainerDep,
    kind: Kind,
    include_hidden: Annotated[bool, Query()] = False,
) -> DictionaryItemList:
    """Значения справочника по порядку админа; `include_hidden` — с отключёнными и с признаком
    `used`.
    """
    return await container.mail_types.list_items(kind, include_hidden=include_hidden)


@router.post(
    "/dictionaries/{kind}", response_model=DictionaryItem, status_code=status.HTTP_201_CREATED
)
async def create_dictionary_item(
    who: Admin, container: ContainerDep, kind: Kind, body: DictionaryItemIn
) -> DictionaryItem:
    """Новое значение: код создаёт CRM из названия; `attrs.default_action` обязательно (закрытый
    список).
    """
    return await container.mail_types.create(who, kind, body)


@router.put("/dictionaries/{kind}/order", response_model=DictionaryItemList)
async def reorder_dictionary_items(
    who: Admin, container: ContainerDep, kind: Kind, body: DictionaryOrderIn
) -> DictionaryItemList:
    return await container.mail_types.reorder(who, kind, body.codes)


@router.patch("/dictionaries/{kind}/{code}", response_model=DictionaryItem)
async def update_dictionary_item(
    who: Admin, container: ContainerDep, kind: Kind, code: Code, body: DictionaryItemPatch
) -> DictionaryItem:
    return await container.mail_types.update(who, kind, code, body)


@router.delete(
    "/dictionaries/{kind}/{code}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_dictionary_item(
    who: Admin, container: ContainerDep, kind: Kind, code: Code
) -> Response:
    """Только неиспользованное значение: у писем или правил — 409 `mail_type_in_use` (скройте
    его).
    """
    await container.mail_types.delete(who, kind, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mail-sender-rules", response_model=MailSenderRuleList)
async def list_mail_sender_rules(_: RulesReader, container: ContainerDep) -> MailSenderRuleList:
    """Правила «отправитель или домен → тип» по возрасту."""
    return await container.mail_types.list_rules()


@router.post(
    "/mail-sender-rules", response_model=MailSenderRuleOut, status_code=status.HTTP_201_CREATED
)
async def create_mail_sender_rule(
    who: Admin, container: ContainerDep, body: MailSenderRuleIn
) -> MailSenderRuleOut:
    """Правило применяется к новым письмам до помощника и побеждает его. Письмо `mail_id` и
    открытые «Новые» этого отправителя, где тип не выбирал человек, получают тип сразу. Шаблон
    уже есть — 409 `mail_rule_exists`; тип отключён — 409 `mail_type_inactive`; не адрес и не
    домен — 422.
    """
    return await container.mail_types.add_rule(who, body)


@router.delete(
    "/mail-sender-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_mail_sender_rule(rule_id: MailId, who: Admin, container: ContainerDep) -> Response:
    """Удалить правило: типы у уже полученных писем остаются."""
    await container.mail_types.delete_rule(who, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/inbound-mail/{mail_id}/type", status_code=status.HTTP_204_NO_CONTENT)
async def set_inbound_mail_type(
    mail_id: MailId, body: InboundMailTypeIn, who: Worker, container: ContainerDep
) -> Response:
    """Сменить тип письма одним щелчком (`null` — снять); запись в журнал письма. Правило
    отправителя и помощник этот выбор не перебивают. Отключённый тип выбрать нельзя — 409
    `mail_type_inactive`.
    """
    await container.inbound_mail_actions.set_type(who, mail_id, body.type_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/inbound-mail/{mail_id}/price", status_code=status.HTTP_204_NO_CONTENT)
async def supplier_price_inbound_mail(
    mail_id: MailId,
    principal: PrincipalDep,
    rbac: Annotated[Rbac, Depends(get_rbac)],
    container: ContainerDep,
) -> Response:
    """«Прайс загружен»: письмо «Разобрано» с итогом `price` (прайс человек загрузил в каталоге).

    Закрывает тот, у кого по объединению ролей есть право загружать прайсы (`erp.stock: full` и
    цены поставщиков), и либо ведёт письмо (его передали на загрузку), либо первая линия
    (`mail_inbox:work`). Иначе — 403."""
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    first_line = rbac.allowed(
        principal.rbac_roles, "mail_inbox", "work", principal.platform_role_ids
    )
    await container.inbound_mail_actions.supplier_price(principal, mail_id, first_line=first_line)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/inbound-mail/{mail_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_inbound_mail(mail_id: MailId, who: Reader, container: ContainerDep) -> Response:
    """«Готово — убрать из очереди»: исполнитель переданного письма (счёт — бухгалтер) закрывает:
    итог `handled`. Не исполнитель — 403; письмо не «в работе» — 409 `mail_handled`."""
    await container.inbound_mail_actions.complete(who, mail_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/inbound-mail/handover-targets", response_model=InboundMailHandoverTargets)
async def inbound_mail_handover_targets(
    _: Worker,
    container: ContainerDep,
    purpose: Annotated[HandoverPurpose, Query()] = "payments",
) -> InboundMailHandoverTargets:
    """Кому передать письмо: `payments` — чья роль даёт подтверждать оплату (счёт); `price` — чья
    роль даёт загружать прайсы поставщиков и видеть их цены."""
    return await container.inbound_mail_actions.handover_targets(purpose)


@router.post("/inbound-mail/{mail_id}/handover", status_code=status.HTTP_204_NO_CONTENT)
async def handover_inbound_mail(
    mail_id: MailId, body: InboundMailHandoverIn, who: Worker, container: ContainerDep
) -> Response:
    """«Передать бухгалтеру»: письмо «В работе» у выбранного сотрудника из `handover-targets`;
    ведёт другой — 409 `mail_in_work_by_other`; нет такого коллеги — 409
    `mail_no_handover_target`.
    """
    await container.inbound_mail_actions.handover(who, mail_id, body.user_id, body.purpose)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/inbound-mail/{mail_id}/suspicious", status_code=status.HTTP_204_NO_CONTENT)
async def suspicious_inbound_mail(
    mail_id: MailId, who: Worker, container: ContainerDep
) -> Response:
    """«В „Подозрительные“»: письмо уходит из очереди во вкладку «Подозрительные» («Не спам»
    вернёт его).
    """
    await container.inbound_mail_actions.suspicious(who, mail_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
