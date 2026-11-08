"""«Мои товары» партнёра (PART-2, ADR-0022 п. 4): эндпоинты `/api/portal/v1/partner/*` по `erp-portal.yaml`.

Все — модуль `my_products`; изменяющие — ещё `can_act` (общий `CanAct` базовой вьюхи). Партнёр видит только свои карточки и
свои цены; публикации и чужих данных здесь нет.
"""

from django.http import Http404
from portal.exceptions import PortalValidationError
from portal.serializers_partner import (
    PartnerConfirmRequestSerializer,
    PartnerConfirmResultSerializer,
    PartnerDocumentUploadRequestSerializer,
    PartnerFinanceSummarySerializer,
    PartnerOrderConfirmRequestSerializer,
    PartnerOrderDetailSerializer,
    PartnerOrderPageSerializer,
    PartnerPriceRequestDetailSerializer,
    PartnerPriceRequestPageSerializer,
    PartnerPriceRequestResponseSerializer,
    PartnerProductDetailSerializer,
    PartnerProductDocumentSerializer,
    PartnerProductPageSerializer,
    PartnerShipmentNoticeRequestSerializer,
    PartnerSubmitRequestSerializer,
    PartnerSubmitResultSerializer,
    PriceListAcceptedSerializer,
    PriceListTaskSerializer,
)
from portal.services import partner_orders as orders
from portal.services import partner_price_list as price_list
from portal.services import partner_products as products
from portal.views import BasePortalView
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from sourcing.views_templates import build_template_response

MODULE = "my_products"


#: Верхняя граница страницы: дальше только пустой хвост, а огромное смещение не должно доходить до базы.
MAX_PAGE = 10_000
MAX_PAGE_SIZE = 100


def _page_params(request) -> tuple[int, int]:
    """`page` и `page_size` из запроса; вне границ контракта (page ≥ 1 и ≤ 10 000, page_size 1…100) — 422 `VALIDATION_ERROR`."""
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
    except ValueError:
        raise PortalValidationError("VALIDATION_ERROR") from None
    if not 1 <= page <= MAX_PAGE or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise PortalValidationError("VALIDATION_ERROR")
    return page, page_size


class PartnerProductListView(BasePortalView):
    """GET /partner/products — свои карточки со своей ценой, вкладки по статусам."""

    required_module = MODULE

    def get(self, request):
        company = request.portal_company
        queryset = products.search(products.partner_cards(company), company, request.query_params.get("q", ""))
        counts = products.status_counts(company, queryset)
        wanted = request.query_params.get("status", "")
        if wanted:
            if wanted not in products.CARD_STATUSES:
                raise PortalValidationError("VALIDATION_ERROR")
            queryset = queryset.filter(products.status_filter(company, wanted))
        page, page_size = _page_params(request)
        total = queryset.count()
        start = (page - 1) * page_size
        page_items = list(products.ordered(queryset, company)[start : start + page_size])
        body = {
            "items": products.project_cards(company, page_items, request.portal_contact.language),
            "page": page,
            "page_size": page_size,
            "total": total,
            "counts": counts,
            "attention": products.offers_attention(company),
        }
        return Response(PartnerProductPageSerializer(body).data)


class PartnerProductDetailView(BasePortalView):
    """GET /partner/products/{id} — своя карточка с историей проверок; чужая — 404."""

    required_module = MODULE

    def get(self, request, pk):
        company = request.portal_company
        product = products.partner_cards(company).filter(pk=pk).first()
        if product is None:
            raise Http404
        return Response(
            PartnerProductDetailSerializer(
                products.project_detail(company, product, request.portal_contact.language)
            ).data
        )


class PartnerSubmitView(BasePortalView):
    """POST /partner/products/submit — свои черновики и возвращённые карточки → «на проверке», сотрудникам уведомление."""

    required_module = MODULE

    def post(self, request):
        serializer = PartnerSubmitRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        company = request.portal_company
        submitted, errors = products.submit_for_review(
            company=company, contact=request.portal_contact, ids=serializer.validated_data["ids"]
        )
        products.notify_submitted(company, len(submitted))
        return Response(PartnerSubmitResultSerializer({"submitted": submitted, "errors": errors}).data)


