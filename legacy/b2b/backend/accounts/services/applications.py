import logging
from typing import List, Optional, Tuple

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from notifications.emails import send_templated_email

from ..models import CompanyRoleApplication, CustomUser
from .subscriptions import ensure_trial_subscription

logger = logging.getLogger(__name__)


def approve_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """
    Approve a CompanyRoleApplication: validate required documents per type,
    set status to APPROVED, attach the requested CompanyType to the company.

    Returns: (application, error_message_or_None)
    """
    if application.status not in ("PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"):
        return None, "ROLE_APPLICATION_CANNOT_APPROVE"

    requested_code = application.requested_type.code
    if requested_code == "SUPPLIER":
        if not application.contract_file or not application.nda_file:
            return None, "ROLE_APPLICATION_MISSING_CONTRACT_NDA"
    elif requested_code == "MANUFACTURER":
        if not application.partnership_agreement:
            return None, "ROLE_APPLICATION_MISSING_PARTNERSHIP"

    before_status = application.status
    application.status = "APPROVED"
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    application.company.types.add(application.requested_type)

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="role_application",
        entity_id=application.id,
        action="Заявка на роль одобрена",
        detail=f"{application.company.name} → {application.requested_type.name}",
        actor=reviewer,
        before={"status": before_status},
        after={"status": "APPROVED"},
        level="SUCCESS",
    )
    log_admin_action(
        entity_type="company",
        entity_id=application.company_id,
        action=f"Добавлена роль: {application.requested_type.code}",
        detail=f"Одобрена заявка #{application.id}",
        actor=reviewer,
        after={"added_type": application.requested_type.code},
        level="SUCCESS",
    )

    # Auto-create TRIAL subscription for SUPPLIER / MANUFACTURER — 30 days
    if requested_code in ("SUPPLIER", "MANUFACTURER"):
        try:
            ensure_trial_subscription(application.company)
        except Exception:
            logger.exception("Failed to create trial subscription for company %s", application.company_id)

    # Notify applicant
    try:
        _send_role_application_email(application, approved=True)
    except Exception:
        logger.exception("Failed to send role application approval email for application %s", application.pk)

    return application, None


def _send_role_application_email(app: CompanyRoleApplication, approved: bool) -> None:
    owners = list(
        CustomUser.objects.filter(
            memberships__company=app.company,
            memberships__is_primary=True,
            memberships__is_active=True,
        ).distinct()
    )
    if not owners:
        return
    template = "role_application_approved" if approved else "role_application_rejected"
    context = {
        "company_name": app.company.name,
        "requested_type_name": app.requested_type.name,
        "review_notes": app.review_notes or "",
        "trial_granted": approved and app.requested_type.code in ("SUPPLIER", "MANUFACTURER"),
        "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:5173"),
    }
    for owner in owners:
        send_templated_email(
            template,
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def reject_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
    reason: str = "",
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """Reject a CompanyRoleApplication. Reason is required for audit. Returns (app, error_or_None)."""
    if application.status not in ("PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"):
        return None, "ROLE_APPLICATION_CANNOT_REJECT"
    if not (reason or "").strip():
        return None, "REASON_REQUIRED"

    before_status = application.status
    application.status = "REJECTED"
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.review_notes = reason
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes", "updated_at"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="role_application",
        entity_id=application.id,
        action="Заявка на роль отклонена",
        detail=f"{application.company.name} → {application.requested_type.name}",
        actor=reviewer,
        reason=reason,
        before={"status": before_status},
        after={"status": "REJECTED"},
        level="WARNING",
    )

    try:
        _send_role_application_email(application, approved=False)
    except Exception:
        logger.exception("Failed to send role application rejection email for application %s", application.pk)

    return application, None


def bulk_approve_role_applications(
    applications: QuerySet[CompanyRoleApplication],
    reviewer: CustomUser,
) -> Tuple[int, List[str]]:
    """Bulk approve. Returns (approved_count, list_of_error_messages)."""
    approved = 0
    errors: List[str] = []
    pending = applications.filter(status__in=["PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"])
    for app in pending:
        _, error = approve_role_application(app, reviewer)
        if error:
            errors.append(error)
        else:
            approved += 1
    return approved, errors


def bulk_reject_role_applications(
    applications: QuerySet[CompanyRoleApplication],
    reviewer: CustomUser,
) -> int:
    """Bulk reject. Returns count of rejected applications."""
    pending = applications.filter(status__in=["PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"])
    rejected = 0
    for app in pending:
        _, error = reject_role_application(app, reviewer)
        if not error:
            rejected += 1
    return rejected
