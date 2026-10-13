import logging
from typing import List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from notifications.emails import send_templated_email

from ..constants import KYC_VERIFIED_CODES, VerificationStatusCode
from ..models import Company, CustomUser, VerificationStatus

logger = logging.getLogger(__name__)

# KYC_VERIFIED_CODES moved to accounts.constants so the model layer can use it too
# (models cannot import services without a cycle). Re-exported here because this was
# its historical home and callers import it from this module.
__all__ = ["KYC_VERIFIED_CODES", "kyc_evidence_gaps"]


def company_kyc_verified(company_id: int) -> bool:
    """True if the company has completed KYC (rank ≥ L2) — the floor for submitting a заявка."""
    company = Company.objects.filter(pk=company_id).select_related("verification_status").first()
    if company is None or not company.verification_status_id:
        return False
    return company.verification_status.code in KYC_VERIFIED_CODES


def kyc_evidence_gaps(company: Company) -> List[str]:
    """
    Чего не хватает, чтобы считать KYC подтверждённым по доказательствам.

    Возвращает КОДЫ пробелов (`NO_DOCUMENTS`, `NO_INN`), не текст: подпись подбирает витрина
    (Rule 5). Признак живёт здесь, а не в диалоге, потому что по нему судят и сервер, и обе
    панели — до 24-08 у него было две копии, и серверная просто отсутствовала.
    """
    gaps: List[str] = []
    # Список компаний (очередь триажа) аннотирует `kyc_document_count` заранее — иначе на
    # каждую строку уходил бы отдельный запрос. Предикат при этом остаётся ОДИН.
    document_count = getattr(company, "kyc_document_count", None)
    has_documents = company.kyc_documents.exists() if document_count is None else document_count > 0
    if not has_documents:
        gaps.append("NO_DOCUMENTS")
    if not (company.inn or "").strip():
        gaps.append("NO_INN")
    return gaps


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
    - reason: required when moving DOWN (e.g. revoking to L1_UNVERIFIED) and when granting
      L2+ to a company whose evidence is incomplete (owner policy 2026-06-03)
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

    # Уровень уже такой — выйти ДО любой записи. Иначе «Отозвать верификацию» на компании,
    # которая и так в L1, писала в журнал зелёную запись об успехе (L1 → L1) и рассылала
    # владельцам письмо о смене статуса: оператор видел подтверждение действия, которого не
    # было. Сравнение `is_downgrade` строгое (`<`), и равенство проваливалось в ветку
    # ПОВЫШЕНИЯ — менять знак на `<=` нельзя, тогда подтверждение L2 → L2 поехало бы как
    # понижение. Нужен именно ранний выход (находка прогона 20-08, №13).
    if level_code == current_code:
        return None, "KYC_LEVEL_UNCHANGED"

    if require_documents and not is_downgrade and not company.kyc_documents.exists():
        return None, "KYC_DOCUMENTS_MISSING"

    # Политика владельца 2026-06-03: выдать L2+ компании без загруженных документов МОЖНО, но
    # это осознанное исключение — «предупреждение + обоснование». Обоснование до сих пор
    # требовал ОДИН диалог из четырёх (карточка компании в панели оператора), а меню строки,
    # массовое действие, аварийное действие Unfold и сырой POST по API проходили мимо: в
    # журнале оставался пустой reason у выдачи уровня, который открывает подачу заявок и
    # отправку/экспорт КП. Проверка стоит в сервисе, потому что четвёртый диалог обошёл бы и
    # пятый (находки прогона 20-08, №11 и №12).
    if not is_downgrade and LEVEL_RANK.get(level_code, 0) >= LEVEL_RANK[VerificationStatusCode.L2_VERIFIED]:
        if kyc_evidence_gaps(company) and not (reason or "").strip():
            return None, "KYC_REASON_REQUIRED_WITHOUT_EVIDENCE"

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
        event_code="company.kyc_downgraded" if is_downgrade else "company.kyc_verified",
        # Имя уровня — русская строка справочника; замороженная в журнале, она печаталась
        # в английской ленте как есть. Витрина подбирает подпись по коду, имена остаются
        # ради старых строк (ARCH-05).
        event_params={
            "company_name": company.name,
            "from_status": before_name or before_code,
            "to_status": target_status.name,
            "from_status_code": before_code,
            "to_status_code": level_code,
        },
        actor=approver,
        reason=reason,
        before={"verification_status": before_code},
        after={"verification_status": level_code},
        level="WARNING" if is_downgrade else "SUCCESS",
        company_id=company.id,
    )

    # CB-auto-populate (Phase C): a KYC upgrade gives the company its canonical identity, so any
    # offline placeholders a seller created under the same INN are now known duplicates — fold
    # their history in so the seller's book is continuous. Best-effort (never breaks verification).
    if not is_downgrade and company.inn:
        from .merge import auto_populate_history

        try:
            auto_populate_history(company, actor=approver)
        except Exception:  # noqa: BLE001 — auto-populate is a convenience; a failure must not block KYC
            logger.exception("CB-auto-populate failed for company %s", company.pk)

    # Notify owner(s) by email and in-app (only on upgrades). Deferred to
    # transaction.on_commit so a "KYC verified" email is never sent if the
    # surrounding transaction rolls back. Runs immediately when no transaction
    # is active.
    # Исход доходит до арендатора В ОБЕ СТОРОНЫ. Раньше письмо и уведомление ставились
    # ТОЛЬКО при повышении, и отзыв уровня проходил молча: арендатор видел на дашборде бейдж
    # «На проверке» с подписью «обычно 1–2 рабочих дня» — то есть ждал вердикта, который уже
    # вынесен. Причину сервер требует обязательно (`REASON_REQUIRED` выше), но она оставалась
    # в журнале, закрытом от арендатора: человек не знал ни об отказе, ни о том, что исправить.
    #
    # Эталон — Stripe ST-CANCEL-REASON: ограничение адресовано тому, кого ограничили, и
    # называет причину. Отправка отложена до `on_commit`, чтобы письмо не ушло при откате.
    company_id = company.pk
    downgrade_reason = (reason or "").strip()

    def _notify_kyc_status() -> None:
        try:
            _send_kyc_status_email(company, level_code, is_downgrade=is_downgrade, reason=downgrade_reason)
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to send KYC status email for company %s", company_id)
        try:
            _create_kyc_notification(company, level_code, is_downgrade=is_downgrade, reason=downgrade_reason)
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to create KYC notification for company %s", company_id)

    transaction.on_commit(_notify_kyc_status)
    return company, None