class PartnerConfirmView(BasePortalView):
    """POST /partner/offers/confirm — «подтвердить актуальность» цен компании, без модерации."""

    required_module = MODULE

    def post(self, request):
        serializer = PartnerConfirmRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        result = products.confirm_offers(
            company=request.portal_company,
            contact=request.portal_contact,
            ids=None if data.get("all") else data["ids"],
        )
        return Response(PartnerConfirmResultSerializer(result).data)


class PartnerPriceTemplateView(BasePortalView):
    """GET /partner/price-template — тот же шаблон прайса, что у сотрудника."""

    required_module = MODULE

    def get(self, request):
        return build_template_response()


class PartnerPriceListView(BasePortalView):
    """POST /partner/price-list — загрузка прайса (multipart); `dry_run` — предпросмотр без записи."""

    required_module = MODULE
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        content = price_list.read_workbook(request.FILES.get("file"))
        validity = price_list.parse_validity(request.data)
        task_id = price_list.enqueue_price_list(
            company=request.portal_company,
            contact=request.portal_contact,
            content=content,
            dry_run=price_list.is_true(request.data.get("dry_run")),
            validity=validity,
        )
        return Response(PriceListAcceptedSerializer({"task_id": task_id}).data, status=status.HTTP_202_ACCEPTED)


class PartnerPriceListTaskView(BasePortalView):
    """GET /partner/price-list/{task_id} — состояние и отчёт; задача другой компании — 404."""

    required_module = MODULE

    def get(self, request, task_id):
        if price_list.task_for_company(request.portal_company, task_id) is None:
            raise Http404
        return Response(PriceListTaskSerializer(price_list.task_view(task_id)).data)


class PartnerOrderListView(BasePortalView):
    """GET /partner/orders — заказы нашей компании к партнёру."""

    required_module = MODULE

    def get(self, request):
        wanted = request.query_params.get("status", "")
        if wanted and wanted not in orders.ORDER_STATUSES:
            raise PortalValidationError("VALIDATION_ERROR")
        page, page_size = _page_params(request)
        q = request.query_params.get("q", "")
        data = orders.list_partner_orders(
            company=request.portal_company, status=wanted or None, q=q, page=page, page_size=page_size
        )
        return Response(PartnerOrderPageSerializer(data).data)


class PartnerOrderDetailView(BasePortalView):
    """GET /partner/orders/{id} — детали заказа; чужой — 404."""

    required_module = MODULE

    def get(self, request, pk):
        data = orders.get_partner_order(company=request.portal_company, order_id=pk)
        if data is None:
            raise Http404
        return Response(PartnerOrderDetailSerializer(data).data)


class PartnerOrderConfirmView(BasePortalView):
    """POST /partner/orders/{id}/confirm — подтверждение заказа поставщиком."""

    required_module = MODULE

    def post(self, request, pk):
        serializer = PartnerOrderConfirmRequestSerializer(data=request.data or {})
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        expected_date = serializer.validated_data.get("expected_date")
        data = orders.confirm_partner_order(
            company=request.portal_company,
            user=request.portal_contact,
            order_id=pk,
            expected_date=expected_date,
        )
        if data is None:
            raise Http404
        return Response(PartnerOrderDetailSerializer(data).data)


class PartnerOrderShipView(BasePortalView):
    """POST /partner/orders/{id}/ship — уведомление об отгрузке (ASN)."""

    required_module = MODULE

    def post(self, request, pk):
        serializer = PartnerShipmentNoticeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        vd = serializer.validated_data
        data = orders.ship_partner_order(
            company=request.portal_company,
            user=request.portal_contact,
            order_id=pk,
            supplier_doc=vd["supplier_doc"],
            carrier=vd.get("carrier", ""),
            tracking_number=vd.get("tracking_number", ""),
            note=vd.get("note", ""),
        )
        if data is None:
            raise Http404
        return Response(PartnerOrderDetailSerializer(data).data)


