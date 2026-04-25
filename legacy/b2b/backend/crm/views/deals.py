from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, OpenApiResponse,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from django.db.models import Prefetch, Max
from django.utils.translation import gettext_lazy as _

from core.permissions import IsPlatformAdmin, IsCompanyMemberOrPlatformAdmin
from crm.models import Deal, DealStage, Quote, QuoteItem
from crm.serializers import DealListSerializer, DealDetailSerializer
from crm.services import transition_deal_stage, force_transition_deal_stage, register_new_deal
from crm import services as crm_services


@extend_schema_view(
    list=extend_schema(
        summary="List deals",
        description=(
            "Returns deals accessible to the current user. "
            "Admins/managers see all; clients see only their company's deals."
        ),
        tags=['CRM'],
    ),
    create=extend_schema(
        summary="Create deal",
        description=(
            "Create a new deal. The client is auto-assigned to the current user, "
            "and the company is set from the user's primary company."
        ),
        tags=['CRM'],
    ),
    retrieve=extend_schema(
        summary="Get deal details",
        description="Returns full deal details including all quotes and their items.",
        tags=['CRM'],
    ),
    update=extend_schema(summary="Update deal", tags=['CRM']),
    partial_update=extend_schema(summary="Partially update deal", tags=['CRM']),
    destroy=extend_schema(summary="Delete deal", tags=['CRM']),
)
class DealViewSet(viewsets.ModelViewSet):
    """
    CRUD for deals (the core CRM entity).

    Deal lifecycle: DRAFT -> KYC_PENDING -> SOURCING -> CALCULATING ->
    QUOTE_SENT -> CONTRACT_SIGNED -> CLOSED_WON / CLOSED_LOST.
    """
    def get_serializer_class(self):
        if self.action == 'list':
            return DealListSerializer
        return DealDetailSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Deal.objects.none()
        user = self.request.user
        quote_items_qs = QuoteItem.objects.select_related(
            'product', 'product__domain_type', 'offer', 'offer__supplier', 'frozen_currency'
        )
        quotes_qs = Quote.objects.select_related('status').prefetch_related(
            Prefetch('items', queryset=quote_items_qs)
        ).order_by('-version')
        queryset = Deal.objects.all().select_related(
            'client', 'manager', 'company', 'stage'
        ).prefetch_related(Prefetch('quotes', queryset=quotes_qs))

        if user.is_platform_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(company_id__in=user_company_ids)

    def perform_create(self, serializer):
        primary_company = self.request.user.primary_company
        if not primary_company:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                "company": _("User has no associated company. Please complete your company profile."),
            })
        save_kwargs = dict(client=self.request.user, company=primary_company)
        if not serializer.validated_data.get('stage'):
            draft_stage = DealStage.objects.filter(code='DRAFT').first()
            if draft_stage:
                save_kwargs['stage'] = draft_stage
        deal = serializer.save(**save_kwargs)
        register_new_deal(deal, self.request.user)

    @extend_schema(
        summary="Change deal stage",
        description=(
            "Transition the deal to a new stage using FSM validation. "
            "Valid transitions are enforced by the backend."
        ),
        request=inline_serializer('ChangeStageRequest', fields={
            'stage_code': drf_serializers.CharField(
                help_text="Target stage code (e.g. SOURCING, CALCULATING, QUOTE_SENT)"
            ),
        }),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            422: OpenApiResponse(description="Invalid stage transition"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='change-stage')
    def change_stage(self, request, pk=None):
        """Change deal stage with FSM validation."""
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        if not stage_code:
            return Response(
                {'detail': 'STAGE_CODE_REQUIRED'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deal, error = transition_deal_stage(deal, stage_code, actor=request.user)
        if error:
            return Response(
                {'detail': error},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)

    @extend_schema(
        summary="Force change deal stage (admin)",
        description=(
            "Transition the deal to ANY stage, bypassing FSM validation. "
            "Admin/Manager only. Use for emergency fixes."
        ),
        request=inline_serializer('ForceChangeStageRequest', fields={
            'stage_code': drf_serializers.CharField(),
            'reason': drf_serializers.CharField(required=False, default=''),
        }),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            404: OpenApiResponse(description="Stage not found"),
        },
        tags=['CRM'],
    )
    @action(
        detail=True, methods=['post'], url_path='force-change-stage',
        permission_classes=[IsAuthenticated, IsPlatformAdmin],
    )
    def force_change_stage(self, request, pk=None):
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        reason = (request.data.get('reason') or '').strip()
        if not stage_code:
            return Response({'detail': 'STAGE_CODE_REQUIRED'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not reason:
            return Response({'detail': 'REASON_REQUIRED'},
                            status=status.HTTP_400_BAD_REQUEST)
        deal, error = force_transition_deal_stage(
            deal, stage_code, actor=request.user, reason=reason,
        )
        if error:
            code = status.HTTP_400_BAD_REQUEST
            return Response({'detail': error}, status=code)
        return Response(DealDetailSerializer(deal).data)

    @extend_schema(
        summary="Export deal PDF",
        description=(
            "Export PDF of the deal's active quote. "
            "Auto-generates the PDF if not yet created."
        ),
        responses={
            (200, 'application/pdf'): OpenApiResponse(description="PDF file download"),
            404: OpenApiResponse(description="No active quote"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=['CRM'],
    )
    @extend_schema(summary="Open RFQ — move deal to RFQ_OPEN and notify suppliers", tags=['CRM'],
                   request=inline_serializer('OpenRFQ', fields={
                       'supplier_ids': drf_serializers.ListField(child=drf_serializers.IntegerField(), required=False),
                   }))
    @action(detail=True, methods=['post'], url_path='open-rfq',
            permission_classes=[IsAuthenticated, IsPlatformAdmin])
    def open_rfq(self, request, pk=None):
        deal, err = crm_services.open_rfq(
            int(pk), request.user,
            supplier_ids=request.data.get('supplier_ids') or None,
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(DealDetailSerializer(deal).data)

    @action(detail=True, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request, pk=None):
        """Export PDF of the deal's active quote."""
        deal = self.get_object()
        quote = deal.active_quote
        if not quote:
            return Response(
                {'error': 'No active quote for this deal'},
                status=status.HTTP_404_NOT_FOUND
            )
        if not quote.pdf_file:
            # Auto-generate PDF if not yet generated
            from crm.services import QuoteLifecycleService
            try:
                quote = QuoteLifecycleService.generate_pdf(quote.pk)
            except (OSError, ValueError, RuntimeError):
                return Response(
                    {'error': 'Failed to generate PDF'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        if not quote.pdf_file:
            return Response(
                {'error': 'PDF generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        from django.http import FileResponse
        return FileResponse(
            quote.pdf_file.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=f'RailTech_Quote_{deal.id}.pdf'
        )


@extend_schema_view(
    list=extend_schema(summary="List deal stages", tags=['CRM']),
)
class DealStageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DealStage.objects.all().order_by('sort_order', 'name')
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{'code': s.code, 'name': s.name} for s in self.get_queryset()]
        return Response(data)
