"""Справочник «Вид документа» входящего письма (P8, SPEC-v3 §3.2a п. 1; бенчмарк СЭД 2026-11-01 §6.3).

Типы — данные (DECISIONS 2026-10-28): письмо хранит код, названия и правило «сразу срочно» живут здесь и отдаются
`GET /api/v1/letter-kinds`; экран берёт их оттуда, своих списков не держит. Стартовый набор — константы: новый
вид — строка ниже без миграции и без правки контракта (код по шаблону `^[a-z][a-z_]{0,31}$`). Когда видов станет
больше или их будет вести администратор — таблица с тем же ответом API.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class LetterKind:
    code: str
    ru: str
    uz: str
    en: str
    urgent: bool = False  # регистрация этим видом сразу ставит «срочно»

    def names(self) -> dict[str, str]:
        return {"ru": self.ru, "uz": self.uz, "en": self.en}


KINDS: Final[tuple[LetterKind, ...]] = (
    # Требования налоговой приходят в кабинет налогоплательщика my.soliq, а не на почту; ответ — 5–10 дней (§3.2a).
    LetterKind(
        "tax_notice",
        "Требование или уведомление ГНК",
        "Soliq qo‘mitasi talabnomasi yoki xabarnomasi",
        "Tax authority demand or notice",
        urgent=True,
    ),
    LetterKind("bank", "Письмо банка", "Bank xati", "Bank letter"),
    LetterKind("supplier", "Письмо поставщика", "Yetkazib beruvchi xati", "Supplier letter"),
    LetterKind("government", "Письмо госоргана", "Davlat organi xati", "Government letter"),
    LetterKind("counterparty", "Письмо контрагента", "Kontragent xati", "Counterparty letter"),
    LetterKind("other", "Прочее", "Boshqa", "Other"),
)
BY_CODE: Final[dict[str, LetterKind]] = {kind.code: kind for kind in KINDS}
