"""Подписанная ссылка на файл документа для CRM (FIX-32, находки S-4, I-6; `GET /documents/{id}/link`, контракт 0.2.0).

Как это устроено:

* CRM просит ссылку (`issue_document_link`): ERP проверяет, что документ можно отдать клиенту (выпущен, клиентского
  вида, компания сопоставлена с клиентом CRM), и выдаёт URL публичного маршрута ERP на `FRONTEND_URL` с подписанным
  токеном (`django.core.signing`, соль своя, срок 10 минут в самом токене).
* Токен несёт вид и id документа, клиента CRM и контекст выдачи — вьюха (`integration.public_views`) не принимает голый id.
  На каждом открытии всё проверяется заново (`resolve_link_token`): подпись, срок, сопоставление и видимость документа —
  отозванное за десять минут не откроется.
* Выдача и каждое скачивание пишутся в журнал ERP (`ActivityLog`, как `sso.revoke` и `document.downloaded_by_client`),
  с `crm_*`-контекстом из заголовка `X-CRM-Context`. Отказы (404) наружу одинаковы: чужой, черновой и внутренний документ
  неотличимы от несуществующего.

Какие документы ссылаются: `documents.GeneratedDocument` — тот же набор и те же id, что отдают `GET /deals/{id}/documents`
и `last_document` сводки (`linkable_documents`). Правило видимости клиенту одно с порталом
(`portal.services.documents.find_client_document`): выпущен, вид «договор/счёт/акт»; письма, рапорты и произвольные
документы внутренние. PDF КП, договора, счёта и акта в их собственных моделях в этот набор не входят — см. QUESTIONS Q-FIX32-1.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings
from django.core import signing
from django.utils import timezone
from documents.models import GeneratedDocument
from portal.services import documents as portal_documents

from crm.constants import GeneratedDocumentStatusCode
from crm.models import ActivityLog

from ..models import CrmClientMapping

logger = logging.getLogger(__name__)

#: Время жизни ссылки (контракт: «ссылка живёт 10 минут»).
LINK_TTL = datetime.timedelta(minutes=10)
#: Соль подписи: токен, выданный для другого назначения (сессия, magic-link), здесь не откроется.
LINK_SALT = "integration.document-link.v1"
#: Путь публичного маршрута (`core/urls.py`); хост — `FRONTEND_URL`, как у публичных ссылок на КП и документы.
LINK_PATH = "/api/v1/public/doc-links/{token}/"
#: Вид источника в токене. Сейчас файл отдаётся только у `GeneratedDocument`; поле нужно, чтобы вид был в подписи.
SOURCE_GENERATED = "generated"

_CHANNELS = frozenset({"bot", "crm"})
_RAW_CONTEXT_LIMIT = 200


class LinkNotFound(Exception):
    """Подпись не сошлась, токен чужой, документ скрыт или не существует — для вызывающего это одно и то же (404)."""


class LinkExpired(Exception):
    """Подпись верна, но срок ссылки вышел (410)."""


@dataclass(frozen=True)
class CrmContext:
    """Контекст выдачи из `X-CRM-Context`: `{"crm_client_id": …, "crm_user_id"?: …, "channel": "bot|crm"}`.

    Не разобранное (не JSON, чужой формат — например, строка erp-mcp) в разбор не попадает, но остаётся в `raw`, чтобы
    след в журнале не терялся.
    """

    crm_client_id: Optional[int] = None
    crm_user_id: Optional[int] = None
    channel: Optional[str] = None
    raw: str = ""

    def as_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "crm_client_id": self.crm_client_id,
            "crm_user_id": self.crm_user_id,
            "channel": self.channel,
        }
        if self.raw:
            params["crm_context_raw"] = self.raw
        return params


def _int_or_none(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_crm_context(raw: Optional[str]) -> CrmContext:
    """Разобрать заголовок. Мусор не роняет запрос (след важнее строгости), но и в проверки не попадает."""
    text = (raw or "").strip()
    if not text:
        return CrmContext()
    try:
        data = json.loads(text)
    except ValueError:
        return CrmContext(raw=text[:_RAW_CONTEXT_LIMIT])
    if not isinstance(data, dict):
        return CrmContext(raw=text[:_RAW_CONTEXT_LIMIT])
    channel = data.get("channel")
    return CrmContext(
        crm_client_id=_int_or_none(data.get("crm_client_id")),
        crm_user_id=_int_or_none(data.get("crm_user_id")),
        channel=channel if channel in _CHANNELS else None,
    )


# ── Какие документы отдаются ─────────────────────────────────────────────────────────────────────────


def linkable_documents():
    """Документы, которые CRM может увидеть в списке и открыть ссылкой: выпущенные `GeneratedDocument` клиентских видов.

    Тот же предикат, что у портала (`portal.services.documents`): список и ссылка не расходятся — id из списка всегда
    открывается (сквозной тест `test_documents_link.py` сверяет этот запрос с `find_client_document`).
    """
    return GeneratedDocument.objects.filter(
        status__code=GeneratedDocumentStatusCode.ISSUED,
        template__kind__code__in=list(portal_documents.KIND_BY_TEMPLATE_KIND),
    )


def _owner_company(document: GeneratedDocument):
    """Компания клиента, которой принадлежит документ: по сделке, иначе по контакту (документ без сделки)."""
    if document.deal_id and document.deal.company_id:
        return document.deal.company
    if document.contact_id and document.contact.company_id:
        return document.contact.company
    return None


def _find_document(pk: int, *, crm_client_id: Optional[int] = None):
    """`(PortalDocument, CrmClientMapping)` или `None`.

    `None` — когда документа нет, он не выпущен или внутренний, у компании нет сопоставления с клиентом CRM либо
    `crm_client_id` (если указан) — другой клиент: чужой документ не отличим от несуществующего.
    """
    document = GeneratedDocument.objects.select_related("deal__company", "contact__company").filter(pk=pk).first()
    if document is None:
        return None
    company = _owner_company(document)
    if company is None:
        return None
    mapping = CrmClientMapping.objects.filter(company=company).first()
    if mapping is None or (crm_client_id is not None and mapping.crm_client_id != crm_client_id):
        return None
    portal_document = portal_documents.find_client_document(
        company, portal_documents.encode_document_id(SOURCE_GENERATED, document.pk)
    )
    if portal_document is None:
        return None
    return portal_document, mapping


# ── Журнал ERP ───────────────────────────────────────────────────────────────────────────────────────


def _record(event_code: str, action: str, document, mapping, context: CrmContext, **extra) -> None:
    ActivityLog.objects.create(
        action=action,
        event_code=event_code,
        event_params={
            "document_id": document.obj.pk,
            "kind": document.kind,
            "number": document.number,
            **context.as_params(),
            **extra,
        },
        detail=f"{document.title}: CRM-клиент #{mapping.crm_client_id}",
        entity_type="generated_document",
        entity_id=document.obj.pk,
        company_id=mapping.company_id,
        deal=document.deal,
    )


# ── Выдача ───────────────────────────────────────────────────────────────────────────────────────────


def issue_document_link(erp_document_id: int, crm_context: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Подписанная ссылка на файл документа (`DocumentLink` контракта) или `None` (для API — 404).

    Пишет выдачу в журнал ERP. Файл ещё не отрисован — ставит рендер в очередь, чтобы к открытию ссылки он был готов;
    `size_bytes` тогда в ответе нет (размер неизвестен), а не выдуманное число.
    """
    context = parse_crm_context(crm_context)
    found = _find_document(erp_document_id, crm_client_id=context.crm_client_id)
    if found is None:
        return None
    document, mapping = found

    expires_at = timezone.now() + LINK_TTL
    token = signing.dumps(
        {
            "k": SOURCE_GENERATED,
            "d": document.obj.pk,
            "c": mapping.crm_client_id,
            "u": context.crm_user_id,
            "ch": context.channel,
            "exp": int(expires_at.timestamp()),
        },
        salt=LINK_SALT,
        compress=True,
    )
    if not document.file and portal_documents.renders_on_demand(document):
        portal_documents.enqueue_render(document)

    _record(
        "document.link_issued",
        "Выдана ссылка на документ для CRM",
        document,
        mapping,
        context,
        expires_at=expires_at.isoformat(),
    )

    link = {
        "url": f"{settings.FRONTEND_URL.rstrip('/')}{LINK_PATH.format(token=token)}",
        "expires_at": expires_at.isoformat(),
        "file_name": document.file_name,
        "content_type": document.content_type,
    }
    size = portal_documents.file_size(document)
    if size:
        link["size_bytes"] = size
    return link


