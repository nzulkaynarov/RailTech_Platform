"""«Мои товары» партнёра (PART-2, ADR-0022 п. 4): эндпоинты `/api/portal/v1/partner/*` по `erp-portal.yaml`.

Все — модуль `my_products`; изменяющие — ещё `can_act` (общий `CanAct` базовой вьюхи). Партнёр видит только свои карточки и
свои цены; публикации и чужих данных здесь нет.
"""

from django.http import Http404
from portal.exceptions import PortalValidationError
from portal.serializers_partner import (
    PartnerConfirmRequestSerializer,
    PartnerConfirmResultSerializer,
    PartnerProductDetailSerializer,
    PartnerProductPageSerializer,
    PartnerSubmitRequestSerializer,
    PartnerSubmitResultSerializer,
    PriceListAcceptedSerializer,
    PriceListTaskSerializer,
)
from portal.services import partner_price_list as price_list
from portal.services import partner_products as products
from portal.views import BasePortalView
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from sourcing.views_templates import build_template_response

MODULE = "my_products"


class PartnerProductListView(BasePortalView):
    """GET /partner/products — свои карточки со своей ценой, вкладки по статусам."""

    required_module = MODULE

    def get(self, request):
        company = request.portal_company
        queryset = products.search(products.partner_cards(company), request.query_params.get("q", ""))
        counts = products.status_counts(company, queryset)
        wanted = request.query_params.get("status", "")
        if wanted:
            if wanted not in products.CARD_STATUSES:
                raise PortalValidationError("VALIDATION_ERROR")
            queryset = queryset.filter(products.status_filter(company, wanted))
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError:
            page, page_size = 1, 20
        total = queryset.count()
        start = (page - 1) * page_size
        page_items = list(queryset.order_by("-updated_at", "-id")[start : start + page_size])
        body = {
            "items": products.project_cards(company, page_items),
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
        return Response(PartnerProductDetailSerializer(products.project_detail(company, product)).data)


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
