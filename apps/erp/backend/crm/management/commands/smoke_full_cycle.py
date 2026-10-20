"""
End-to-end smoke test of the enterprise deal cycle (dev-only).

Run:
    python manage.py smoke_full_cycle [--cleanup]

Только при ``DEBUG=True`` (иначе ``CommandError``): команда заводит учётные записи и пишет данные
сквозного цикла. Всё, что она создаёт, помечено — свои ИНН и e-mail «smoke», источник курса
``SMOKE``, артикул ``SMK-001`` — и ни одна строка чужих данных не правится (FIX-43, F-8):

* реальный курс USD не переписывается: берётся действующий курс справочника, а строка
  с источником ``SMOKE`` заводится, только если курса нет вовсе;
* реквизиты своей компании (``own_company()``) не читаются и не меняются: продавец цикла — своя
  smoke-компания (на время прогона ``OWN_COMPANY_ID`` указывает на неё, после — возвращается);
* smoke-менеджер — обычный сотрудник smoke-компании с ролью «Руководитель», а не суперпользователь;
  по окончании членства деактивируются, чтобы вторая компания-продавец не сбила ``own_company()``;
* ``--cleanup`` удаляет только созданное командой (по меткам) и никогда — настоящую компанию.

What it does:
    1. Create (or reuse) a client company (клиентских пользователей в ERP нет — FIX-13).
    2. Create (or reuse) the smoke SUPPLIER company + user.
    3. Create (or reuse) a MANAGER user (staff of the smoke company, not a superuser).
    4. Create a Deal (DRAFT).
    5. Move Deal DRAFT → SOURCING → CALCULATING via the FSM.
    6. Create Quote + QuoteItem, send to client, accept as the client's contact.
    7. Generate Contract → sign client → sign manager (SIGNED).
    8. Generate Invoice → record Payment (PAID) → generate Act (приёмка акта — шаг клиента в портале).
    9. Fulfillment SHIPPED → DELIVERED; the client contact accepts the delivery lines (portal step);
       the manager moves the Deal to CLOSED_WON.
    10. Print step-by-step report.

All steps go through services.py — no raw ORM writes for business logic. Шаги клиента, которых
в ERP больше нет (приёмка акта), цикл не имитирует; подпись договора клиентом — как в портале,
от контакта своей компании с ``can_act`` (FIX-22).
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

# Метки smoke-данных: по ним --cleanup находит «своё» и только своё. ИНН заведомо вымышленные.
SMOKE_RATE_SOURCE = "SMOKE"
SMOKE_BUYER = {"inn": "999000001", "name": "Smoke Buyer LLC"}
SMOKE_SELLER = {"inn": "999000002", "name": "Smoke Supplier LLC"}
SMOKE_SELLER_BANK = {"bank_account": "20208000000000000001", "mfo": "00440"}
SMOKE_CLIENT_EMAIL = "smoke.client@example.test"
SMOKE_SUPPLIER_EMAIL = "smoke.supplier@example.test"
SMOKE_MANAGER_EMAIL = "smoke.manager@example.test"
SMOKE_PRODUCT_SKU = "SMK-001"
SMOKE_PRODUCT_NAME = "Железный шпала"
SMOKE_DEAL_TITLE = "Smoke E2E deal"


class Command(BaseCommand):
    help = "End-to-end smoke test of the enterprise deal cycle (dev-only: DEBUG=True required)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Drop the entities this command created (by smoke labels; never the own company)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "smoke_full_cycle is a dev-only smoke test: it creates accounts and a full deal cycle. "
                "Refusing to run with DEBUG=False."
            )
        # На время прогона своя компания — smoke-продавец (иначе вторая компания-продавец с
        # сотрудниками ломает `own_company()`); настройка возвращается в любом случае.
        had_override = hasattr(settings, "OWN_COMPANY_ID")
        previous_override = getattr(settings, "OWN_COMPANY_ID", None)
        try:
            with transaction.atomic():
                self._run(options)
        finally:
            if had_override:
                settings.OWN_COMPANY_ID = previous_override
            elif hasattr(settings, "OWN_COMPANY_ID"):
                del settings.OWN_COMPANY_ID

    def _run(self, options):
        from accounts.models import CompanyMember, CompanyType, SystemRole, WorkspaceRole
        from catalog.models import DomainType, Product, ProductStatus, StockStatus, SupplierOffer
        from crm import services as crm_services
        from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
        from master_data.models import Country, Currency, UnitOfMeasure

        out = self.stdout
        tag = "[SMOKE]"

        def step(i, msg):
            out.write(self.style.SUCCESS(f"{tag} {i}. {msg}"))

        def info(msg):
            out.write(f"{tag}    {msg}")

        # ─── Require lookups from data migration (Rule 1: no hot-path get_or_create) ───
        def _must(model, code, hint=""):
            obj = model.objects.filter(code=code).first()
            if obj is None:
                raise RuntimeError(
                    f"Lookup {model.__name__}.code={code!r} missing. "
                    f"Run `python manage.py migrate` — core.0002_seed_enterprise_lookups "
                    f"is the single source of truth for business codes."
                    f"{' · ' + hint if hint else ''}"
                )
            return obj

        client_type = _must(CompanyType, "CLIENT")
        supplier_type = _must(CompanyType, "SUPPLIER")
        owner_role = _must(WorkspaceRole, "OWNER")
        draft_quote = _must(QuoteStatus, "DRAFT")
        _must(QuoteStatus, "SENT")
        _must(QuoteStatus, "APPROVED")
        for code in [
            "DRAFT",
            "KYC_PENDING",
            "RFQ_OPEN",
            "SOURCING",
            "CALCULATING",
            "QUOTE_SENT",
            "CONTRACT_SIGNED",
            "CLOSED_WON",
            "CLOSED_LOST",
        ]:
            _must(DealStage, code)
        # Master Data (Country / Currency / UOM) still uses get_or_create — those are
        # real reference data, not enterprise lookups owned by the seed migration.
        usd, _ = Currency.objects.get_or_create(
            code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10}
        )
        pcs, _ = UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Piece", "sort_order": 10})
        country, _ = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
        from finance.services.fx import resolve_rate

        from core.models import ExchangeRate

        # Реальный курс не трогаем (F-8): действующий курс справочника годится как есть. Строку с
        # источником SMOKE заводим, только если на сегодня строки нет вовсе — и --cleanup снимет именно её.
        # Настоящая, но непригодная строка за сегодня не перезаписывается: это ошибка данных, её чинит человек.
        if resolve_rate("USD") is None:
            ExchangeRate.objects.get_or_create(
                currency=usd,
                rate_date=timezone.localdate(),
                defaults={"rate_to_uzs": Decimal("12800.00"), "source": SMOKE_RATE_SOURCE},
            )
            if resolve_rate("USD") is None:
                raise CommandError(
                    "Курс USD на сегодня есть в справочнике, но непригоден (не положительный). "
                    "smoke_full_cycle его не переписывает — исправьте строку курса и запустите снова."
                )
        published = _must(ProductStatus, "PUBLISHED")
        domain_general = _must(DomainType, "GENERAL_GOODS")
        stock_in = _must(StockStatus, "IN_STOCK")

        step(1, "Client company")
        buyer_co = self._smoke_company(SMOKE_BUYER, country=country)
        buyer_co.types.add(client_type)
        from accounts.models import Contact

        # Клиент — контакт контрагента (пользователя ERP у клиента нет — FIX-13): получатель КП.
        client_contact, _ = Contact.objects.get_or_create(
            company=buyer_co,
            email=SMOKE_CLIENT_EMAIL,
            defaults={"name": "Smoke Client", "phone": "+998900000000", "can_act": True},
        )
        if not client_contact.can_act:
            client_contact.can_act = True
            client_contact.save(update_fields=["can_act"])
        info(f"company={buyer_co.name} contact={client_contact.email}")

        step(2, "Supplier user + company")
        # Продавец цикла — своя smoke-компания: реквизиты настоящей own_company() не читаем и не пишем.
        supplier_co = self._smoke_company(SMOKE_SELLER, country=country, **SMOKE_SELLER_BANK)
        supplier_co.types.add(supplier_type)
        # На время прогона «своя компания» ERP — smoke-продавец (возвращается в handle()).
        settings.OWN_COMPANY_ID = supplier_co.pk

        supplier = self._smoke_user(
            SMOKE_SUPPLIER_EMAIL, first_name="Smoke", last_name="Supplier", role=_must(SystemRole, "USER")
        )
        self._smoke_member(supplier, supplier_co, owner_role, is_primary=True)
        info(f"supplier={supplier.email} company={supplier_co.name}")

        step(3, "Manager user")
        # Обычный сотрудник smoke-компании с ролью «Руководитель» (все права ролей), не суперпользователь.
        manager = self._smoke_user(
            SMOKE_MANAGER_EMAIL, first_name="Smoke", last_name="Manager", role=_must(SystemRole, "USER")
        )
        manager_member = self._smoke_member(manager, supplier_co, owner_role, is_primary=True)
        from accounts.services.roles import ensure_default_company_roles

        manager_member.company_roles.set([ensure_default_company_roles(supplier_co)["HEAD"]])
        info(f"manager={manager.email} superuser={manager.is_superuser}")

        step(4, "Create Deal (stage DRAFT)")
        # Каждый прогон начинается с чистой smoke-сделки: договор прошлого прогона уже подписан и цикл не повторит.
        self._drop_smoke_deals([buyer_co.pk])
        draft_stage = DealStage.objects.get(code="DRAFT")
        deal, _ = Deal.objects.get_or_create(
            title=SMOKE_DEAL_TITLE,
            company=buyer_co,
            contact=client_contact,
            manager=manager,
            defaults={"stage": draft_stage},
        )
        if deal.stage is None or deal.stage.code != "DRAFT":
            deal.stage = draft_stage
            deal.save(update_fields=["stage"])
        info(f"deal=#{deal.id} stage={deal.stage.code}")

        step(5, "Move deal DRAFT → SOURCING → CALCULATING")
        for target in ["SOURCING", "CALCULATING"]:
            deal, err = crm_services.transition_deal_stage(deal, target, actor=manager)
            if err:
                raise Exception(f"transition_deal_stage → {target} failed: {err}")
        deal.refresh_from_db()
        info(f"deal.stage={deal.stage.code} (expected CALCULATING)")

        step(6, "Create Quote + QuoteItem, send, approve")
        product, _ = Product.objects.get_or_create(
            sku=SMOKE_PRODUCT_SKU,
            defaults={
                "name": SMOKE_PRODUCT_NAME,
                "status": published,
                "domain_type": domain_general,
                "uom": pcs,
                "manufacturer": supplier_co,
                "gost_drawing": "GOST-1234",
            },
        )
        SupplierOffer.objects.get_or_create(
            product=product,
            supplier=supplier_co,
            defaults={"base_price": "100.00", "currency": usd, "stock_status": stock_in, "is_active": True},
        )
        quote, _ = Quote.objects.get_or_create(
            deal=deal,
            version=1,
            defaults={
                "status": draft_quote,
                "prepared_by": manager,
                "seller_company": supplier_co,
                "tax_country": country,
                "vat_rate": Decimal("12.00"),
            },
        )
        if not quote.seller_company_id:
            quote.seller_company = supplier_co
            quote.save(update_fields=["seller_company"])
        QuoteItem.objects.update_or_create(
            quote=quote,
            product=product,
            defaults={
                "quantity": 10,
                "frozen_base_price": Decimal("100.00"),
                "frozen_currency": usd,
                "margin_percent": Decimal("20.00"),
            },
        )
        from crm.services import QuoteCalculationService, QuoteLifecycleService

        QuoteCalculationService.recalculate_quote(quote.id)
        # КП must be internally approved (READY_TO_SEND) before it can go out.
        quote.status = _must(QuoteStatus, "READY_TO_SEND")
        quote.save(update_fields=["status"])
        quote = QuoteLifecycleService.send_to_client(quote.id, manager)
        info(f"quote sent, total_incl_vat={quote.total_incl_vat}")
        quote = QuoteLifecycleService.accept_quote_as_contact(quote.id, contact_email=client_contact.email)
        info(f"quote status={quote.status.code}")

        step(7, "Generate contract, sign by client and manager")
        contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager, notes="smoke contract")
        if err:
            raise Exception(f"generate_contract_from_quote failed: {err}")
        info(f"contract={contract.number} status={contract.status_code}")
        # Подпись клиента — шаг портала (FIX-22): контакт своей компании с `can_act`, договор «ждёт клиента».
        contract, err = crm_services.sign_contract_by_client(contract.id, portal_contact=client_contact)
        if err:
            raise Exception(f"sign_contract_by_client failed: {err}")
        contract, err = crm_services.sign_contract_by_manager(contract.id, manager)
        if err:
            raise Exception(f"sign_contract_by_manager failed: {err}")
        info(f"contract status={contract.status_code} (expected SIGNED)")

        step(8, "Generate invoice, record payment, generate act")
        invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
        if err:
            raise Exception(f"generate_invoice_from_contract failed: {err}")
        from crm.services.invoice_lifecycle import issue_invoice

        invoice, err = issue_invoice(invoice, manager)
        if err:
            raise Exception(f"issue_invoice failed: {err}")
        info(f"invoice={invoice.number} total={invoice.total_incl_vat}")
        payment, err = crm_services.record_payment(
            invoice.id,
            manager,
            amount=invoice.total_incl_vat,
            paid_at=timezone.localdate(),
            method="BANK_TRANSFER",
            reference="smoke",
            manual=True,
        )
        if err:
            raise Exception(f"record_payment failed: {err}")
        invoice.refresh_from_db()
        info(f"invoice status={invoice.status_code} amount_paid={invoice.amount_paid}")
        act, err = crm_services.generate_act(invoice.id, actor=manager)
        if err:
            raise Exception(f"generate_act failed: {err}")
        info(f"act={act.number} status={act.status_code} (приёмка акта клиентом — в портале)")

        step(9, "Fulfillment DELIVERED → client accepts the delivery lines (portal step) → deal CLOSED_WON")
        crm_services.ensure_fulfillment(deal)
        ff, err = crm_services.update_fulfillment_status(
            deal.id, manager, "SHIPPED", tracking_number="TRK-SMK-001", carrier="Smoke Logistics"
        )
        if err:
            raise Exception(f"update_fulfillment_status SHIPPED failed: {err}")
        ff, err = crm_services.update_fulfillment_status(deal.id, manager, "DELIVERED")
        if err:
            raise Exception(f"update_fulfillment_status DELIVERED failed: {err}")
        # Приёмка — решение клиента: статус исполнения «принято» менеджеру недоступен (FIX-13/FIX-24). Строки
        # поставки принимает контакт клиента, как в портале; сделку закрывает менеджер по обычному переходу.
        from sales.models import DeliveryLine
        from sales.services.delivery_lines import accept_delivery_line, sync_company_delivery_lines

        sync_company_delivery_lines(buyer_co)
        lines = list(DeliveryLine.objects.filter(deal=deal))
        if not lines:
            raise Exception("no delivery lines for the approved quote")
        for line in lines:
            _, err = accept_delivery_line(line.pk, client_contact)
            if err:
                raise Exception(f"accept_delivery_line failed: {err}")
        info(f"delivery lines accepted by the client contact: {len(lines)}")
        deal.refresh_from_db()
        moved, err = crm_services.transition_deal_stage(
            deal, "CLOSED_WON", actor=manager, reason="Приёмка клиентом (smoke)"
        )
        if err:
            raise Exception(f"transition_deal_stage → CLOSED_WON failed: {err} (stage={deal.stage.code})")
        deal.refresh_from_db()
        info(f"deal.stage={deal.stage.code} (expected CLOSED_WON)")

        assert deal.stage.code == "CLOSED_WON", f"Expected CLOSED_WON, got {deal.stage.code}"
        out.write(self.style.SUCCESS(f"{tag} ✅ SUCCESS: full enterprise cycle passed"))

        if options.get("cleanup"):
            out.write(self.style.WARNING(f"{tag} cleaning up test entities..."))
            self._cleanup(out, tag)
        else:
            # Smoke-сотрудники остаются в базе (сделку можно открыть глазами), но не активны: иначе вторая
            # компания-продавец с сотрудниками сделала бы `own_company()` неоднозначной для всего ERP.
            CompanyMember.objects.filter(company=supplier_co).update(is_active=False)
            info("smoke staff memberships deactivated (own_company() stays unambiguous)")

    # ─── Smoke-данные: создание ──────────────────────────────────────────────────────

    def _smoke_company(self, spec, country, **extra):
        """Smoke-компания по метке (ИНН + имя). Чужая компания с тем же ИНН — отказ, не правка."""
        from accounts.models import Company

        company = Company.objects.filter(inn=spec["inn"]).first()
        if company is None:
            return Company.objects.create(inn=spec["inn"], name=spec["name"], country=country, **extra)
        if company.name != spec["name"]:
            raise CommandError(
                f"ИНН {spec['inn']} занят компанией «{company.name}», это не smoke-данные — команда её не трогает."
            )
        return company

    def _smoke_user(self, email, *, first_name, last_name, role):
        """Smoke-аккаунт без пароля и без прав администратора (старые прогоны делали менеджера суперпользователем)."""
        from accounts.models import CustomUser

        user = CustomUser.objects.filter(email=email).first()
        if user is None:
            user = CustomUser(
                email=email, username=email, first_name=first_name, last_name=last_name, role=role, is_active=True
            )
            user.set_unusable_password()
            user.save()
        elif user.is_superuser or user.is_staff:
            user.is_superuser = False
            user.is_staff = False
            user.save(update_fields=["is_superuser", "is_staff"])
        return user

    def _smoke_member(self, user, company, workspace_role, *, is_primary):
        from accounts.models import CompanyMember

        member, _ = CompanyMember.objects.get_or_create(
            user=user,
            company=company,
            defaults={"role": workspace_role, "is_primary": is_primary, "is_active": True, "can_sell": True},
        )
        if not member.is_active or not member.can_sell:
            member.is_active = True
            member.can_sell = True
            member.save(update_fields=["is_active", "can_sell"])
        return member

    # ─── Smoke-данные: уборка по меткам ──────────────────────────────────────────────

    def _drop_smoke_deals(self, smoke_company_ids):
        """Снять smoke-сделки и их документы. Финансовые документы защищены от каскада (PROTECT): идём снизу
        вверх — акты, платежи, счета, договоры. Только сделки smoke-компаний с smoke-названием."""
        from crm.models import Act, Contract, Deal, Invoice, Payment

        deals = Deal.objects.filter(title=SMOKE_DEAL_TITLE, company_id__in=smoke_company_ids)
        Act.objects.filter(deal__in=deals).delete()
        Payment.objects.filter(invoice__deal__in=deals).delete()
        Invoice.objects.filter(deal__in=deals).delete()
        Contract.objects.filter(deal__in=deals).delete()
        deals.delete()

    def _cleanup(self, out, tag):
        """Удаляет только то, что создаёт эта команда: smoke-компании (ИНН + имя), аккаунты по smoke e-mail,
        smoke-товар, курс с источником SMOKE. Настоящая компания не попадает ни под одну метку."""
        from accounts.models import Company, CustomUser
        from catalog.models import Product
        from core.models import ExchangeRate

        smoke_companies = Company.objects.none()
        for spec in (SMOKE_BUYER, SMOKE_SELLER):
            smoke_companies = smoke_companies | Company.objects.filter(inn=spec["inn"], name=spec["name"])
        smoke_company_ids = list(smoke_companies.values_list("pk", flat=True))

        self._drop_smoke_deals(smoke_company_ids)
        Product.objects.filter(sku=SMOKE_PRODUCT_SKU, name=SMOKE_PRODUCT_NAME).delete()
        Company.objects.filter(pk__in=smoke_company_ids).delete()
        CustomUser.objects.filter(email__in=[SMOKE_SUPPLIER_EMAIL, SMOKE_MANAGER_EMAIL], is_superuser=False).delete()
        ExchangeRate.objects.filter(source=SMOKE_RATE_SOURCE).delete()
        out.write(f"{tag}    removed: {len(smoke_company_ids)} smoke companies, deal, product, accounts, SMOKE rates")
