from rest_framework import viewsets, status, throttling
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Deal, DealStage, Quote, QuoteItem, Message, ActivityLog
from .serializers import (
    DealListSerializer, DealDetailSerializer, QuoteSerializer, QuoteItemSerializer,
    MessageSerializer, ActivityLogSerializer, LeadSerializer
)
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsManagerOrAdmin, IsOwnerOrManagerOrAdmin

# Explicit deal stage transition matrix (FSM)
ALLOWED_STAGE_TRANSITIONS = {
    'DRAFT': ['KYC_PENDING', 'SOURCING', 'CLOSED_LOST'],
    'KYC_PENDING': ['SOURCING', 'CLOSED_LOST'],
    'SOURCING': ['CALCULATING', 'CLOSED_LOST'],
    'CALCULATING': ['QUOTE_SENT', 'SOURCING', 'CLOSED_LOST'],
    'QUOTE_SENT': ['CONTRACT_SIGNED', 'CALCULATING', 'CLOSED_LOST'],
    'CONTRACT_SIGNED': ['CLOSED_WON', 'CLOSED_LOST'],
    'CLOSED_WON': [],   # Terminal state
    'CLOSED_LOST': [],   # Terminal state
}


class DealViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == 'list':
            return DealListSerializer
        return DealDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = Deal.objects.all().select_related(
            'client', 'manager', 'company', 'stage'
        ).prefetch_related('quotes', 'quotes__items')

        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        # B2B Filter: User sees all deals of their active companies
        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(company_id__in=user_company_ids)

    def perform_create(self, serializer):
        # Auto-assign the primary company if not provided
        primary_company = self.request.user.primary_company
        if not primary_company:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"company": "У вас нет привязанной компании. Заполните профиль компании."}
            )
        deal = serializer.save(client=self.request.user,
                               company=primary_company)

        ActivityLog.objects.create(
            action="Сделка создана",
            detail=(
                f"Пользователь {self.request.user.email} инициировал "
                f"новую сделку #{deal.id} для компании "
                f"{deal.company.name if deal.company else 'N/A'}"
            ),
            user=self.request.user,
            level='INFO'
        )

    @action(detail=True, methods=['post'], url_path='change-stage')
    def change_stage(self, request, pk=None):
        """Change deal stage with FSM validation."""
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        if not stage_code:
            return Response({'detail': 'stage_code is required.'}, status=status.HTTP_400_BAD_REQUEST)

        new_stage = DealStage.objects.filter(code=stage_code).first()
        if not new_stage:
            return Response({'detail': f'Unknown stage: {stage_code}'}, status=status.HTTP_400_BAD_REQUEST)

        # FSM validation: check allowed transitions
        current_code = deal.stage.code if deal.stage else 'DRAFT'
        allowed = ALLOWED_STAGE_TRANSITIONS.get(current_code, [])
        if stage_code not in allowed:
            return Response(
                {'detail': f'Transition {current_code} → {stage_code} is not allowed. '
                           f'Allowed: {", ".join(allowed) if allowed else "none (terminal state)"}'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        old_stage_name = deal.stage.name if deal.stage else 'N/A'
        deal.stage = new_stage
        deal.save(update_fields=['stage'])

        ActivityLog.objects.create(
            action="Стадия изменена",
            detail=f"Сделка #{deal.id}: {old_stage_name} → {new_stage.name}",
            user=request.user,
            level='INFO'
        )
        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)


class QuoteViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = Quote.objects.all().select_related('deal', 'status')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    @action(detail=True, methods=['post'], url_path='generate-pdf')
    def generate_pdf(self, request, pk=None):
        """Generate PDF for a quote."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        try:
            quote = QuoteLifecycleService.generate_pdf(quote.pk)
            return Response({
                'status': 'PDF generated',
                'pdf_url': request.build_absolute_uri(quote.pdf_file.url) if quote.pdf_file else None
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='send-to-client',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def send_to_client(self, request, pk=None):
        """Send quote to client (manager only). Freezes prices."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.send_to_client(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Client approves the quote."""
        quote = self.get_object()
        # Verify the user is the deal's client or company member
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(company=quote.deal.company, is_active=True).exists():
                return Response({'error': 'Only the client company can approve'}, status=status.HTTP_403_FORBIDDEN)

        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.approve_quote(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Client rejects the quote."""
        quote = self.get_object()
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(company=quote.deal.company, is_active=True).exists():
                return Response({'error': 'Only the client company can reject'}, status=status.HTTP_403_FORBIDDEN)

        reason = request.data.get('reason', '')
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.reject_quote(quote.pk, request.user, reason)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """Download the generated PDF."""
        quote = self.get_object()
        if not quote.pdf_file:
            return Response({'error': 'PDF not generated yet'}, status=status.HTTP_404_NOT_FOUND)

        from django.http import FileResponse
        return FileResponse(quote.pdf_file.open('rb'), content_type='application/pdf',
                            as_attachment=True, filename=quote.pdf_file.name.split('/')[-1])


class QuoteItemViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteItemSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = QuoteItem.objects.all().select_related('product', 'quote')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]
    filterset_fields = ['deal_id']

    def get_queryset(self):
        user = self.request.user
        queryset = Message.objects.all().order_by(
            'timestamp').select_related('sender', 'deal')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


class CRMAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        from .services import get_crm_analytics_data
        data = get_crm_analytics_data()
        return Response(data)


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get_queryset(self):
        """Staff see all logs. Non-admin managers see only their own."""
        user = self.request.user
        queryset = ActivityLog.objects.all().select_related('user')
        if user.is_superuser:
            return queryset
        return queryset.filter(user=user)


class LeadSubmitThrottle(throttling.SimpleRateThrottle):
    scope = 'lead_submit'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class LeadCreateView(APIView):
    permission_classes = []
    throttle_classes = [LeadSubmitThrottle]

    def post(self, request):
        serializer = LeadSerializer(data=request.data)
        if serializer.is_valid():
            lead = serializer.save()
            ActivityLog.objects.create(
                action="Новый лид с сайта",
                detail=f"Получен запрос от {lead.name} ({lead.email}) через лендинг.",
                level='SUCCESS'
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
