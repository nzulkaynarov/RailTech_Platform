"""Workflow-экшены сделки: claim/assign, AI-черновик КП, операторские
оверрайды и экспорт. Отдельный модуль по причине изменения (распил deals.py 783 строки,
тех-долг хендоффов); поведение 1:1 — методы перенесены дословно."""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsPlatformAdmin
from crm.models import Deal
from crm.serializers import DealDetailSerializer
from crm.services import force_transition_deal_stage

from .ai import AiDraftThrottle


class DealWorkflowActionsMixin:
    """Экшены «после сборки заявки»: кто ведёт сделку и что с ней делает продавец."""

    def _assignment_response(self, deal, err, request):
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "MEMBER_REQUIRED_FOR_ACTION")
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        # Re-fetch UNSCOPED (not via get_queryset): the service already authorized the mutation,
        # but get_queryset() is context-sensitive and excludes this deal for a delegated admin
        # (can_sell=False) or in BUYER context → would raise DoesNotExist → HTTP 500 after a
        # successful write. The service-returned object is the same deal; re-fetch only to refresh
        # prefetched caches for the serializer.
        deal = Deal.objects.get(pk=deal.pk)
        return Response(DealDetailSerializer(deal, context={"request": request}).data)

    @extend_schema(summary="Claim a deal (take it from the shared queue)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="claim", permission_classes=[IsAuthenticated])
    def claim(self, request, pk=None):
        """ADR-0006 Move 2: a back-office staff member takes ownership of an unclaimed заявка."""
        from crm.services.assignment import claim_deal

        deal, err = claim_deal(int(pk), request.user)
        return self._assignment_response(deal, err, request)

    @extend_schema(summary="Release a deal back to the queue", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="release", permission_classes=[IsAuthenticated])
    def release(self, request, pk=None):
        from crm.services.assignment import release_deal

        deal, err = release_deal(int(pk), request.user)
        return self._assignment_response(deal, err, request)

    @extend_schema(
        summary="Assign a deal to a team member (company admin)",
        request=inline_serializer("AssignDealRequest", fields={"assignee_id": drf_serializers.IntegerField()}),
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="assign", permission_classes=[IsAuthenticated])
    def assign(self, request, pk=None):
        from crm.services.assignment import assign_deal

        deal, err = assign_deal(int(pk), request.user, request.data.get("assignee_id"))
        return self._assignment_response(deal, err, request)

    @extend_schema(
        summary="W2 одна кнопка: взять заявку в работу и подготовить КП",
        description=(
            "One-click-quotation (утв. spec-inbound-rfq W2): claim + переход стадии в CALCULATING + "
            "предзаполненный черновик КП со строками заявки. При включённом ИИ — "
            "202 {task_id, mode:'ai'} (существующий draft_quote job — AI-матч и цены, поллинг "
            "sourcing/ai-status/); при выключенном — 200 {quote_id, mode:'quote'} синхронно "
            "(копия строк + точный ГОСТ/MPN-матч + цены из своих офферов, без AI). Идемпотентно: "
            "существующий КП компании переиспользуется, повторный клик в AI-режиме возвращает "
            "уже идущий task_id (задача не ставится дважды)."
        ),
        responses={
            200: OpenApiResponse(description="{mode:'quote', quote_id} — КП готов, открывайте билдер"),
            202: OpenApiResponse(description="{mode:'ai', task_id} — AI-черновик готовится, поллинг ai-status"),
            400: OpenApiResponse(description="Нет строк заявки / стадия вне пред-КП набора"),
            403: OpenApiResponse(description="Не сотрудник своей компании"),
            404: OpenApiResponse(description="Deal not found"),
            409: OpenApiResponse(description="Заявку уже взял коллега (DEAL_ALREADY_CLAIMED)"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="take-and-prepare",
        permission_classes=[IsAuthenticated],
        throttle_classes=[AiDraftThrottle],
    )
    def take_and_prepare(self, request, pk=None):
        """Thin wrapper (Rule 8): ONE service call orchestrates claim+stage+КП; the view only
        maps error codes and, for the AI mode, enqueues the existing draft_quote job with a
        cache-backed double-click guard (an in-flight task is returned, not re-bought)."""
        from django.core.cache import cache

        from crm.services.draft_quote import take_and_prepare_quote, validate_draft_quote_gates
        from sourcing.ai_jobs import enqueue_ai_job

        result, err = take_and_prepare_quote(int(pk), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "ONLY_SELLER_CAN_BUILD_QUOTE", "MEMBER_REQUIRED_FOR_ACTION")
                else (
                    status.HTTP_404_NOT_FOUND
                    if err in ("DEAL_NOT_FOUND",)
                    else status.HTTP_409_CONFLICT if err in ("DEAL_ALREADY_CLAIMED",) else status.HTTP_400_BAD_REQUEST
                )
            )
            return Response({"detail": err}, status=http_status)
        if result["mode"] == "quote":
            return Response({"mode": "quote", "quote_id": result["quote"].id, "deal_id": int(pk)})

        # AI mode. Double-click guard: while the first job is in flight its task_id is cached —
        # a second press re-polls the SAME job instead of paying for a second LLM pass.
        cache_key = f"draft_quote_inflight:{pk}:{request.user.id}"
        inflight_task_id = cache.get(cache_key)
        if inflight_task_id:
            return Response({"mode": "ai", "task_id": inflight_task_id}, status=status.HTTP_202_ACCEPTED)
        gate_err = validate_draft_quote_gates(int(pk), request.user)
        if gate_err:
            return Response({"detail": gate_err}, status=status.HTTP_400_BAD_REQUEST)
        response = enqueue_ai_job("draft_quote", {"deal_id": int(pk), "user_id": request.user.id}, request.user)
        if response.status_code == status.HTTP_202_ACCEPTED:
            cache.add(cache_key, response.data["task_id"], timeout=180)
            response.data["mode"] = "ai"
        return response

    @extend_schema(
        summary="Force change deal stage (admin)",
        description=(
            "Transition the deal to ANY stage, bypassing FSM validation. "
            "Admin/Manager only. Use for emergency fixes."
        ),
        request=inline_serializer(
            "ForceChangeStageRequest",
            fields={
                "stage_code": drf_serializers.CharField(),
                "reason": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            404: OpenApiResponse(description="Stage not found"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="force-change-stage",
        permission_classes=[IsAuthenticated, IsPlatformAdmin],
    )
    def force_change_stage(self, request, pk=None):
        deal = self.get_object()
        stage_code = request.data.get("stage_code")
        reason = (request.data.get("reason") or "").strip()
        if not stage_code:
            return Response({"detail": "STAGE_CODE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if not reason:
            return Response({"detail": "REASON_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        deal, error = force_transition_deal_stage(
            deal,
            stage_code,
            actor=request.user,
            reason=reason,
        )
        if error:
            code = status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(DealDetailSerializer(deal).data)

    @extend_schema(
        summary="Export deal PDF",
        description="Export PDF of the deal's active quote; 202 + off-thread render when it is not ready yet.",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF file download"),
            202: OpenApiResponse(description="PDF rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="No active quote"),
            409: OpenApiResponse(description="QUOTE_NOT_CLAIMED / FX_RATE_MISSING / QUOTE_BELOW_COST"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        """Export PDF of the deal's active quote."""
        deal = self.get_object()
        quote = deal.active_quote
        if not quote:
            return Response({"detail": "NO_ACTIVE_QUOTE"}, status=status.HTTP_404_NOT_FOUND)
        if not quote.pdf_file:
            # ARCH-03: enqueue the off-thread render + 202 instead of running WeasyPrint
            # inline; only the cheap render guards run synchronously (409 on failure).
            from crm.services import QuoteLifecycleService
            from crm.views._pdf import pdf_generating_response

            try:
                QuoteLifecycleService.assert_pdf_renderable(quote.pk)
            except ValueError as exc:
                if str(exc) in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
                    return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
                return Response({"detail": "PDF_GENERATION_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return pdf_generating_response("quote", quote.pk)
        from django.http import FileResponse

        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=f"RailTech_Quote_{deal.id}.pdf",
        )
