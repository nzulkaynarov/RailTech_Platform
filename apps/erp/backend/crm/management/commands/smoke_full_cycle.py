"""
End-to-end smoke test of the enterprise deal cycle.

Run:
    python manage.py smoke_full_cycle

What it does:
    1. Create (or reuse) a client company (клиентских пользователей в ERP нет — FIX-13).
    2. Create (or reuse) a SUPPLIER company + user.
    3. Create (or reuse) a MANAGER user.
    4. Create a Deal (DRAFT).
    5. Move Deal DRAFT → SOURCING → CALCULATING via the FSM.
    6. Create Quote + QuoteItem, send to client, accept as the client's contact.
    7. Generate Contract → sign client → sign manager (SIGNED).
    8. Generate Invoice → record Payment (PAID) → generate Act (приёмка акта — шаг клиента в портале).
    9. Update Fulfillment to ACCEPTED → auto-transition Deal to CLOSED_WON.
    10. Print step-by-step report.

All steps go through services.py — no raw ORM writes for business logic. Шаги клиента, которых
в ERP больше нет (подпись договора, приёмка акта), имитирует администратор-менеджер; настоящие
вернёт портал (FIX-22).
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "End-to-end smoke test of the enterprise deal cycle."

    def add_arguments(self, parser):
        parser.add_argument("--cleanup", action="store_true", help="Drop test entities after the run")

    @transaction.atomic
    def handle(self, *args, **options):
        from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
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
        admin_role = _must(SystemRole, "ADMIN")
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
        from core.models import ExchangeRate

        ExchangeRate.objects.update_or_create(
            currency=usd,
            rate_date=timezone.localdate(),
            defaults={"rate_to_uzs": Decimal("12800.00"), "source": "CBU"},
        )
        published = _must(ProductStatus, "PUBLISHED")
        domain_general = _must(DomainType, "GENERAL_GOODS")
        stock_in = _must(StockStatus, "IN_STOCK")

        step(1, "Client company")
        buyer_co, _ = Company.objects.get_or_create(
            inn="111111111",
            defaults={"name": "Smoke Buyer LLC", "country": country},
        )
        buyer_co.types.add(client_type)
        from accounts.models import Contact

        # Клиент — контакт контрагента (пользователя ERP у клиента нет — FIX-13): получатель КП.
        client_contact, _ = Contact.objects.get_or_create(
            company=buyer_co,
            email="smoke.client@example.test",
            defaults={"name": "Smoke Client", "phone": "+998900000000"},
        )
        info(f"company={buyer_co.name} contact={client_contact.email}")

        step(2, "Supplier user + company")
        from core.tenant import own_company

        supplier_co = own_company()
        if supplier_co is None:
            supplier_co, _ = Company.objects.get_or_create(
                inn="222222222",
                defaults={
                    "name": "Smoke Supplier LLC",
                    "country": country,
                    "bank_account": "20208000000000000001",
                    "mfo": "00440",
                },
            )
            supplier_co.types.add(supplier_type)
        if not supplier_co.bank_account or not supplier_co.mfo:
            supplier_co.bank_account = "20208000000000000001"
            supplier_co.mfo = "00440"
            supplier_co.save(update_fields=["bank_account", "mfo"])

        supplier, _ = CustomUser.objects.get_or_create(
            email="smoke.supplier@example.test",
            defaults={
                "username": "smoke.supplier@example.test",
                "is_active": True,
                "first_name": "Smoke",
                "last_name": "Supplier",
            },
        )
        CompanyMember.objects.get_or_create(
            user=supplier, company=supplier_co, defaults={"role": owner_role, "is_primary": True, "is_active": True}
        )
        info(f"supplier={supplier.email} company={supplier_co.name}")

        step(3, "Manager user")
        manager, _ = CustomUser.objects.get_or_create(
            email="smoke.manager@example.test",
            defaults={
                "username": "smoke.manager@example.test",
                "is_active": True,
                "is_staff": True,
                "first_name": "Smoke",
                "last_name": "Manager",
                "role": admin_role,
            },
        )
        if not manager.is_staff or not manager.is_superuser:
            manager.is_staff = True
            manager.is_superuser = True
            manager.role = admin_role
            manager.save(update_fields=["is_staff", "is_superuser", "role"])
        info(f"manager={manager.email} role={manager.role.code if manager.role else '-'}")

        step(4, "Create Deal (stage DRAFT)")
        draft_stage = DealStage.objects.get(code="DRAFT")
        deal, _ = Deal.objects.get_or_create(
            title="Smoke E2E deal",
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
            sku="SMK-001",
            defaults={
                "name": "Железный шпала",
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
        contract, err = crm_services.sign_contract_by_client(contract.id, manager)
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

        step(9, "Fulfillment ACCEPTED → auto CLOSED_WON")
        crm_services.ensure_fulfillment(deal)
        ff, err = crm_services.update_fulfillment_status(
            deal.id, manager, "SHIPPED", tracking_number="TRK-SMK-001", carrier="Smoke Logistics"
        )
        if err:
            raise Exception(f"update_fulfillment_status SHIPPED failed: {err}")
        ff, err = crm_services.update_fulfillment_status(deal.id, manager, "DELIVERED")
        if err:
            raise Exception(f"update_fulfillment_status DELIVERED failed: {err}")
        ff, err = crm_services.update_fulfillment_status(deal.id, manager, "ACCEPTED")
        if err:
            raise Exception(f"update_fulfillment_status ACCEPTED failed: {err}")
        deal.refresh_from_db()
        info(f"deal.stage={deal.stage.code} (expected CLOSED_WON)")

        assert deal.stage.code == "CLOSED_WON", f"Expected CLOSED_WON, got {deal.stage.code}"
        out.write(self.style.SUCCESS(f"{tag} ✅ SUCCESS: full enterprise cycle passed"))

        if options.get("cleanup"):
            out.write(self.style.WARNING(f"{tag} cleaning up test entities..."))
            deal.delete()
            supplier_co.delete()
            buyer_co.delete()
            supplier.delete()
            manager.delete()
