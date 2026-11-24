"""Шаблоны писем и служебок (TPL-4, план 3.6): варианты по языкам, встроенные с «Вернуть по умолчанию», один шаблон по
умолчанию на вид, предпросмотр на бланке через общую очередь рендера. Применение шаблона только заполняет тело нового
документа — документ шаблон не хранит."""

import copy
import uuid
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, invalid_fields, not_found
from app.models import Employee, LetterTemplate
from app.schemas.documents import DocumentBody
from app.schemas.letter_templates import (
    LetterTemplateIn,
    LetterTemplateList,
    LetterTemplateOut,
    TemplateVariants,
)
from app.services import letter_body

LANGS: Final = ("ru", "uz", "en")


def _paragraphs(lang: str, lines: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "lang": lang,
        "doc": {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
                for line in lines
            ],
        },
    }


#: Встроенные шаблоны — исходник «по умолчанию»; узбекский — латиницей (ADR-0020 п. 9), формулировки правит владелец
BUILTINS: Final[dict[str, dict[str, Any]]] = {
    "business_letter": {
        "kind": "letter",
        "name": "Деловое письмо",
        "variants": {
            "ru": _paragraphs("ru", ["Уважаемые коллеги!", "", "Сообщаем следующее.", "", "С уважением,"]),
            "uz": _paragraphs("uz", ["Hurmatli hamkasblar!", "", "Quyidagilarni maʼlum qilamiz.", "", "Hurmat bilan,"]),
            "en": _paragraphs(
                "en", ["Dear colleagues,", "", "We would like to inform you of the following.", "", "Best regards,"]
            ),
        },
    },
    # ДОК-13: бывшие образцы ERP «Гарантийное письмо», «Сопроводительное письмо» и «Претензия» —
    # теперь шаблоны писем на бланке
    "guarantee_letter": {
        "kind": "letter",
        "name": "Гарантийное письмо",
        "variants": {
            "ru": _paragraphs(
                "ru",
                [
                    "Гарантийное письмо",
                    "",
                    "Настоящим гарантируем оплату по сделке в полном объёме и в согласованные сроки.",
                    "",
                    "Обязательства соответствуют коммерческому предложению.",
                    "",
                    "С уважением,",
                ],
            ),
            "uz": _paragraphs(
                "uz",
                [
                    "Kafolat xati",
                    "",
                    "Uşbu xat bilan bitim böyiça tölovni töliq hajmda "
                    "va kelişilgan muddatlarda amalga oşirişimizni kafolatlaymiz.",
                    "",
                    "Majburiyatlar tijorat taklifiga muvofiq keladi.",
                    "",
                    "Hurmat bilan,",
                ],
            ),
            "en": _paragraphs(
                "en",
                [
                    "Letter of guarantee",
                    "",
                    "We hereby guarantee payment under the deal in full and within the agreed terms.",
                    "",
                    "The obligations correspond to the commercial offer.",
                    "",
                    "Best regards,",
                ],
            ),
        },
    },
    "cover_letter": {
        "kind": "letter",
        "name": "Сопроводительное письмо",
        "variants": {
            "ru": _paragraphs(
                "ru",
                [
                    "Уважаемые коллеги!",
                    "",
                    "Направляем Вам комплект документов по сделке. Просим рассмотреть и подтвердить получение.",
                    "",
                    "С уважением,",
                ],
            ),
            "uz": _paragraphs(
                "uz",
                [
                    "Hurmatli hamkasblar!",
                    "",
                    "Bitim böyiça hujjatlar töplamini yuboramiz. "
                    "Körib çiqişingizni va olinganini tasdiqlaşingizni söraymiz.",
                    "",
                    "Hurmat bilan,",
                ],
            ),
            "en": _paragraphs(
                "en",
                [
                    "Dear colleagues,",
                    "",
                    "We are sending you the set of documents for the deal. Please review them and confirm receipt.",
                    "",
                    "Best regards,",
                ],
            ),
        },
    },
    "claim": {
        "kind": "letter",
        "name": "Претензия",
        "variants": {
            "ru": _paragraphs(
                "ru",
                [
                    "Претензия",
                    "",
                    "В рамках сделки по договору нами выявлено неисполнение обязательств.",
                    "",
                    "Требуем устранить нарушения в разумный срок.",
                    "",
                    "С уважением,",
                ],
            ),
            "uz": _paragraphs(
                "uz",
                [
                    "Daʼvo",
                    "",
                    "Şartnoma doirasidagi bitimda majburiyatlar bajarilmagani aniqlandi.",
                    "",
                    "Buzilişlarni maʼqul muddatda bartaraf etişingizni talab qilamiz.",
                    "",
                    "Hurmat bilan,",
                ],
            ),
            "en": _paragraphs(
                "en",
                [
                    "Claim",
                    "",
                    "Under the deal and the contract we have found a failure to perform obligations.",
                    "",
                    "We demand that the violations be remedied within a reasonable time.",
                    "",
                    "Best regards,",
                ],
            ),
        },
    },
    "memo": {
        "kind": "memo",
        "name": "Служебная записка",
        "variants": {
            "ru": _paragraphs("ru", ["Прошу рассмотреть следующее.", "", "Обоснование:"]),
        },
    },
}


