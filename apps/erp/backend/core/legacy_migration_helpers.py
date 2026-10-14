"""Legacy migration helper functions for regression testing and historical data fixups.

These functions were originally part of one-off data migrations in legacy B2B.
They are preserved here so historical regression tests continue to pass without
relying on deleted 00xx migration files.
"""

import re
from collections import defaultdict

STUB_TO_CANONICAL_UOM = {
    "кг": "KG",
    "компл": "SET",
    "м": "M",
    "т": "T",
    "шт": "PCS",
}

TYPO_FIXES = {"Безопастность": "Безопасность"}


def dedupe_uom_stubs(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        UnitOfMeasure = apps.get_model("core", "UnitOfMeasure")
    except LookupError:
        try:
            UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")
        except LookupError:
            return

    for stub_code, canonical_code in STUB_TO_CANONICAL_UOM.items():
        stub = UnitOfMeasure.objects.filter(code=stub_code).first()
        canonical = UnitOfMeasure.objects.filter(code=canonical_code).first()
        if not stub or not canonical or stub.pk == canonical.pk:
            continue
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if getattr(field, "many_to_one", False) and field.related_model is UnitOfMeasure:
                    model._default_manager.filter(**{field.name: stub}).update(**{field.name: canonical})
        stub.delete()


def _norm(name):
    return (name or "").strip().lower()


def dedupe_taxonomy(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    Category = apps.get_model("catalog", "Category")
    try:
        EquipmentGroup = apps.get_model("catalog", "EquipmentGroup")
    except LookupError:
        EquipmentGroup = None
    Product = apps.get_model("catalog", "Product")

    for wrong, right in TYPO_FIXES.items():
        Category.objects.filter(name=wrong).update(name=right)
        if EquipmentGroup is not None:
            EquipmentGroup.objects.filter(name=wrong).update(name=right)

    cat_groups = defaultdict(list)
    for cid, cname in Category.objects.order_by("id").values_list("id", "name"):
        cat_groups[_norm(cname)].append(cid)
    for ids in cat_groups.values():
        if len(ids) < 2:
            continue
        canonical_id, dup_ids = ids[0], ids[1:]
        Category.objects.filter(parent_id__in=dup_ids).update(parent_id=canonical_id)
        Product.objects.filter(category_id__in=dup_ids).update(category_id=canonical_id)
        Category.objects.filter(id__in=dup_ids).delete()

    if EquipmentGroup is not None:
        eg_groups = defaultdict(list)
        for gid, gname in EquipmentGroup.objects.order_by("id").values_list("id", "name"):
            eg_groups[_norm(gname)].append(gid)
        for ids in eg_groups.values():
            if len(ids) < 2:
                continue
            canonical_id, dup_ids = ids[0], ids[1:]
            EquipmentGroup.objects.filter(parent_id__in=dup_ids).update(parent_id=canonical_id)
            for product in Product.objects.filter(equipment_groups__id__in=dup_ids).distinct():
                product.equipment_groups.remove(*dup_ids)
                product.equipment_groups.add(canonical_id)
            EquipmentGroup.objects.filter(id__in=dup_ids).delete()


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
    return _PATTERN.sub(_replace_word, text or "")


def rewrite_activity_logs(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        log_model = apps.get_model("sales", "ActivityLog")
    except LookupError:
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


def null_out_never_applied_margins(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        QuoteItem = apps.get_model("sales", "QuoteItem")
    except LookupError:
        QuoteItem = apps.get_model("crm", "QuoteItem")

    QuoteItem.objects.update(margin_percent=None)


def restore_zero_margins(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        QuoteItem = apps.get_model("sales", "QuoteItem")
    except LookupError:
        QuoteItem = apps.get_model("crm", "QuoteItem")

    QuoteItem.objects.filter(margin_percent__isnull=True).update(margin_percent=0)


def backfill_position(apps=None, schema_editor=None):
    if schema_editor is not None:
        schema_editor.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crm_quoteitem') THEN
                    UPDATE crm_quoteitem AS qi
                    SET position = sub.rn - 1
                    FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY quote_id ORDER BY id) AS rn
                        FROM crm_quoteitem
                    ) AS sub
                    WHERE qi.id = sub.id;
                ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sales_quoteitem') THEN
                    UPDATE sales_quoteitem AS qi
                    SET position = sub.rn - 1
                    FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY quote_id ORDER BY id) AS rn
                        FROM sales_quoteitem
                    ) AS sub
                    WHERE qi.id = sub.id;
                END IF;
            END $$;
            """
        )
    else:
        if apps is None:
            from django.apps import apps as django_apps

            apps = django_apps
        try:
            QuoteItem = apps.get_model("sales", "QuoteItem")
        except LookupError:
            QuoteItem = apps.get_model("crm", "QuoteItem")
        for quote_id in QuoteItem.objects.values_list("quote_id", flat=True).distinct():
            for idx, item in enumerate(QuoteItem.objects.filter(quote_id=quote_id).order_by("id")):
                if item.position != idx:
                    QuoteItem.objects.filter(pk=item.pk).update(position=idx)


def fix_document_currencies(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        Contract = apps.get_model("sales", "Contract")
    except LookupError:
        Contract = apps.get_model("crm", "Contract")

    try:
        Invoice = apps.get_model("finance", "Invoice")
    except LookupError:
        Invoice = apps.get_model("crm", "Invoice")

    for contract in Contract.objects.select_related("quote").exclude(quote__isnull=True).iterator():
        correct_currency_id = contract.quote.quote_currency_id
        if contract.currency_id == correct_currency_id:
            continue
        contract.currency_id = correct_currency_id
        contract.pdf_file = ""
        contract.save(update_fields=["currency", "pdf_file"])

    for invoice in (
        Invoice.objects.select_related("contract__quote")
        .exclude(contract__isnull=True)
        .exclude(contract__quote__isnull=True)
        .iterator()
    ):
        correct_currency_id = invoice.contract.quote.quote_currency_id
        if invoice.currency_id == correct_currency_id:
            continue
        invoice.currency_id = correct_currency_id
        invoice.pdf_file = ""
        invoice.save(update_fields=["currency", "pdf_file"])


_DOCS = [("CT", "CT", "Contract"), ("INV", "INV", "Invoice"), ("ACT", "ACT", "Act")]
_PAT = re.compile(r"^([A-Z]+)-(\d{4})-(\d+)$")


def backfill_sequences(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        DocumentSequence = apps.get_model("documents", "DocumentSequence")
    except LookupError:
        DocumentSequence = apps.get_model("crm", "DocumentSequence")

    for doc_type, prefix, model_name in _DOCS:
        try:
            if model_name == "Contract":
                Model = apps.get_model("sales", model_name)
            elif model_name in ("Invoice", "Act"):
                Model = apps.get_model("finance", model_name)
            else:
                Model = apps.get_model("crm", model_name)
        except LookupError:
            Model = apps.get_model("crm", model_name)

        max_by_year = {}
        for number in Model.objects.values_list("number", flat=True):
            match = _PAT.match((number or "").strip())
            if not match or match.group(1) != prefix:
                continue
            year, suffix = int(match.group(2)), int(match.group(3))
            if suffix > max_by_year.get(year, 0):
                max_by_year[year] = suffix
        for year, max_suffix in max_by_year.items():
            seq = DocumentSequence.objects.get_or_create(doc_type=doc_type, year=year, defaults={"last_value": 0})[0]
            if seq.last_value < max_suffix:
                seq.last_value = max_suffix
                seq.save(update_fields=["last_value"])


PARTICIPATION_BY_LABEL = {
    "Руководитель": "HEAD",
    "Согласовант": "APPROVER",
    "Для информации": "INFORMED",
}

STAGE_EVENTS = ("deal.stage_changed", "deal.stage_changed_force")
KYC_EVENTS = ("company.kyc_verified", "company.kyc_downgraded")


def _fill(params: dict, key: str, value) -> bool:
    if not value or params.get(key):
        return False
    params[key] = value
    return True


def backfill_activity_params(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        ActivityLog = apps.get_model("sales", "ActivityLog")
    except LookupError:
        ActivityLog = apps.get_model("crm", "ActivityLog")

    try:
        CompanyType = apps.get_model("parties", "CompanyType")
    except LookupError:
        CompanyType = apps.get_model("accounts", "CompanyType")

    role_code_by_name = {name: code for code, name in CompanyType.objects.values_list("code", "name")}

    updated = []
    rows = ActivityLog.objects.filter(
        event_code__in=[*STAGE_EVENTS, *KYC_EVENTS, "quote.approval_step_approved", "company.role_application_approved"]
    )
    for row in rows.iterator(chunk_size=500):
        params = dict(row.event_params or {})
        before = row.before_data or {}
        after = row.after_data or {}
        changed = False

        if row.event_code in STAGE_EVENTS:
            changed |= _fill(params, "from_stage_code", before.get("stage_code"))
            changed |= _fill(params, "to_stage_code", after.get("stage_code"))
        elif row.event_code in KYC_EVENTS:
            changed |= _fill(params, "from_status_code", before.get("verification_status"))
            changed |= _fill(params, "to_status_code", after.get("verification_status"))
        elif row.event_code == "quote.approval_step_approved":
            changed |= _fill(params, "participation_code", PARTICIPATION_BY_LABEL.get(params.get("participation")))
        elif row.event_code == "company.role_application_approved":
            changed |= _fill(params, "role_code", role_code_by_name.get(params.get("role_name")))

        if changed:
            row.event_params = params
            updated.append(row)
        if len(updated) >= 500:
            ActivityLog.objects.bulk_update(updated, ["event_params"])
            updated = []
    if updated:
        ActivityLog.objects.bulk_update(updated, ["event_params"])
