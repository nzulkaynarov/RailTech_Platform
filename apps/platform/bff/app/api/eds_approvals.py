"""EDS · КП на одобрение и документы на согласовании (контракт: tag `eds-approvals`, 0.24.0; D1-4).

BFF не решает: маршрут, шаги, чек-лист КП (визы и маржа блокируют, срок — предупреждение, C1-G-1)
и право решать шаг проверяет EDS. Здесь — доступ к разделам каталога (КП — `eds.drafts`: чтение
видит менеджер, решает директор; документы — `eds.memo.approve`, чтение также у автора —
`eds.memo.create`), вызовы EDS с токеном доступа EDS (обмен токена сотрудника CRM `aud=eds`), состав
КП и контакт клиента из ERP с частичным ответом `sources`, вырезание себестоимости и маржи у роли
без группы `cost_margin`, адресация и по id, и по номеру (`КП-2026/115`, `СЗ-2026/014`), перевод
ошибок решения в формат `Error`.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream
from app.api.eds_projects import _scan_body
from app.deps import Authed, require, require_any
from app.eds_approvals import (
    decision_error,
    evidence_path,
    memo_card,
    memo_document_id,
    memo_page,
    not_found,
    quote_card,
    quote_page,
    quote_route_id,
    record_client_decision,
    send_quote,
)
from app.eds_documents import API, EdsProxy
from app.eds_projects import project_error
from app.errors import backend_unavailable
from app.schemas_eds_approvals import (
    MemoApprovalCard,
    MemoApprovalPage,
    MemoDecisionIn,
    QuoteApprovalCard,
    QuoteApprovalPage,
    QuoteDecisionIn,
    QuoteSendIn,
    RouteStatus,
)

router = APIRouter(prefix="/eds", tags=["eds-approvals"])

QuoteReader = Annotated[Authed, Depends(require("eds.drafts", "read"))]
QuoteDecider = Annotated[Authed, Depends(require("eds.drafts", "full"))]
# Отправляет КП клиенту тот, у кого `quote.send` ERP — раздел «Клиенты» полный (C1-G-4, D17G-2);
# кому из них можно именно это КП (своя заявка или `quote.review`), решает ERP.
QuoteSender = Annotated[Authed, Depends(require("crm.clients", "full"))]
# Решение клиента по его подтверждению записывает тот, кто ведёт клиента (A1): раздел «Клиенты»
# полный; право `deal.manage` проверяет ERP.
QuoteClientRecorder = QuoteSender
MemoReader = Annotated[
    Authed, Depends(require_any(("eds.memo.approve", "read"), ("eds.memo.create", "read")))
]
# Решает директор (`eds.memo.approve`) или бухгалтер на своём шаге (`eds.payments` — полный);
# чей шаг, знает EDS.
MemoDecider = Annotated[
    Authed, Depends(require_any(("eds.memo.approve", "full"), ("eds.payments", "full")))
]
ApprovalId = Annotated[UUID, Path()]
Scope = Literal["mine", "all"]
Status = Annotated[list[RouteStatus] | None, Query(max_length=4)]


def _proxy(authed: Authed) -> EdsProxy:
    return EdsProxy(authed.call)


async def _decide(proxy: EdsProxy, approval_id: UUID, body: dict[str, Any]) -> Any:
    response = await proxy.raw("POST", f"{API}/approvals/{approval_id}/decision", json=body)
    if response.status_code != 200:
        raise decision_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise backend_unavailable("eds", "bad_response") from exc


# --- КП ------------------------------------------------------------------------------------------


@router.get("/quotes", response_model=QuoteApprovalPage, operation_id="listQuoteApprovals")
async def list_quotes(
    authed: QuoteReader,
    scope: Scope = "mine",
    status: Status = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> QuoteApprovalPage:
    return await quote_page(
        _proxy(authed),
        mine=scope == "mine",
        status=list(dict.fromkeys(status or [])),
        cursor=cursor,
        limit=limit,
    )


# Раньше `/quotes/{ref:path}`: иначе адрес файла съел бы путь карточки по номеру.
@router.get(
    "/quotes/{id}/client-decision/evidence",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadQuoteClientDecisionEvidence",
)
async def download_quote_client_decision_evidence(id: ApprovalId, authed: QuoteReader) -> Response:
    """Файл подтверждения клиента потоком, всегда как вложение (тип не доверяется)."""
    proxy = _proxy(authed)
    path = await evidence_path(authed, proxy, str(id))
    upstream = await authed.call("erp", "GET", path, stream=True)
    if upstream.status_code != 200:
        try:
            await upstream.aread()
            raise project_error(upstream)
        finally:
            await upstream.aclose()
    headers = {
        "Content-Disposition": f'attachment; filename="client-confirmation-{id}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(upstream, headers, "application/octet-stream")


@router.get(
    "/quotes/{ref:path}",
    response_model=QuoteApprovalCard,
    response_model_exclude_unset=True,
    operation_id="getQuoteApproval",
)
async def get_quote(ref: str, authed: QuoteReader) -> QuoteApprovalCard:
    proxy = _proxy(authed)
    route_id = await quote_route_id(proxy, ref)
    return await quote_card(
        authed, proxy, await proxy.request("GET", f"{API}/approvals/{route_id}")
    )


@router.post(
    "/quotes/{id}/decision",
    response_model=QuoteApprovalCard,
    response_model_exclude_unset=True,
    operation_id="decideQuoteApproval",
)
async def decide_quote(
    id: ApprovalId, body: QuoteDecisionIn, authed: QuoteDecider
) -> QuoteApprovalCard:
    proxy = _proxy(authed)
    return await quote_card(authed, proxy, await _decide(proxy, id, body.for_eds()))


@router.post(
    "/quotes/{id}/send",
    response_model=QuoteApprovalCard,
    response_model_exclude_unset=True,
    operation_id="sendQuoteByChannel",
)
async def send_quote_by_channel(
    id: ApprovalId, body: QuoteSendIn, authed: QuoteSender
) -> QuoteApprovalCard:
    proxy = _proxy(authed)
    route = await send_quote(authed, proxy, str(id), body.channel)
    return await quote_card(authed, proxy, route)


@router.post(
    "/quotes/{id}/client-decision",
    response_model=QuoteApprovalCard,
    response_model_exclude_unset=True,
    operation_id="recordQuoteClientDecision",
)
async def record_quote_client_decision(
    id: ApprovalId, request: Request, authed: QuoteClientRecorder
) -> QuoteApprovalCard:
    """«Клиент принял / отклонил» по подтверждению клиента (A1): multipart до 20 МБ как есть."""
    content, content_type = await _scan_body(request)
    proxy = _proxy(authed)
    route = await record_client_decision(authed, proxy, str(id), content, content_type)
    return await quote_card(authed, proxy, route)


# --- служебные записки, заявления, отчёты ---------------------------------------------------------


@router.get("/memo-approvals", response_model=MemoApprovalPage, operation_id="listMemoApprovals")
async def list_memos(
    authed: MemoReader,
    scope: Scope = "mine",
    status: Status = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MemoApprovalPage:
    return await memo_page(
        _proxy(authed),
        mine=scope == "mine",
        status=list(dict.fromkeys(status or [])),
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/memo-approvals/{ref:path}",
    response_model=MemoApprovalCard,
    operation_id="getMemoApproval",
)
async def get_memo(ref: str, authed: MemoReader) -> MemoApprovalCard:
    proxy = _proxy(authed)
    document_id = await memo_document_id(proxy, ref)
    return await memo_card(proxy, await proxy.request("GET", f"{API}/documents/{document_id}"))


@router.post(
    "/memo-approvals/{id}/decision",
    response_model=MemoApprovalCard,
    operation_id="decideMemoApproval",
)
async def decide_memo(
    id: ApprovalId, body: MemoDecisionIn, authed: MemoDecider
) -> MemoApprovalCard:
    proxy = _proxy(authed)
    approval = await _decide(proxy, id, body.for_eds())
    document_id = (
        (approval.get("object") or {}).get("document_id") if isinstance(approval, dict) else None
    )
    if not isinstance(document_id, str):
        raise not_found("Документ не найден.")
    return await memo_card(
        proxy, await proxy.request("GET", f"{API}/documents/{document_id}"), approval
    )
