"""Структурные блоки документа как плейсхолдеры.

Зачем так. Компания должна иметь возможность править ТЕКСТ документа — этого требует любая
реальная сделка, где юрист контрагента возражает по формулировке. Но таблица позиций, блок
итогов и ссылки на сделку/договор/счёт — не текст, а данные с обязательной формой: если дать
править их свободным HTML, документ перестанет быть документом.

Эталон решает это блоками с замком (PandaDoc: «restrict editing» + «lock block position»,
снять может только администратор). Блочного редактора у нас нет, поэтому замок выражен иначе:
**блок вставляется в шаблон ОДНИМ плейсхолдером**. Компания решает, где блок стоит и какой
текст его окружает, но не то, что у него внутри. Это тот же контракт, что у PandaDoc, только
записанный токеном, а не свойством блока.
"""

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

#: Токен → человеческая подпись. Каталог один: и редактор показывает его пользователю, и
#: проверка целостности (E2) сверяется с ним, поэтому разъехаться они не могут.
DOCUMENT_BLOCKS = {
    "doc.refs": "Блок: ссылки на сделку, договор и счёт",
    "doc.items_table": "Блок: таблица позиций",
    "doc.totals": "Блок: итоги и НДС",
}

#: Скалярные значения юридического документа.
DOCUMENT_SCALARS = {
    "doc.number": "Номер документа",
    "doc.date": "Дата документа",
    "doc.total": "Сумма документа",
}


def act_block_values(act, invoice, totals, ccy: str) -> dict:
    """HTML блоков для акта. Разметка та же, что печаталась из кода, — вынесена в partials,
    чтобы у шаблона компании и у платформенного образца был ОДИН источник вёрстки."""
    return {
        "doc.refs": mark_safe(render_to_string("crm/blocks/_doc_refs.html", {"act": act, "invoice": invoice})),
        "doc.items_table": mark_safe(
            render_to_string(
                "crm/blocks/_items_table.html", {"items": invoice.items.all() if invoice else [], "ccy": ccy}
            )
        ),
        "doc.totals": mark_safe(render_to_string("crm/blocks/_totals.html", {"totals": totals})),
    }


def company_template_for(company, kind_code: str):
    """Активный шаблон компании этого вида, иначе платформенный образец, иначе None.

    Порядок — тот же, что у остальных настроек документа: своё важнее общего, а общее важнее
    пустоты. None означает «печатать из кода» — так ведут себя документы, для которых образец
    ещё не заведён.
    """
    from crm.models import DocumentTemplate

    if company is not None:
        own = (
            DocumentTemplate.objects.filter(company=company, kind__code=kind_code, is_active=True)
            .order_by("-updated_at")
            .first()
        )
        if own is not None:
            return own
    return DocumentTemplate.objects.filter(company__isnull=True, is_sample=True, kind__code=kind_code).first()


def render_document_body(body_html: str, *, blocks: dict, scalars: dict) -> str:
    """Подстановка блоков и скаляров в тело шаблона.

    Разница между ними — вопрос безопасности, а не удобства:

    * **скаляры** приходят из данных (номер, дата, сумма) и ЭКРАНИРУЮТСЯ — иначе значение с
      разметкой стало бы разметкой (XSS);
    * **блоки** сервер собрал сам из наших же partials, они уже HTML, и экранировать их значило
      бы напечатать теги буквально.

    Тело шаблона НЕ рендерится как Django-шаблон: подстановка строковая (нет SSTI), а сам
    `body_html` прошёл санитайзинг по allowlist при сохранении.
    """
    from django.utils.html import escape

    from .document_placeholders import PLACEHOLDER_RE

    def _sub(match) -> str:
        code = match.group(1).strip()
        if code in blocks:
            return str(blocks[code])
        if code in scalars:
            return escape("" if scalars[code] is None else str(scalars[code]))
        return match.group(0)

    return PLACEHOLDER_RE.sub(_sub, body_html or "")


def render_act_body(act, invoice, totals, ccy: str, template) -> str:
    """Тело акта по шаблону компании либо по платформенному образцу."""
    return render_document_body(
        template.body_html,
        blocks=act_block_values(act, invoice, totals, ccy),
        scalars={
            "doc.number": act.number,
            "doc.date": act.issued_at.strftime("%d.%m.%Y") if act.issued_at else "",
            "doc.total": act.total_amount,
        },
    )
