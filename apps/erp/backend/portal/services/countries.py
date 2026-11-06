"""Справочник стран и метаданных для онбординга (COUNTRY-MASK-1)."""

from typing import Any, Dict, List

from core.models import Country

COUNTRY_META: Dict[str, Dict[str, str]] = {
    "UZ": {
        "phone_code": "+998",
        "phone_mask": "+998 (99) 999-99-99",
        "phone_placeholder": "+998 90 123-45-67",
        "tax_label": "ИНН (STIR)",
        "tax_placeholder": "123456789",
        "tax_regex": r"^\d{9}$",
    },
    "KZ": {
        "phone_code": "+7",
        "phone_mask": "+7 (799) 999-99-99",
        "phone_placeholder": "+7 701 123-45-67",
        "tax_label": "БИН / ИИН",
        "tax_placeholder": "123456789012",
        "tax_regex": r"^\d{12}$",
    },
    "RU": {
        "phone_code": "+7",
        "phone_mask": "+7 (999) 999-99-99",
        "phone_placeholder": "+7 916 123-45-67",
        "tax_label": "ИНН",
        "tax_placeholder": "1234567890",
        "tax_regex": r"^\d{10}(\d{2})?$",
    },
    "CN": {
        "phone_code": "+86",
        "phone_mask": "+86 999 9999 9999",
        "phone_placeholder": "+86 138 1234 5678",
        "tax_label": "USCC (Код юрлица)",
        "tax_placeholder": "91110000000000000X",
        "tax_regex": r"^[0-9A-Z]{18}$",
    },
    "TR": {
        "phone_code": "+90",
        "phone_mask": "+90 999 999 99 99",
        "phone_placeholder": "+90 532 123 45 67",
        "tax_label": "VKN",
        "tax_placeholder": "1234567890",
        "tax_regex": r"^\d{10}$",
    },
    "BY": {
        "phone_code": "+375",
        "phone_mask": "+375 (99) 999-99-99",
        "phone_placeholder": "+375 29 123-45-67",
        "tax_label": "УНП",
        "tax_placeholder": "123456789",
        "tax_regex": r"^\d{9}$",
    },
    "KG": {
        "phone_code": "+996",
        "phone_mask": "+996 (999) 999-999",
        "phone_placeholder": "+996 555 123-456",
        "tax_label": "ИНН",
        "tax_placeholder": "12345678901234",
        "tax_regex": r"^\d{14}$",
    },
    "TJ": {
        "phone_code": "+992",
        "phone_mask": "+992 99 999 9999",
        "phone_placeholder": "+992 90 123 4567",
        "tax_label": "ИНН",
        "tax_placeholder": "123456789",
        "tax_regex": r"^\d{9}$",
    },
    "DE": {
        "phone_code": "+49",
        "phone_mask": "+49 999 9999999",
        "phone_placeholder": "+49 170 1234567",
        "tax_label": "USt-IdNr. / HRB",
        "tax_placeholder": "DE123456789",
        "tax_regex": "",
    },
    "AE": {
        "phone_code": "+971",
        "phone_mask": "+971 99 999 9999",
        "phone_placeholder": "+971 50 123 4567",
        "tax_label": "TRN",
        "tax_placeholder": "100123456700003",
        "tax_regex": r"^\d{15}$",
    },
}

DEFAULT_META = {
    "phone_code": "",
    "phone_mask": "",
    "phone_placeholder": "+...",
    "tax_label": "Рег. номер / Tax ID",
    "tax_placeholder": "Регистрационный или налоговый номер",
    "tax_regex": "",
}


def list_portal_countries() -> List[Dict[str, Any]]:
    countries = Country.objects.filter(is_active=True).order_by("sort_order", "name")
    result = []
    for c in countries:
        meta = COUNTRY_META.get(c.code, DEFAULT_META)
        result.append(
            {
                "code": c.code,
                "name": c.name,
                "alpha3": c.alpha3,
                "phone_code": meta["phone_code"],
                "phone_mask": meta["phone_mask"],
                "phone_placeholder": meta["phone_placeholder"],
                "tax_label": meta["tax_label"],
                "tax_placeholder": meta["tax_placeholder"],
                "tax_regex": meta["tax_regex"],
                "is_uzbekistan": c.code == "UZ",
            }
        )
    return result