# ── Открытие по ссылке ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedLink:
    document: portal_documents.PortalDocument
    mapping: CrmClientMapping
    context: CrmContext


def resolve_link_token(token: str) -> ResolvedLink:
    """Проверить токен и документ заново. `LinkNotFound` — 404, `LinkExpired` — 410.

    Срок проверяется только после подписи: подделка срока не отличима от любой другой подделки (404), а 410 получает
    лишь тот, кто держит настоящий токен.
    """
    try:
        claims = signing.loads(token, salt=LINK_SALT, max_age=int(LINK_TTL.total_seconds()) + 60)
    except signing.SignatureExpired:
        raise LinkExpired from None
    except signing.BadSignature:
        raise LinkNotFound from None

    try:
        source, pk, crm_client_id, expires = claims["k"], claims["d"], claims["c"], claims["exp"]
    except (KeyError, TypeError):
        raise LinkNotFound from None
    if source != SOURCE_GENERATED or not all(isinstance(v, int) for v in (pk, crm_client_id, expires)):
        raise LinkNotFound
    if timezone.now().timestamp() > expires:
        raise LinkExpired

    found = _find_document(pk, crm_client_id=crm_client_id)
    if found is None:
        raise LinkNotFound
    document, mapping = found
    context = CrmContext(
        crm_client_id=crm_client_id,
        crm_user_id=_int_or_none(claims.get("u")),
        channel=claims.get("ch") if claims.get("ch") in _CHANNELS else None,
    )
    return ResolvedLink(document=document, mapping=mapping, context=context)


def record_download(link: ResolvedLink, *, ip: str) -> None:
    """Запись журнала о каждой выдаче файла по ссылке: что, кому из CRM-контекста, с какого IP."""
    _record(
        "document.link_downloaded",
        "Документ скачан по ссылке CRM",
        link.document,
        link.mapping,
        link.context,
        ip=ip,
    )
