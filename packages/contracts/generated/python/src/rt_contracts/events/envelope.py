# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts).

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, constr


class Envelope(BaseModel):
    """
    CloudEvents 1.0, structured mode, JSON (ADR-0014; docs/CONTRACTS.md, раздел «Шина rt_bus»). Поле data проверяется отдельно схемой своего типа: uz.railtech.<домен>.<сущность>.<действие>.v<N> ↔ events/<домен>/<сущность>.<действие>.v<N>.json; dataschema — rt://contracts/events/<домен>/<сущность>.<действие>/v<N>. Отправитель строгий: заполняет все обязательные атрибуты по этой схеме. Читатель терпимый: неизвестные атрибуты-расширения CloudEvents (имена [a-z0-9]{1,20}) допускаются и игнорируются.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    __annotations__ = {
        "__pydantic_extra__": dict[
            constr(pattern=r"^[a-z0-9]{1,20}$"), str | bool | int
        ],
    }
    specversion: Literal["1.0"]
    """
    Версия CloudEvents
    """
    id: UUID
    """
    Идентификатор события (UUID); ключ дедупликации inbox и заголовок X-RT-Event-Id
    """
    source: Annotated[str, Field(pattern="^rt://[a-z][a-z0-9-]{0,62}$")]
    """
    Издатель: rt://crm, rt://erp, rt://eds, rt://platform-bff; коннекторы — rt://connector-<имя>. События домена identity v1 публикует CRM (rt://crm, ADR-0015)
    """
    type: Annotated[
        str,
        Field(
            pattern="^uz\\.railtech\\.(crm|erp|eds|identity|platform)\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*\\.v[1-9][0-9]*$"
        ),
    ]
    """
    uz.railtech.<домен>.<сущность>.<действие>.v<N>; сущность и действие — по одному сегменту snake_case
    """
    time: AwareDatetime
    """
    Момент события, RFC 3339 в UTC (суффикс Z; отправитель всегда пишет UTC, читатель принимает любое смещение)
    """
    subject: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    """
    Необязательно: объект события в понятном человеку виде (номер сделки, КП, клиента); без персональных данных
    """
    datacontenttype: Literal["application/json"]
    dataschema: Annotated[
        str,
        Field(
            pattern="^rt://contracts/events/(crm|erp|eds|identity|platform)/[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*/v[1-9][0-9]*$"
        ),
    ]
    """
    rt://contracts/events/<домен>/<сущность>.<действие>/v<N> — соответствует type
    """
    tenant: Annotated[str, Field(pattern="^[a-z0-9][a-z0-9-]{0,62}$")]
    """
    Арендатор (компания-владелец ансамбля); v1 — railtech
    """
    correlationid: Annotated[str, Field(pattern="^[A-Za-z0-9._:/+=-]{1,128}$")]
    """
    UUID или X-Request-ID исходного запроса; если его нет — новый UUID. Переносится в задачу обработчика, логи и заголовок X-Request-ID доставки
    """
    traceparent: Annotated[
        str | None, Field(pattern="^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
    ] = None
    """
    Необязательно: W3C Trace Context исходного запроса
    """
    data: dict[str, Any]
    """
    Тело события по схеме типа (dataschema)
    """
