"""ТЕСТ-2: к чему относится уведомление — единый справочник видов (по префиксу `event_code`).

Уведомление о записи, привязанной к сделке (заявка, расчёт, КП, договор, счёт, платёж, акт, поставка), обязано нести
`deal=`: по нему шлюз `Notification.objects` решает, тестовая ли компания и можно ли слать этому сотруднику. Виды без
сделки — каталог, портал, поставщики, партнёры, служебные — перечислены явно. Охранный тест
`notifications/tests/test_delivery_guard.py` требует, чтобы каждый вид из кода был в одном из двух списков.
"""

DEAL_SCOPED_PREFIXES = (
    "deal.",
    "quote.",
    "contract.",
    "invoice.",
    "payment.",
    "act.",
    "delivery.",
    "fulfillment.",
    "calc.",
    "rfq.",
    "document.",
    "approval.",
)

COMPANY_FREE_PREFIXES = (
    "supplier_order.",
    "catalog.",
    "portal.",
    "partner.",
    "partner_contract.",
    "company.",
    "invitation.",
    "mail.",
    "price.",
    "stock.",
    "sourcing.",
    "system.",
    "admin.",
    "order.",
    "supply.",
    "integration.",
    "eds.",
    "payment_doc.",
    "product.",
    "sso.",
)


# исключения из «сделочных» префиксов: запрос цены партнёру — к сделке не привязан
COMPANY_FREE_CODES = frozenset({"rfq.partner_answered"})


def is_deal_scoped(event_code: str) -> bool:
    return event_code.startswith(DEAL_SCOPED_PREFIXES) and event_code not in COMPANY_FREE_CODES


def is_company_free(event_code: str) -> bool:
    return event_code.startswith(COMPANY_FREE_PREFIXES) or event_code in COMPANY_FREE_CODES