def _send_kyc_status_email(company: Company, level_code: str, *, is_downgrade: bool = False, reason: str = "") -> None:
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
        "reason": reason,
        "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:5173"),
    }
    template = "kyc_revoked" if is_downgrade else "kyc_verified"
    # Send one email per owner so each row in EmailLog is searchable by user.
    for owner in owners:
        send_templated_email(
            template,
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def _create_kyc_notification(
    company: Company, level_code: str, *, is_downgrade: bool = False, reason: str = ""
) -> None:
    from notifications.services import notify_user

    owners = CustomUser.objects.filter(
        memberships__company=company,
        memberships__is_primary=True,
        memberships__is_active=True,
    ).distinct()
    # Через общий `notify_user`, а не `Notification.objects.create` руками: он делает и WS-пуш,
    # которого здесь не было — отзыв уровня доходил до арендатора только опросом раз в минуту,
    # тогда как всё остальное прилетает мгновенно.
    event_code = f"{KYC_EVENT_PREFIX}_revoked" if is_downgrade else f"{KYC_EVENT_PREFIX}_verified"
    for u in owners:
        notify_user(
            user=u,
            title="Статус KYC обновлён",
            message=f"KYC для {company.name} — {level_code}",
            link="/cabinet/profile",
            type_code="WARNING" if is_downgrade else "SUCCESS",
            event_code=event_code,
            event_params={"company": company.name, "level_code": level_code, "reason": reason},
        )


#: Префикс машинных кодов событий KYC. Читатель причины и писатель события обязаны брать его
#: ОТСЮДА: до 27-08 сериализатор `/me` искал по `kyc.`, а писалось `company.kyc_downgraded` —
#: причина отказа не находилась никогда, и арендатор по-прежнему не знал, что исправить.
KYC_EVENT_PREFIX = "company.kyc"


def last_kyc_reason(company) -> str:
    """Причина последнего вердикта по KYC — из журнала, где её и записывает сервис.

    Сервер ТРЕБУЕТ причину при понижении уровня (`REASON_REQUIRED` выше), но она оставалась
    только в `ActivityLog`, закрытом от арендатора: человек знал, что ему отказали, но не знал
    почему, и подать заново было не с чего.

    У ПОДТВЕРЖДЁННОЙ компании причина не нужна и не спрашивается: `ActivityLog` — самая
    большая таблица проекта, а фильтры по коду события и непустой причине индексом не
    покрыты, так что самый частый случай («отказа не было») давал бы худший план на КАЖДОМ
    вызове `/me/` у всех пользователей ради поля, нужного единицам.
    """
    from crm.models import ActivityLog

    status_code = getattr(getattr(company, "verification_status", None), "code", None)
    if status_code in KYC_VERIFIED_CODES:
        return ""

    return (
        ActivityLog.objects.filter(entity_type="company", entity_id=company.pk, event_code__startswith=KYC_EVENT_PREFIX)
        .exclude(reason="")
        .order_by("-timestamp")
        .values_list("reason", flat=True)
        .first()
        or ""
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

    # Два разных отказа — два разных КОДА, а не один текст.
    #
    # Раньше обе проверки стояли под одним `except`, и наружу уходил `str(ValidationError)` —
    # то есть строковое представление СПИСКА: `["KYC document: file content does not match its
    # '.pdf' extension (possible spoofing)."]`. Это ломает форму ответа проекта
    # (`{"detail": "<CODE>"}`), витрина такую строку не распознаёт и печатает оператору
    # внутренний код своего HTTP-клиента — `ERR_BAD_REQUEST`. Единственная полезная
    # информация — ПОЧЕМУ файл отвергнут — выбрасывалась, и оператор грузил тот же файл снова
    # (замер 20-08). Эталон Salesforce SF-BLOCKER-NAMED: отказ называет конкретную причину.
    ext_validator = FileExtensionValidator(allowed_extensions)
    try:
        ext_validator(file_obj)
    except DjangoValidationError:
        return None, "FILE_EXTENSION_NOT_ALLOWED"

    try:
        # SEC-08: the extension + client content_type are spoofable — verify the file
        # HEADER matches its extension too (a .pdf that is really an executable/HTML is
        # rejected). KYC keeps its own stricter allowlist above; this only adds anti-spoofing.
        assert_content_matches_extension(file_obj, "KYC document")
    except DjangoValidationError:
        return None, "FILE_CONTENT_MISMATCH"

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
