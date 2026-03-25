import json
import os
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction, models
from django.contrib.auth import get_user_model
from django.utils import timezone

from master_data.models import Currency
from accounts.models import (
    SystemRole, WorkspaceRole, VerificationStatus,
    Company, CompanyMember, CompanyType,
)
from catalog.models import (
    ProductStatus, StockStatus, DomainType, Category,
    EquipmentGroup, Product, SupplierOffer,
)
from crm.models import DealStage, Deal, Quote, QuoteStatus, QuoteItem, Message
from notifications.models import Notification, NotificationType

User = get_user_model()
SEED_DATA_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'seed_data.json'


class Command(BaseCommand):
    help = 'Loads ALL demo data from seed_data.json into the database (after running core_seed).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-core',
            action='store_true',
            help='Skip running core_seed first (useful if it was already run)',
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("Demo Data Seeding Started")
        self.stdout.write("=" * 60)

        # Load seed data
        seed_data = json.loads(SEED_DATA_PATH.read_text(encoding='utf-8'))

        # Step 1: Run core_seed if needed
        if not options['skip_core']:
            self.stdout.write("\n[1/9] Running core_seed to ensure lookups exist...")
            call_command('core_seed')
            self.stdout.write(self.style.SUCCESS("✓ Core lookups loaded"))
        else:
            self.stdout.write("\n[1/9] Skipping core_seed (--skip-core flag set)")

        with transaction.atomic():
            # Step 2: Equipment Groups
            self.stdout.write("\n[2/9] Creating equipment groups...")
            self._create_equipment_groups(seed_data.get('equipment_groups', []))

            # Step 3: Categories
            self.stdout.write("\n[3/9] Creating categories...")
            self._create_categories(seed_data.get('categories', []))

            # Step 4: Products
            self.stdout.write("\n[4/9] Creating products...")
            self._create_products(seed_data.get('products', []))

            # Step 5: Supplier Offers
            self.stdout.write("\n[5/9] Creating supplier offers...")
            self._create_supplier_offers(seed_data.get('products', []))

            # Step 6: Deals
            self.stdout.write("\n[6/9] Creating deals...")
            self._create_deals(seed_data.get('deals', []))

            # Step 7: Quotes
            self.stdout.write("\n[7/9] Creating quotes...")
            self._create_quotes(seed_data.get('quotes', []))

            # Step 8: Messages
            self.stdout.write("\n[8/9] Creating deal messages...")
            self._create_messages(seed_data.get('messages', []))

            # Step 9: Notifications
            self.stdout.write("\n[9/9] Creating notifications...")
            self._create_notifications(seed_data.get('notifications', []))

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("✓ Demo data fully loaded!"))
        self.stdout.write("=" * 60)

    # ─────────────────────────────────────────────────────────────
    # Equipment Groups (Hierarchical)
    # ─────────────────────────────────────────────────────────────

    def _create_equipment_groups(self, equipment_groups_data):
        """Create equipment groups with proper hierarchy (parent FK to self)."""
        if not equipment_groups_data:
            self.stdout.write("  No equipment groups to load")
            return

        count = 0
        for group_data in equipment_groups_data:
            group_type = group_data.get('type')
            if not group_type:
                continue

            # For demo data, treat each equipment_group entry as a root (parent=None)
            # In a real scenario, you'd parse a hierarchy from children list
            obj, created = EquipmentGroup.objects.get_or_create(
                name=group_type,
                parent=None,
                defaults={
                    'description': f"Railway equipment group: {group_type}",
                    'sort_order': count,
                    'is_active': True,
                }
            )
            if created:
                count += 1
                self.stdout.write(f"  ✓ Created equipment group: {group_type}")
            else:
                self.stdout.write(f"  - Equipment group already exists: {group_type}")

        self.stdout.write(self.style.SUCCESS(f"  {count} equipment groups created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Categories (Hierarchical)
    # ─────────────────────────────────────────────────────────────

    def _create_categories(self, categories_data):
        """Create categories with parent hierarchy (parent FK to self)."""
        if not categories_data:
            self.stdout.write("  No categories to load")
            return

        # First pass: create all categories without parents
        categories_by_name = {}
        count = 0

        for cat_data in categories_data:
            name = cat_data.get('name')
            domain_code = cat_data.get('domain_type')
            if not name:
                continue

            domain_type = None
            if domain_code:
                domain_type = DomainType.objects.filter(code=domain_code).first()
                if not domain_type:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ DomainType '{domain_code}' not found for category '{name}'"
                        )
                    )

            # Store for second pass
            categories_by_name[name] = cat_data
            categories_by_name[name]['domain_type_obj'] = domain_type

        # Second pass: create with proper parent references
        for name, cat_data in categories_by_name.items():
            parent_name = cat_data.get('parent')
            parent_obj = None

            if parent_name and parent_name in categories_by_name:
                # Try to fetch parent from DB (it should exist from first pass)
                parent_obj = Category.objects.filter(name=parent_name).first()

            obj, created = Category.objects.get_or_create(
                name=name,
                defaults={
                    'domain_type': cat_data.get('domain_type_obj'),
                    'parent': parent_obj,
                    'sort_order': 0,
                    'is_active': True,
                }
            )
            if created:
                count += 1
                parent_str = f" (parent: {parent_name})" if parent_name else " (root)"
                self.stdout.write(f"  ✓ Created category: {name}{parent_str}")
            else:
                self.stdout.write(f"  - Category already exists: {name}")

        self.stdout.write(self.style.SUCCESS(f"  {count} categories created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Products (PIM)
    # ─────────────────────────────────────────────────────────────

    def _create_products(self, products_data):
        """Create products with proper FK lookups."""
        if not products_data:
            self.stdout.write("  No products to load")
            return

        count = 0
        for prod_data in products_data:
            sku = prod_data.get('sku')
            name = prod_data.get('name')
            if not sku or not name:
                continue

            # Resolve FK references
            domain_type = None
            domain_code = prod_data.get('domain_type_code')
            if domain_code:
                domain_type = DomainType.objects.filter(code=domain_code).first()
                if not domain_type:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ DomainType '{domain_code}' not found for product '{sku}'"
                        )
                    )

            status = ProductStatus.objects.filter(code=prod_data.get('status_code', 'PUBLISHED')).first()
            if not status:
                status = ProductStatus.objects.filter(code='PUBLISHED').first()

            category = None
            category_name = prod_data.get('category_name')
            if category_name:
                category = Category.objects.filter(name=category_name).first()
                if not category:
                    self.stdout.write(
                        self.style.WARNING(f"  ⚠ Category '{category_name}' not found for '{sku}'")
                    )

            manufacturer = None
            manufacturer_inn = prod_data.get('manufacturer_inn')
            if manufacturer_inn:
                manufacturer = Company.objects.filter(inn=manufacturer_inn).first()
                if not manufacturer:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Manufacturer INN '{manufacturer_inn}' not found for '{sku}'"
                        )
                    )

            uom = None
            uom_code = prod_data.get('uom_code')
            if uom_code:
                from master_data.models import UnitOfMeasure
                uom = UnitOfMeasure.objects.filter(code=uom_code).first()
                if not uom:
                    self.stdout.write(
                        self.style.WARNING(f"  ⚠ UOM '{uom_code}' not found for '{sku}'")
                    )

            obj, created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'description': prod_data.get('description', ''),
                    'domain_type': domain_type,
                    'status': status,
                    'category': category,
                    'manufacturer': manufacturer,
                    'uom': uom,
                    'gost_drawing': prod_data.get('gost_drawing', ''),
                    'specifications': prod_data.get('specifications', {}),
                }
            )
            if created:
                count += 1
                self.stdout.write(f"  ✓ Created product: {sku} ({name})")
            else:
                self.stdout.write(f"  - Product already exists: {sku}")

        self.stdout.write(self.style.SUCCESS(f"  {count} products created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Supplier Offers
    # ─────────────────────────────────────────────────────────────

    def _create_supplier_offers(self, products_data):
        """Create supplier offers for each product (price, currency, stock_status, delivery_basis)."""
        if not products_data:
            self.stdout.write("  No supplier offers to load")
            return

        from master_data.models import DeliveryBasis

        count = 0
        for prod_data in products_data:
            sku = prod_data.get('sku')
            manufacturer_inn = prod_data.get('manufacturer_inn')
            base_price = prod_data.get('base_price_fca', 0)

            # Skip if no SKU or manufacturer
            if not sku or not manufacturer_inn:
                continue

            product = Product.objects.filter(sku=sku).first()
            supplier = Company.objects.filter(inn=manufacturer_inn).first()

            if not product or not supplier:
                continue

            # Get default values for offer
            currency = Currency.objects.filter(code='USD').first()
            stock_status = StockStatus.objects.filter(code='IN_STOCK').first()
            delivery_basis = DeliveryBasis.objects.filter(code='FCA').first()

            if not currency or not stock_status or not delivery_basis:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ Missing lookup for offer: {sku} from {manufacturer_inn}"
                    )
                )
                continue

            obj, created = SupplierOffer.objects.get_or_create(
                product=product,
                supplier=supplier,
                defaults={
                    'supplier_sku': sku,
                    'base_price': Decimal(str(base_price)),
                    'currency': currency,
                    'delivery_basis': delivery_basis,
                    'stock_status': stock_status,
                    'delivery_lead_time': '14-21 дн.',
                    'min_order_qty': 1,
                    'is_active': True,
                }
            )
            if created:
                count += 1
                self.stdout.write(f"  ✓ Created offer: {sku} from {supplier.name}")
            else:
                self.stdout.write(f"  - Offer already exists: {sku} from {supplier.name}")

        self.stdout.write(self.style.SUCCESS(f"  {count} supplier offers created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Deals
    # ─────────────────────────────────────────────────────────────

    def _create_deals(self, deals_data):
        """Create deals with proper FKs (company, client user, manager user, stage)."""
        if not deals_data:
            self.stdout.write("  No deals to load")
            return

        count = 0
        for deal_data in deals_data:
            deal_number = deal_data.get('number')
            client_inn = deal_data.get('client_inn')
            manager_email = deal_data.get('manager_email')
            stage_code = deal_data.get('stage', 'DRAFT')

            if not deal_number or not client_inn:
                continue

            # Resolve FKs
            company = Company.objects.filter(inn=client_inn).first()
            if not company:
                self.stdout.write(self.style.WARNING(f"  ⚠ Company INN '{client_inn}' not found"))
                continue

            manager = None
            if manager_email:
                manager = User.objects.filter(email=manager_email).first()
                if not manager:
                    self.stdout.write(
                        self.style.WARNING(f"  ⚠ Manager email '{manager_email}' not found")
                    )

            stage = DealStage.objects.filter(code=stage_code).first()
            if not stage:
                stage = DealStage.objects.filter(code='DRAFT').first()

            # Parse created_date
            try:
                created_date = datetime.fromisoformat(deal_data.get('created_date', '').replace('Z', '+00:00'))
                created_date = timezone.make_aware(created_date)
            except (ValueError, TypeError):
                created_date = timezone.now()

            obj, created = Deal.objects.get_or_create(
                company=company,
                title=deal_number,
                defaults={
                    'client': None,  # Could be set if a specific client user is identified
                    'manager': manager,
                    'stage': stage,
                    'notes': f"Deal amount: ${deal_data.get('amount_usd', 0)}",
                }
            )

            # Manually update created_at if it's a new deal (since auto_now_add prevents updates)
            if created:
                count += 1
                Deal.objects.filter(pk=obj.pk).update(created_at=created_date)
                self.stdout.write(f"  ✓ Created deal: {deal_number}")
            else:
                self.stdout.write(f"  - Deal already exists: {deal_number}")

        self.stdout.write(self.style.SUCCESS(f"  {count} deals created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Quotes
    # ─────────────────────────────────────────────────────────────

    def _create_quotes(self, quotes_data):
        """Create quotes linked to deals with proper status FK."""
        if not quotes_data:
            self.stdout.write("  No quotes to load")
            return

        count = 0
        for quote_data in quotes_data:
            quote_number = quote_data.get('number')
            deal_number = quote_data.get('deal_number')
            status_code = quote_data.get('status', 'DRAFT')

            if not quote_number or not deal_number:
                continue

            # Find the deal
            deal = Deal.objects.filter(title=deal_number).first()
            if not deal:
                self.stdout.write(self.style.WARNING(f"  ⚠ Deal '{deal_number}' not found"))
                continue

            status = QuoteStatus.objects.filter(code=status_code).first()
            if not status:
                status = QuoteStatus.objects.filter(code='DRAFT').first()

            # Parse valid_until
            valid_until = None
            try:
                valid_until = datetime.fromisoformat(
                    quote_data.get('valid_until', '').replace('Z', '+00:00')
                ).date()
            except (ValueError, TypeError):
                pass

            # Parse created_date
            try:
                created_date = datetime.fromisoformat(
                    quote_data.get('created_date', '').replace('Z', '+00:00')
                )
                created_date = timezone.make_aware(created_date)
            except (ValueError, TypeError):
                created_date = timezone.now()

            # Get next version number for this deal
            last_version = deal.quotes.aggregate(
                max_version=models.Max('version')
            )['max_version'] or 0
            next_version = last_version + 1

            obj, created = Quote.objects.get_or_create(
                deal=deal,
                version=next_version,
                defaults={
                    'status': status,
                    'prepared_by': deal.manager,
                    'valid_until': valid_until,
                    'vat_rate': Decimal('12.00'),
                    'subtotal_excl_vat': Decimal(str(quote_data.get('total_usd', 0))),
                    'vat_amount': Decimal('0'),
                    'total_incl_vat': Decimal(str(quote_data.get('total_usd', 0))),
                }
            )

            if created:
                count += 1
                Quote.objects.filter(pk=obj.pk).update(created_at=created_date)
                self.stdout.write(f"  ✓ Created quote: {quote_number} (v{next_version})")
            else:
                self.stdout.write(f"  - Quote already exists: {quote_number}")

        self.stdout.write(self.style.SUCCESS(f"  {count} quotes created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Messages (Deal Chat)
    # ─────────────────────────────────────────────────────────────

    def _create_messages(self, messages_data):
        """Create messages for deal chat."""
        if not messages_data:
            self.stdout.write("  No messages to load")
            return

        count = 0
        for msg_data in messages_data:
            msg_id = msg_data.get('id')
            deal_number = msg_data.get('deal_number')
            sender_name = msg_data.get('sender_name')
            text = msg_data.get('text', '')
            timestamp_str = msg_data.get('timestamp', '')

            if not deal_number:
                continue

            # Find the deal
            deal = Deal.objects.filter(title=deal_number).first()
            if not deal:
                self.stdout.write(self.style.WARNING(f"  ⚠ Deal '{deal_number}' not found for message"))
                continue

            # Try to find the sender by name or company
            # For demo, we'll use the manager if available, or any user from the company
            sender = None
            if deal.manager:
                sender = deal.manager
            else:
                # Find any user from the company
                from accounts.models import CompanyMember
                member = CompanyMember.objects.filter(company=deal.company).first()
                if member:
                    sender = member.user

            if not sender:
                self.stdout.write(
                    self.style.WARNING(f"  ⚠ No sender found for message in deal '{deal_number}'")
                )
                continue

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                timestamp = timezone.make_aware(timestamp)
            except (ValueError, TypeError):
                timestamp = timezone.now()

            obj, created = Message.objects.get_or_create(
                deal=deal,
                sender=sender,
                text=text,
                timestamp=timestamp,
                defaults={}
            )
            if created:
                count += 1
                self.stdout.write(f"  ✓ Created message in deal {deal_number}")
            else:
                self.stdout.write(f"  - Message already exists in deal {deal_number}")

        self.stdout.write(self.style.SUCCESS(f"  {count} messages created/updated"))

    # ─────────────────────────────────────────────────────────────
    # Notifications
    # ─────────────────────────────────────────────────────────────

    def _create_notifications(self, notifications_data):
        """Create notifications for users."""
        if not notifications_data:
            self.stdout.write("  No notifications to load")
            return

        count = 0
        for notif_data in notifications_data:
            notif_id = notif_data.get('id')
            type_code = notif_data.get('type', 'INFO')
            title = notif_data.get('title', '')
            message = notif_data.get('message', '')
            recipient_email = notif_data.get('recipient_email')

            if not title or not message:
                continue

            # Find recipient user
            recipient = None
            if recipient_email:
                recipient = User.objects.filter(email=recipient_email).first()
                if not recipient:
                    self.stdout.write(
                        self.style.WARNING(f"  ⚠ Recipient email '{recipient_email}' not found")
                    )

            # Map notification type (demo data might have custom types like "DEAL_CREATED")
            # For now, use INFO as default
            notif_type = NotificationType.objects.filter(code='INFO').first()
            if not notif_type:
                self.stdout.write(self.style.WARNING("  ⚠ NotificationType 'INFO' not found"))
                continue

            # Parse created_date
            try:
                created_date = datetime.fromisoformat(
                    notif_data.get('created_date', '').replace('Z', '+00:00')
                )
                created_date = timezone.make_aware(created_date)
            except (ValueError, TypeError):
                created_date = timezone.now()

            obj, created = Notification.objects.get_or_create(
                user=recipient,
                title=title,
                message=message,
                defaults={
                    'type': notif_type,
                    'link': '',
                    'is_read': False,
                }
            )

            if created:
                count += 1
                Notification.objects.filter(pk=obj.pk).update(created_at=created_date)
                self.stdout.write(f"  ✓ Created notification: {notif_id}")
            else:
                self.stdout.write(f"  - Notification already exists")

        self.stdout.write(self.style.SUCCESS(f"  {count} notifications created/updated"))
