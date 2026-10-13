"""E4 — библиотека согласованных формулировок (spec-wording-library-e4-2026-08-01).

Playbook-канон (Ironclad fallback positions, DocuSign playbook): юрист компании заранее
готовит именованные редакции пункта, менеджер в переговорах по конкретному договору
ВЫБИРАЕТ из них — а не сочиняет текст и не правит шаблон всей компании. Red-line эскалации
осознанно нет (PRODUCT RULE 2 — никаких новых гейтов без запроса владельца).
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from ..document_wording import DOCUMENT_WORDING_DEFAULTS, resolve_wording
from ..models import ActivityLog, CompanyWordingVariant

#: Поля, которые выбираются на договоре. Оговорка акта фиксируется при выпуске и на
#: конкретном акте не переигрывается (акт рождается выпущенным).
CONTRACT_WORDING_FIELDS = (
    "contract_acceptance_text",
    "contract_liability_text",
    "contract_extra_terms_text",
)


def _assert_known_field(field: str) -> None:
    if field not in DOCUMENT_WORDING_DEFAULTS:
        raise ValidationError("WORDING_FIELD_UNKNOWN")


@transaction.atomic
def create_variant(company, user, *, field: str, title: str, text: str):
    """Новый согласованный вариант. Право — то же, что у формулировок D1 (settings.edit),
    гейт проверяет вьюха тем же способом, что CRUD шаблонов документов."""
    _assert_known_field(field)
    if not (title or "").strip():
        raise ValidationError("WORDING_TITLE_REQUIRED")
    if not (text or "").strip():
        raise ValidationError("WORDING_TEXT_REQUIRED")
    if CompanyWordingVariant.objects.filter(company=company, field=field, title=title.strip()).exists():
        raise ValidationError("WORDING_TITLE_TAKEN")
    return CompanyWordingVariant.objects.create(
        company=company, field=field, title=title.strip(), text=text, created_by=user
    )


@transaction.atomic
def update_variant(variant, *, title=None, text=None):
    fields = ["updated_at"]
    if title is not None:
        if not title.strip():
            raise ValidationError("WORDING_TITLE_REQUIRED")
        clash = CompanyWordingVariant.objects.filter(
            company=variant.company, field=variant.field, title=title.strip()
        ).exclude(pk=variant.pk)
        if clash.exists():
            raise ValidationError("WORDING_TITLE_TAKEN")
        variant.title = title.strip()
        fields.append("title")
    if text is not None:
        if not text.strip():
            raise ValidationError("WORDING_TEXT_REQUIRED")
        variant.text = text
        fields.append("text")
    variant.save(update_fields=fields)
    return variant


def _contract_is_signed(contract) -> bool:
    return bool(contract.manager_signer_id or contract.client_signer_id)


@transaction.atomic
def select_contract_wording(contract, actor, *, field: str, variant_id):
    """Выбор редакции пункта для ЭТОГО договора: согласованный вариант либо возврат к
    дефолту компании (variant_id=None). Только пока договор не подписан ни одной стороной —
    подписанный текст неприкосновенен (двусторонний документ, G2)."""
    from accounts.services import is_seller
    from accounts.services.permissions import seller_company_routed_to_deal

    from .quotes import _quote_seller_company

    if not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if not (getattr(actor, "is_superuser", False) or seller_company_routed_to_deal(actor, contract.deal_id)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if field not in CONTRACT_WORDING_FIELDS:
        return None, "WORDING_FIELD_UNKNOWN"
    if _contract_is_signed(contract):
        return None, "CONTRACT_ALREADY_SIGNED"

    seller_company = _quote_seller_company(contract.quote) if contract.quote_id else None
    if variant_id is None:
        # Возврат к дефолту компании (профиль → платформа) — «стандартная редакция» плейбука.
        from accounts.models import CompanyDocumentProfile

        profile = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
        text = resolve_wording(profile, field)
        chosen_title = ""
    else:
        variant = CompanyWordingVariant.objects.filter(pk=variant_id, company=seller_company, field=field).first()
        if variant is None:
            return None, "WORDING_VARIANT_NOT_FOUND"
        text = variant.text
        chosen_title = variant.title

    selections = dict(contract.wording_selections or {})
    selections[field] = text
    contract.wording_selections = selections
    # Кэшированный PDF печатал прежнюю редакцию — сбросить; скачивание отрендерит заново.
    if contract.pdf_file:
        contract.pdf_file.delete(save=False)
        contract.pdf_file = None
    contract.save(update_fields=["wording_selections", "pdf_file", "updated_at"])
    ActivityLog.objects.create(
        action="Формулировка договора изменена",
        detail=f"Договор {contract.number}: {field} → {chosen_title or 'стандартная редакция'}",
        event_code="contract.wording_changed",
        # `field` — машинный код пункта, витрина подбирает к нему подпись. Заголовок варианта
        # (`variant`) — пользовательский текст, он не переводится; `variant_code=STANDARD`
        # говорит витрине, что выбрана стандартная редакция и подпись у неё своя (ARCH-05).
        event_params={
            "number": contract.number,
            "field": field,
            "variant": chosen_title,
            "variant_code": "CUSTOM" if chosen_title else "STANDARD",
        },
        user=actor,
        level="INFO",
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    return contract, None
