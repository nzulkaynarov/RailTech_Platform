"""Company identity resolution & merge (CRM Phase C, spec-remaining-2026-07-07 §2.1/§2.0).

A seller records an offline client `Company(is_registered=False, stated_inn=…)`. When that real
company later self-registers or is KYC-verified with a canonical `inn`, the offline placeholder is
a DUPLICATE of the real account. Merging folds the placeholder's history (contacts, deals, activity
timeline, relationship edges) onto the surviving real company so the seller's book stays continuous
and the buyer isn't split across two Company rows.

Safe direction only: we ONLY ever fold an OFFLINE placeholder INTO a survivor. A registered company
carries members / subscription / offers / entitlements that must never be silently moved, so a
registered source is refused. `Company.inn` stays unique (the survivor keeps it).
"""

import logging
from typing import Optional, Tuple

from django.db import transaction

from ..models import Company

logger = logging.getLogger(__name__)


def find_offline_duplicates(company: Company):
    """Offline placeholder companies whose `stated_inn` matches this company's canonical `inn`.

    These are the seller-created duplicates to fold into `company` once its real identity is known.
    Empty when the company has no canonical INN yet (nothing to match on).
    """
    inn = (company.inn or "").strip()
    if not inn:
        return Company.objects.none()
    return Company.objects.filter(is_registered=False, stated_inn=inn).exclude(pk=company.pk)


def _source_has_account(duplicate: Company) -> bool:
    """A placeholder must be a bare offline stub. If it somehow carries account artefacts
    (members / subscription / offers / entitlements / KYC docs), refuse to merge — those belong
    to a real tenant and moving them silently would be destructive."""
    from catalog.models import Product, SupplierOffer

    if duplicate.members.exists():
        return True
    if duplicate.entitlements.exists() or duplicate.kyc_documents.exists():
        return True
    if hasattr(duplicate, "subscription") and duplicate.subscription is not None:
        return True
    if SupplierOffer.objects.filter(supplier=duplicate).exists():
        return True
    if Product.objects.filter(owner_company=duplicate).exists():
        return True
    return False


def _merge_relationship_edges(survivor: Company, duplicate: Company) -> None:
    """Re-point every edge that references the duplicate onto the survivor, deduping against the
    UniqueConstraint(owner_company, counterparty_company, direction). On a conflict the surviving
    edge absorbs the duplicate's rollups and the widest interaction window."""
    from crm.models import CounterpartyRelationship
    from crm.services.relationships import recompute_rollups_for_edge

    dup_edges = list(
        CounterpartyRelationship.objects.filter(owner_company=duplicate)
        | CounterpartyRelationship.objects.filter(counterparty_company=duplicate)
    )
    touched_ids = set()
    for edge in dup_edges:
        new_owner = survivor.id if edge.owner_company_id == duplicate.id else edge.owner_company_id
        new_counterparty = survivor.id if edge.counterparty_company_id == duplicate.id else edge.counterparty_company_id
        if new_owner == new_counterparty:
            # A self-edge would result (owner and counterparty both became the survivor) — drop it.
            edge.delete()
            continue
        existing = CounterpartyRelationship.objects.filter(
            owner_company_id=new_owner, counterparty_company_id=new_counterparty, direction=edge.direction
        ).first()
        if existing:
            # Fold the duplicate edge into the existing survivor edge (widest window; rollups get
            # recomputed from source rows afterwards, so no double counting).
            if edge.first_interaction_at and (
                existing.first_interaction_at is None or edge.first_interaction_at < existing.first_interaction_at
            ):
                existing.first_interaction_at = edge.first_interaction_at
            if edge.last_interaction_at and (
                existing.last_interaction_at is None or edge.last_interaction_at > existing.last_interaction_at
            ):
                existing.last_interaction_at = edge.last_interaction_at
            existing.save(update_fields=["first_interaction_at", "last_interaction_at", "updated_at"])
            edge.delete()
            touched_ids.add(existing.id)
        else:
            edge.owner_company_id = new_owner
            edge.counterparty_company_id = new_counterparty
            edge.save(update_fields=["owner_company", "counterparty_company", "updated_at"])
            touched_ids.add(edge.id)
    # Rollups depend on deals, which we re-parent BEFORE calling this — recompute so the moved
    # deals count under the survivor edge.
    for edge in CounterpartyRelationship.objects.filter(id__in=touched_ids):
        recompute_rollups_for_edge(edge)


@transaction.atomic
def merge_companies(
    survivor: Company,
    duplicate: Company,
    actor=None,
    reason: str = "",
) -> Tuple[Optional[Company], Optional[str]]:
    """Fold an offline `duplicate` Company into `survivor`. Returns (survivor, error_code)."""
    from core.audit import log_admin_action
    from crm.models import ActivityLog, ChargeTemplate, Deal, DocumentSequence
    from sourcing.models import Attachment

    if survivor.pk == duplicate.pk:
        return None, "MERGE_SAME_COMPANY"
    if duplicate.is_registered:
        return None, "MERGE_SOURCE_REGISTERED"
    if _source_has_account(duplicate):
        return None, "MERGE_SOURCE_HAS_ACCOUNT"

    # Re-parent contacts, deduping by email against contacts the survivor already has.
    survivor_emails = {(email or "").lower() for email in survivor.contacts.values_list("email", flat=True) if email}
    for contact in list(duplicate.contacts.all()):
        if contact.email and contact.email.lower() in survivor_emails:
            contact.delete()  # survivor already reachable at this address
        else:
            contact.is_primary = False  # the survivor keeps its own primary
            contact.company = survivor
            contact.save(update_fields=["company", "is_primary"])

    # Re-parent the direct one-to-many history. Deals must move BEFORE edge rollups recompute.
    Deal.objects.filter(company=duplicate).update(company=survivor)
    ActivityLog.objects.filter(company=duplicate).update(company=survivor)
    Attachment.objects.filter(company=duplicate).update(company=survivor)
    ChargeTemplate.objects.filter(company=duplicate).update(company=survivor)
    DocumentSequence.objects.filter(company=duplicate).update(company=survivor)

    _merge_relationship_edges(survivor, duplicate)

    dup_id, dup_name = duplicate.id, duplicate.name
    duplicate.delete()

    log_admin_action(
        entity_type="company",
        entity_id=survivor.id,
        action="Слияние дубля компании",
        detail=f"Дубль #{dup_id} «{dup_name}» влит в «{survivor.name}»",
        event_code="company.merged",
        event_params={"duplicate_id": dup_id, "duplicate_name": dup_name, "survivor_name": survivor.name},
        actor=actor,
        reason=reason,
        after={"merged_from_id": dup_id, "merged_from_name": dup_name},
        level="WARNING",
        company_id=survivor.id,
    )
    logger.info("Merged offline company #%s into #%s", dup_id, survivor.id)
    return survivor, None


def auto_populate_history(company: Company, actor=None) -> int:
    """Fold any offline duplicates (by INN) into `company` — the CB-auto-populate step.

    Called after a company gains a canonical identity (KYC verify). Best-effort: a merge that
    fails a guard (e.g. a duplicate that unexpectedly carries an account) is skipped, not fatal —
    identifying the real company must never break on a stray placeholder. Returns merge count.
    """
    merged = 0
    for duplicate in list(find_offline_duplicates(company)):
        _survivor, error = merge_companies(company, duplicate, actor=actor, reason="CB-auto-populate по ИНН")
        if error:
            logger.warning("auto_populate_history: skipped duplicate #%s → #%s (%s)", duplicate.id, company.id, error)
        else:
            merged += 1
    return merged