class PartnerPriceRequestListView(BasePortalView):
    """GET /partner/price-requests — запросы цен от нас к поставщику."""

    required_module = MODULE

    def get(self, request):
        wanted = request.query_params.get("status", "")
        if wanted and wanted not in orders.PRICE_REQUEST_STATUSES:
            raise PortalValidationError("VALIDATION_ERROR")
        page, page_size = _page_params(request)
        q = request.query_params.get("q", "")
        data = orders.list_partner_price_requests(
            company=request.portal_company, status=wanted or None, q=q, page=page, page_size=page_size
        )
        return Response(PartnerPriceRequestPageSerializer(data).data)


class PartnerPriceRequestDetailView(BasePortalView):
    """GET /partner/price-requests/{id} — детали запроса цен; чужой — 404."""

    required_module = MODULE

    def get(self, request, pk):
        data = orders.get_partner_price_request(company=request.portal_company, request_id=pk)
        if data is None:
            raise Http404
        return Response(PartnerPriceRequestDetailSerializer(data).data)


class PartnerPriceRequestRespondView(BasePortalView):
    """POST /partner/price-requests/{id}/respond — ответ на запрос цен."""

    required_module = MODULE

    def post(self, request, pk):
        serializer = PartnerPriceRequestResponseSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = orders.respond_partner_price_request(
            company=request.portal_company,
            user=request.portal_contact,
            request_id=pk,
            answer_note=serializer.validated_data["answer_note"],
        )
        if data is None:
            raise Http404
        return Response(PartnerPriceRequestDetailSerializer(data).data)


class PartnerProductDocumentsView(BasePortalView):
    """GET/POST /partner/products/{id}/documents — список и загрузка документов карточки товара партнёра."""

    required_module = MODULE
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, pk):
        product = products.partner_cards(request.portal_company).filter(pk=pk).first()
        if product is None:
            raise Http404
        data = products.list_partner_documents(company=request.portal_company, product_id=pk)
        return Response(PartnerProductDocumentSerializer(data, many=True).data)

    def post(self, request, pk):
        file_obj = request.FILES.get("file")
        if file_obj:
            data = request.data
        else:
            serializer = PartnerDocumentUploadRequestSerializer(data=request.data)
            if not serializer.is_valid():
                raise PortalValidationError("VALIDATION_ERROR")
            data = serializer.validated_data

        doc = products.create_partner_document(
            company=request.portal_company,
            product_id=pk,
            data=data,
            file_obj=file_obj,
            contact=request.portal_contact,
        )
        return Response(PartnerProductDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class PartnerProductDocumentDetailView(BasePortalView):
    """DELETE /partner/products/{id}/documents/{doc_id} — удаление документа товара партнёром."""

    required_module = MODULE

    def delete(self, request, pk, doc_id):
        deleted = products.delete_partner_document(
            company=request.portal_company,
            product_id=pk,
            doc_id=doc_id,
        )
        if not deleted:
            raise Http404
        return Response(status=status.HTTP_204_NO_CONTENT)


class PartnerProductDocumentFileView(BasePortalView):
    """GET /partner/products/{id}/documents/{doc_id}/file — скачивание файла документа товара партнёра."""

    required_module = MODULE

    def get(self, request, pk, doc_id):
        doc = products.get_partner_document(
            company=request.portal_company,
            product_id=pk,
            doc_id=doc_id,
        )
        if doc is None:
            raise Http404
        from portal.services import catalog_documents

        resp = catalog_documents.file_response(doc)
        if resp is None:
            raise Http404
        return resp


class PartnerFinanceView(BasePortalView):
    """GET /partner/finance — сводка взаиморасчётов и оценка эффективности партнёра."""

    required_module = MODULE

    def get(self, request):
        data = orders.get_partner_finance_summary(company=request.portal_company)
        return Response(PartnerFinanceSummarySerializer(data).data)