async def ensure_builtins(session: AsyncSession) -> None:
    """Встроенные шаблоны есть в базе: недостающий добавляется; первый шаблон вида становится «по умолчанию»."""
    now = clock.now()
    for key, source in BUILTINS.items():
        has_default = await session.scalar(
            select(LetterTemplate.id).where(LetterTemplate.kind == source["kind"], LetterTemplate.is_default)
        )
        await session.execute(
            insert(LetterTemplate)
            .values(
                id=uuid.uuid4(),
                kind=source["kind"],
                name=source["name"],
                variants=copy.deepcopy(source["variants"]),
                is_default=has_default is None,
                active=True,
                builtin_key=key,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["builtin_key"], index_where=LetterTemplate.builtin_key.isnot(None))
        )


def _changed(row: LetterTemplate) -> bool:
    source = BUILTINS.get(row.builtin_key or "")
    return source is not None and row.variants != source["variants"]


def present(row: LetterTemplate) -> LetterTemplateOut:
    return LetterTemplateOut(
        id=row.id,
        kind=row.kind,
        name=row.name,
        variants={lang: row.variants[lang] for lang in LANGS if row.variants.get(lang)},
        languages=[lang for lang in LANGS if row.variants.get(lang)],
        is_default=row.is_default,
        active=row.active,
        origin="builtin" if row.builtin_key else "custom",
        changed=_changed(row),
        updated_at=row.updated_at,
    )


async def list_all(session: AsyncSession, kind: str | None = None) -> LetterTemplateList:
    await ensure_builtins(session)
    stmt = select(LetterTemplate).order_by(LetterTemplate.kind, LetterTemplate.is_default.desc(), LetterTemplate.name)
    if kind:
        stmt = stmt.where(LetterTemplate.kind == kind)
    return LetterTemplateList(items=[present(row) for row in (await session.execute(stmt)).scalars()])


async def _get(session: AsyncSession, template_id: uuid.UUID) -> LetterTemplate:
    row = await session.get(LetterTemplate, template_id, with_for_update=True)
    if row is None:
        raise not_found("Шаблон не найден.")
    return row


async def get(session: AsyncSession, template_id: uuid.UUID) -> LetterTemplateOut:
    return present(await _get(session, template_id))


def _variants(data: TemplateVariants) -> dict[str, Any]:
    """Варианты для хранения: язык тела совпадает с ключом, тело — по схеме бланка; хотя бы один язык."""
    out: dict[str, Any] = {}
    for lang in LANGS:
        body: DocumentBody | None = getattr(data, lang)
        if body is None:
            continue
        if body.lang != lang:
            raise invalid_fields("Язык текста не совпадает с вариантом.", variants=f"{lang}_lang")
        out[lang] = letter_body.clean(body)
    if not out:
        raise invalid_fields("Нужен текст хотя бы на одном языке.", variants="required")
    return out


async def _make_default(session: AsyncSession, row: LetterTemplate) -> None:
    """Шаблон по умолчанию — один на вид: сначала метка снимается с прежнего, потом ставится (уникальный индекс)."""
    await session.execute(
        update(LetterTemplate)
        .where(LetterTemplate.kind == row.kind, LetterTemplate.id != row.id, LetterTemplate.is_default)
        .values(is_default=False)
        .execution_options(synchronize_session="fetch")
    )
    row.is_default = True
    await session.flush()


async def create(session: AsyncSession, employee: Employee, data: LetterTemplateIn) -> LetterTemplateOut:
    now = clock.now()
    row = LetterTemplate(
        id=uuid.uuid4(),
        kind=data.kind,
        name=data.name.strip(),
        variants=_variants(data.variants),
        is_default=False,
        active=data.active,
        created_by=employee.crm_user_id,
        updated_by=employee.crm_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    if data.is_default:
        await _make_default(session, row)
    return present(row)


async def update_one(
    session: AsyncSession, employee: Employee, template_id: uuid.UUID, data: LetterTemplateIn
) -> LetterTemplateOut:
    row = await _get(session, template_id)
    if data.kind != row.kind:
        raise invalid_fields("Вид шаблона не меняется.", kind="immutable")
    row.name, row.variants, row.active = data.name.strip(), _variants(data.variants), data.active
    row.updated_by, row.updated_at = employee.crm_user_id, clock.now()
    if data.is_default and not row.is_default:
        await _make_default(session, row)
    elif not data.is_default and row.is_default:
        raise conflict("default_required", "Шаблон по умолчанию снимается выбором другого.")
    await session.flush()
    return present(row)


async def reset(session: AsyncSession, employee: Employee, template_id: uuid.UUID) -> LetterTemplateOut:
    """«Вернуть по умолчанию»: варианты встроенного — снова из исходника."""
    row = await _get(session, template_id)
    source = BUILTINS.get(row.builtin_key or "")
    if source is None:
        raise conflict("not_builtin", "Вернуть можно только встроенный шаблон.")
    row.variants, row.name = copy.deepcopy(source["variants"]), source["name"]
    row.updated_by, row.updated_at = employee.crm_user_id, clock.now()
    await session.flush()
    return present(row)


async def delete(session: AsyncSession, template_id: uuid.UUID) -> None:
    row = await _get(session, template_id)
    if row.builtin_key:
        raise conflict("builtin", "Встроенный шаблон не удаляется — его можно выключить или вернуть по умолчанию.")
    if row.is_default:
        raise conflict("default_required", "Сначала сделайте по умолчанию другой шаблон.")
    await session.delete(row)
    await session.flush()
