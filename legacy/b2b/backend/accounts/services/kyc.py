import logging
from typing import List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from notifications.emails import send_templated_email

from ..constants import VerificationStatusCode
from ..models import Company, CustomUser, VerificationStatus

logger = logging.getLogger(__name__)

# ADR-0006 Phase E — the KYC floor. A company completes KYC at L2; below it can register + browse
# + build a DRAFT заявка, but not SUBMIT it (or otherwise trade). This makes «после KYC = минимум»
# real on the BACKEND (it was FE-cosmetic only — the Layer-0 gap).
KYC_VERIFIED_CODES = frozenset({VerificationStatusCode.L2_VERIFIED, VerificationStatusCode.L3_CONTRACTED})


def company_kyc_verified(company_id: int) -> bool:
    """True if the company has completed KYC (rank ≥ L2) — the floor for submitting a заявка."""
    company = Company.objects.filter(pk=company_id).select_related("verification_status").first()
    if company is None or not company.verification_status_id:
        return False
    return company.verification_status.code in KYC_VERIFIED_CODES


def verify_company_kyc(
    company: Company,
    approver: CustomUser,
    level_code: str = VerificationStatusCode.L2_VERIFIED,
    require_documents: bool = True,
    reason: str = "",
) -> Tuple[Optional[Company], Optional[str]]:
    """
    Move a company through KYC verification levels (L1 → L2 → L3).

    - level_code: target VerificationStatus.code
    - require_documents: when True, refuse to verify if no KYC documents uploaded
    - reason: required when moving DOWN (e.g. revoking to L1_UNVERIFIED)
    Returns: (company, error_message_or_None)
    """
    target_status = VerificationStatus.objects.filter(code=level_code).first()
    if not target_status:
        return None, "VERIFICATION_STATUS_NOT_FOUND"

    # Downgrades/revokes must carry a reason for audit purposes.
    LEVEL_RANK = {
        VerificationStatusCode.L1_UNVERIFIED: 0,
        VerificationStatusCode.PROFILE_SUBMITTED: 1,
        VerificationStatusCode.L2_VERIFIED: 2,
        VerificationStatusCode.L3_CONTRACTED: 3,
    }
    current_code = (
        company.verification_status.code if company.verification_status_id else VerificationStatusCode.L1_UNVERIFIED
    )
    is_downgrade = LEVEL_RANK.get(level_code, 0) < LEVEL_RANK.get(current_code, 0)
    if is_downgrade and not (reason or "").strip():
        return None, "REASON_REQUIRED"

    if require_documents and not is_downgrade and not company.kyc_documents.exists():
        return None, "KYC_DOCUMENTS_MISSING"

    before_code = current_code
    before_name = company.verification_status.name if company.verification_status_id else ""
    company.verification_status = target_status
    # Keep the denormalised is_verified flag consistent with the status — L2+ is
    # "verified". Without this the /me/ payload could show is_verified=False next
    # to verification_status_code="L2_VERIFIED" (checkup 2026-06-10).
    company.is_verified = LEVEL_RANK.get(level_code, 0) >= LEVEL_RANK[VerificationStatusCode.L2_VERIFIED]
    company.save(update_fields=["verification_status", "is_verified"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="company",
        entity_id=company.id,
        action="KYC: понижение уровня" if is_downgrade else "KYC: подтверждение",
        detail=f"{company.name}: {before_name or before_code} → {target_status.name}",
        actor=approver,
        reason=reason,
        before={"verification_status": before_code},
        after={"verification_status": level_code},
        level="WARNING" if is_downgrade else "SUCCESS",
        company_id=company.id,
    )

    # Notify owner(s) by email and in-app (only on upgrades). Deferred to
    # transaction.on_commit so a "KYC verified" email is never sent if the
    # surrounding transaction rolls back. Runs immediately when no transaction
    # is active.
    if not is_downgrade:
        company_id = company.pk

        def _notify_kyc_status() -> None:
            try:
                _send_kyc_status_email(company, level_code)
            except (OSError, RuntimeError, ValueError):
                logger.exception("Failed to send KYC status email for company %s", company_id)
            try:
                _create_kyc_notification(company, level_code)
            except (OSError, RuntimeError, ValueError):
                logger.exception("Failed to create KYC notification for company %s", company_id)

        transaction.on_commit(_notify_kyc_status)
    return company, None


def _send_kyc_status_email(company: Company, level_code: str) -> None:
    owners = list(
        CustomUser.objects.filter(
            memberships__company=company,
            memberships__is_primary=True,
            memberships__is_active=True,
        ).distinct()
    )
    if not owners:
        return
    context = {
        "company_name": company.name,
        "company_inn": company.inn,
        "level_code": level_code,
        "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:5173"),
    }
    # Send one email per owner so each row in EmailLog is searchable by user.
    for owner in owners:
        send_templated_email(
            "kyc_verified",
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def _create_kyc_notification(company: Company, level_code: str) -> None:
    from notifications.models import Notification, NotificationType

    owners = CustomUser.objects.filter(
        memberships__company=company,
        memberships__is_primary=True,
        memberships__is_active=True,
    ).distinct()
    nt = NotificationType.objects.filter(code="SUCCESS").first()
    for u in owners:
        Notification.objects.create(
            user=u,
            type=nt,
            title="Статус KYC обновлён",
            message=f"KYC для {company.name} — {level_code}",
            link="/cabinet/profile",
        )


def bulk_verify_kyc(
    companies: QuerySet[Company],
    approver: CustomUser,
    level_code: str = VerificationStatusCode.L2_VERIFIED,
    reason: str = "",
) -> Tuple[int, List[dict]]:
    """
    Bulk wrapper around verify_company_kyc for admin actions.

    Returns: (approved_count, list_of_skipped_reports [{company_id, name, error}])
    """
    approved = 0
    skipped: List[dict] = []
    for company in companies:
        # Owner decision 2026-06-03: KYC approval no longer requires uploaded docs.
        _, error = verify_company_kyc(
            company,
            approver,
            level_code,
            require_documents=False,
            reason=reason,
        )
        if error:
            skipped.append({"company_id": company.id, "name": company.name, "error": error})
        else:
            approved += 1
    return approved, skipped


def upload_kyc_document(
    company: Company,
    file_obj,
    doc_type_code: str = "OTHER",
) -> Tuple[Optional["KYCDocument"], Optional[str]]:  # noqa: F821
    """
    Upload a KYC document for a company with file validation.
    Returns: (document, error_or_None)
    """
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import FileExtensionValidator

    from core.validators import assert_content_matches_extension

    from ..models import KYCDocType, KYCDocument

    allowed_extensions = ["pdf", "jpg", "jpeg", "png", "doc", "docx"]
    max_size = 10 * 1024 * 1024  # 10MB

    if file_obj.size > max_size:
        return None, "FILE_TOO_LARGE"

    ext_validator = FileExtensionValidator(allowed_extensions)
    try:
        ext_validator(file_obj)
        # SEC-08: the extension + client content_type are spoofable — verify the file
        # HEADER matches its extension too (a .pdf that is really an executable/HTML is
        # rejected). KYC keeps its own stricter allowlist above; this only adds anti-spoofing.
        assert_content_matches_extension(file_obj, "KYC document")
    except DjangoValidationError as e:
        return None, str(e)

    d_type = KYCDocType.objects.filter(code=doc_type_code).first()
    doc = KYCDocument.objects.create(
        company=company,
        file=file_obj,
        doc_type=d_type,
        original_filename=file_obj.name,
    )
    return doc, None


def delete_kyc_document(
    company: Company,
    doc_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Delete a KYC document belonging to a company.
    Returns: (success, error_or_None)
    """
    from ..models import KYCDocument

    doc = KYCDocument.objects.filter(company=company, id=doc_id).first()
    if not doc:
        return False, "Document not found"
    doc.file.delete(save=False)
    doc.delete()
    return True, None
