"""ARCH-01 — enqueue helper + status endpoint for off-thread AI jobs.

The interactive AI views validate synchronously (cheap guards, visibility scoping),
then call `enqueue_ai_job(...)` → 202 {"task_id"}; the frontend polls
GET /api/v1/sourcing/ai-status/<task_id>/ until SUCCESS/FAILURE. Ownership is a
persistent AIJob row (mirrors ImportTask / ImportStatusView — IDOR guard, not cache).
"""

import logging
from uuid import uuid4

from celery.result import AsyncResult
from django.db import DatabaseError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .ai_spend_cap import is_ai_daily_cap_reached
from .models import AIJob
from .tasks_ai import run_ai_job

logger = logging.getLogger(__name__)


def enqueue_ai_job(feature: str, payload: dict, user) -> Response:
    """Queue one AI job on the "ai" queue and record its ownership. Returns 202 {"task_id"}.

    Ordering matters: the ownership row is created FIRST with a pre-generated task id, then
    the task is published under that id — so a failed row insert means nothing was queued
    (no orphaned paid LLM call / credit spend the user could never poll). If the publish
    itself fails, the dangling row is removed before returning 500.

    Security audit #13: a per-company daily safety cap is enforced HERE — the single choke
    every interactive AI feature passes through — BEFORE any row is written or task queued,
    so a runaway/abusive tenant hits a 429 instead of an unbounded Anthropic bill. The cap
    is generous; legitimate use never reaches it (see sourcing/ai_spend_cap.py).
    """
    if is_ai_daily_cap_reached(user):
        return Response({"detail": "AI_DAILY_CAP_REACHED"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    task_id = str(uuid4())
    try:
        AIJob.objects.create(celery_task_id=task_id, owner=user, feature=feature)
    except DatabaseError:
        logger.exception("Failed to record AI job ownership (feature=%s)", feature)
        return Response(
            {"detail": "AI_JOB_QUEUE_FAILED"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    try:
        run_ai_job.apply_async(args=[feature, payload], task_id=task_id)
    except OperationalError:
        # Celery broker unreachable — nothing ran; drop the ownership row so the id
        # doesn't dangle as an eternally-PENDING job.
        logger.exception("Failed to publish AI job (feature=%s)", feature)
        AIJob.objects.filter(celery_task_id=task_id).delete()
        return Response(
            {"detail": "AI_JOB_QUEUE_FAILED"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return Response({"task_id": task_id}, status=status.HTTP_202_ACCEPTED)


@extend_schema(
    summary="Check AI job status",
    description=(
        "Check the status of a background AI job by Celery task_id (the interactive AI "
        "endpoints return 202 + task_id — ARCH-01). Users can only check their own jobs; "
        "platform admins can check any job."
    ),
    responses={
        200: OpenApiResponse(description="Task status with the result payload when ready"),
        403: OpenApiResponse(description="No access to this task"),
    },
    tags=["Sourcing"],
)
class AIJobStatusView(APIView):
    """Status endpoint for off-thread AI jobs (mirrors ImportStatusView)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        # IDOR protection: verify job ownership via DB (not cache); platform admin bypasses.
        if not request.user.is_platform_admin:
            job_exists = AIJob.objects.filter(celery_task_id=task_id, owner=request.user).exists()
            if not job_exists:
                return Response({"detail": "TASK_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        res = AsyncResult(task_id)
        result_data = None
        if res.ready():
            raw_result = res.result
            if res.failed():
                # A hard crash (uncaught exception, time-limit, worker kill) leaves
                # res.result as an Exception instance. NEVER pass its text to the client
                # (DB error strings / SDK request ids would leak — the old sync views only
                # ever surfaced an opaque 500): log it server-side, return a stable code.
                logger.error("AI job %s failed: %s", task_id, raw_result)
                result_data = {"status": "failed", "message": "AI_JOB_FAILED"}
            elif isinstance(raw_result, dict):
                # Handlers return the exact JSON the old sync view returned — pass through.
                result_data = raw_result
            else:
                result_data = {"status": "completed"}

        return Response({"task_id": task_id, "status": res.status, "result": result_data})
