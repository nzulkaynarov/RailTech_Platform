"""K0 — снять CLIENT у поставщиков, которым его выдал сигнал (данные; схема не меняется).

Сигнал `supplier_or_manufacturer_implies_client` (маркетплейс, удалён в K0) выдавал CLIENT каждой компании, которой
добавляли SUPPLIER. С K0 CLIENT открывает кабинет клиента (`portal/services/access.py`), поэтому поставщик с таким
«подарком» входил бы в чужой кабинет. Миграция снимает CLIENT только у тех, где это точно не клиент:

- есть тип SUPPLIER или MANUFACTURER;
- нет сопоставления с клиентом CRM (`CrmClientMapping`);
- нет сделок (в том числе где она — компания контакта), КП, договоров, счетов и актов по сделкам компании,
  вложений и документов портала.

Своей компании (`OWN_COMPANY_ID` или единственный поставщик с активными участниками) CLIENT снимается всегда. Если свою
компанию определить нельзя (поставщиков с участниками несколько, `OWN_COMPANY_ID` не задан), шаг для неё пропускается
без ошибки: остальные условия действуют как для всех. Спорные случаи — нет, неоднозначные связи считаются активностью,
и CLIENT остаётся.

Перед изменением id и ИНН затронутых компаний пишутся в журнал миграции (контакты — нет) и в таблицу
`accounts_k0_client_unset`; по ней `reverse` возвращает CLIENT ровно тем же компаниям и удаляет таблицу.
"""

import logging

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)

TABLE = "accounts_k0_client_unset"
SELLER_CODES = ("SUPPLIER", "MANUFACTURER")


def _own_company_id(apps):
    """`OWN_COMPANY_ID` или единственный поставщик с активными участниками; иначе `None` (не падаем)."""
    configured = getattr(settings, "OWN_COMPANY_ID", None)
    if configured:
        return int(configured)
    Company = apps.get_model("parties", "Company")
    Member = apps.get_model("accounts", "CompanyMember")
    member_company_ids = Member.objects.filter(is_active=True).values("company_id")
    ids = list(
        Company.objects.filter(types__code="SUPPLIER", pk__in=member_company_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()[:2]
    )
    return ids[0] if len(ids) == 1 else None


def _has_activity(apps, company_ids):
    """Id компаний из `company_ids`, у которых есть хоть какая-то клиентская история."""
    busy = set()
    probes = (
        ("integration", "CrmClientMapping", "company_id"),
        ("sales", "Deal", "company_id"),
        ("sales", "Deal", "contact__company_id"),
        ("sales", "Quote", "deal__company_id"),
        ("sales", "Contract", "deal__company_id"),
        ("finance", "Invoice", "deal__company_id"),
        ("finance", "Act", "deal__company_id"),
        ("portal", "PortalUpload", "company_id"),
        ("documents", "GeneratedDocument", "company_id"),
    )
    for app_label, model_name, path in probes:
        model = apps.get_model(app_label, model_name)
        busy.update(
            model.objects.filter(**{f"{path}__in": company_ids}).values_list(path, flat=True).distinct()
        )
    return busy


def unset_client(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    CompanyType = apps.get_model("parties", "CompanyType")
    client = CompanyType.objects.filter(code="CLIENT").first()
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} (company_id bigint PRIMARY KEY, inn varchar(20) NULL)"
        )
    if client is None:
        return

    through = Company._meta.get_field("types").remote_field.through
    with_client = Company.objects.filter(types=client)
    own_id = _own_company_id(apps)
    sellers = list(with_client.filter(types__code__in=SELLER_CODES).values_list("pk", flat=True).distinct())
    busy = _has_activity(apps, sellers)
    target_ids = sorted(
        {pk for pk in sellers if pk not in busy}
        | ({own_id} if own_id and with_client.filter(pk=own_id).exists() else set())
    )
    if not target_ids:
        logger.info("K0: no supplier companies to unset CLIENT from")
        return

    rows = list(Company.objects.filter(pk__in=target_ids).order_by("pk").values_list("pk", "inn"))
    for company_id, inn in rows:
        logger.warning("K0: CLIENT is removed from company id=%s inn=%s", company_id, inn)
        print(f"K0: CLIENT is removed from company id={company_id} inn={inn}")
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {TABLE} (company_id, inn) VALUES (%s, %s) ON CONFLICT (company_id) DO NOTHING", rows
        )
    # Напрямую по связующей таблице: сигналы живых моделей в миграции не нужны, а «компания без типов» невозможна —
    # у каждой затронутой остаётся SUPPLIER/MANUFACTURER, у своей компании — SUPPLIER.
    through.objects.filter(companytype_id=client.pk, company_id__in=target_ids).delete()


def restore_client(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    CompanyType = apps.get_model("parties", "CompanyType")
    connection = schema_editor.connection
    client = CompanyType.objects.filter(code="CLIENT").first()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [TABLE])
        if cursor.fetchone()[0] is None:
            return
        cursor.execute(f"SELECT company_id FROM {TABLE} ORDER BY company_id")
        company_ids = [row[0] for row in cursor.fetchall()]
    if client is not None:
        through = Company._meta.get_field("types").remote_field.through
        existing = set(through.objects.filter(companytype_id=client.pk).values_list("company_id", flat=True))
        alive = set(Company.objects.filter(pk__in=company_ids).values_list("pk", flat=True))
        through.objects.bulk_create(
            [through(company_id=pk, companytype_id=client.pk) for pk in company_ids if pk in alive - existing]
        )
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE {TABLE}")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_finance_view_permission"),
        ("parties", "0008_contact_archived_at"),
        ("integration", "0010_prune_snapshot_quote_final_approval"),
        ("sales", "0011_contract_status_v3"),
        ("finance", "0004_payment_confirmation"),
        ("portal", "0006_portalupload_private_storage"),
        ("documents", "0003_initial"),
    ]

    operations = [migrations.RunPython(unset_client, restore_client)]
