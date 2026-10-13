"""История сделки говорит теми же словами, что и продукт (D3 «одно слово для одной вещи»).

Волна D3 (#491) переименовала «Контракты»→«Договоры» и «Инвойсы»→«Счета» в интерфейсе и PDF,
но таймлайн сделки печатал старое слово: у строк ActivityLog, записанных до structured
timeline (и у их RU-fallback `action`/`detail`), текст заморожен на момент записи — «Инвойс
выставлен», «Подписан контракт». Решение владельца (хендофф 31-07 §3, вариант «а»): текст
здесь ОТОБРАЖАТЕЛЬНЫЙ, а не юридический — переписать данными; `event_code` и `event_params`
не трогаются, аудиторская суть события неизменна.

Замена — по границам слов с учётом падежей, поэтому «контрактный» или номер вида «CT-…» не
пострадают. Обратная операция — no-op: исходные формулировки не восстановимы, а прямой прогон
идемпотентен (новые слова под замену не попадают).
"""

import re

from django.db import migrations

#: Пары «старая форма → новая форма» по падежам и числам; длинные формы раньше коротких.
WORD_MAP = [
    ("инвойсами", "счетами"),
    ("инвойсам", "счетам"),
    ("инвойсах", "счетах"),
    ("инвойсов", "счетов"),
    ("инвойсом", "счётом"),
    ("инвойса", "счёта"),
    ("инвойсу", "счёту"),
    ("инвойсе", "счёте"),
    ("инвойсы", "счета"),
    ("инвойс", "счёт"),
    ("контрактами", "договорами"),
    ("контрактам", "договорам"),
    ("контрактах", "договорах"),
    ("контрактов", "договоров"),
    ("контрактом", "договором"),
    ("контракта", "договора"),
    ("контракту", "договору"),
    ("контракте", "договоре"),
    ("контракты", "договоры"),
    ("контракт", "договор"),
]

_PATTERN = re.compile(
    r"\b(" + "|".join(old for old, _ in WORD_MAP) + r")\b",
    re.IGNORECASE,
)
_LOWER_MAP = dict(WORD_MAP)


def _replace_word(match: "re.Match") -> str:
    source = match.group(0)
    replacement = _LOWER_MAP[source.lower()]
    if source[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def rewrite_text(text: str) -> str:
    """Пословная замена с сохранением регистра первой буквы («Инвойс»→«Счёт», «инвойс»→«счёт»)."""
    return _PATTERN.sub(_replace_word, text or "")


def rewrite(apps, schema_editor):
    log_model = apps.get_model("crm", "ActivityLog")
    queryset = log_model.objects.filter(action__iregex=r"инвойс|контракт") | log_model.objects.filter(
        detail__iregex=r"инвойс|контракт"
    )
    batch = []
    for row in queryset.only("id", "action", "detail").iterator(chunk_size=500):
        new_action = rewrite_text(row.action)
        new_detail = rewrite_text(row.detail)
        if new_action != row.action or new_detail != row.detail:
            row.action = new_action
            row.detail = new_detail
            batch.append(row)
        if len(batch) >= 500:
            log_model.objects.bulk_update(batch, ["action", "detail"])
            batch = []
    if batch:
        log_model.objects.bulk_update(batch, ["action", "detail"])


class Migration(migrations.Migration):
    dependencies = [("crm", "0085_invoice_contract_samples_act_signatures")]
    operations = [migrations.RunPython(rewrite, migrations.RunPython.noop)]
