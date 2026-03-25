"""
Management command: seed S3 (MinIO) with test data.

Tests ALL storage integration paths:
  1. Public bucket  — product images, company logos, user avatars, category icons
  2. Private bucket — KYC documents, deal attachments, quote PDFs

Usage:
  python manage.py seed_s3_test_data
"""

import io
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils import timezone


def _make_svg(text, color="#3B82F6", bg="#EFF6FF"):
    """Generate a minimal SVG placeholder image."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        f'<rect width="400" height="300" fill="{bg}"/>'
        f'<text x="200" y="160" text-anchor="middle" font-family="Arial" '
        f'font-size="24" fill="{color}">{text}</text>'
        f'</svg>'
    )
    return ContentFile(svg.encode(), name=f"{text.replace(' ', '_').lower()}.svg")


def _make_pdf(title):
    """Generate a minimal PDF file."""
    pdf_content = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
        b"/Resources<</Font<</F1 4 0 R>>>>>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 5\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    return ContentFile(pdf_content, name=f"{title}.pdf")


def _make_txt(content):
    """Generate a text file."""
    return ContentFile(content.encode(), name="document.txt")


def _make_xlsx_stub():
    """Generate a minimal Excel-like file (just bytes for testing)."""
    return ContentFile(b"PK\x03\x04" + b"\x00" * 100, name="import_template.xlsx")


class Command(BaseCommand):
    help = "Seed MinIO/S3 with test data for all storage integration paths"

    def handle(self, *args, **options):
        from accounts.models import Company, CustomUser, KYCDocument, KYCDocType
        from catalog.models import (
            Product, ProductImage, ProductDocument, Category,
            DomainType, ProductStatus, EquipmentGroup
        )
        from crm.models import Deal, DealStage, Quote, QuoteStatus, Message
        from sourcing.models import Attachment
        from notifications.models import Notification, NotificationType

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("  SEED S3 TEST DATA")
        self.stdout.write("=" * 60 + "\n")

        admin = CustomUser.objects.filter(is_superuser=True).first()
        if not admin:
            self.stderr.write(self.style.ERROR("Superuser not found! Run init_superadmin first."))
            return

        # ─── 1. COMPANY LOGOS (public) ───

        self.stdout.write(self.style.MIGRATE_HEADING("1. Company logos (public bucket)"))
        companies = Company.objects.all()
        for company in companies:
            if not company.logo:
                company.logo = _make_svg(
                    company.name[:12], color="#1E40AF", bg="#DBEAFE"
                )
                company.save(update_fields=["logo"])
                self.stdout.write(f"   Logo: {company.name} -> {company.logo.name}")
            else:
                self.stdout.write(f"   Skip: {company.name} (already has logo)")

        # ─── 2. USER AVATARS (public) ───

        self.stdout.write(self.style.MIGRATE_HEADING("2. User avatars (public bucket)"))
        users = CustomUser.objects.all()
        for user in users:
            if not user.avatar:
                initials = (user.first_name[:1] + user.last_name[:1]).upper() or user.email[:2].upper()
                user.avatar = _make_svg(initials, color="#059669", bg="#D1FAE5")
                user.save(update_fields=["avatar"])
                self.stdout.write(f"   Avatar: {user.email} -> {user.avatar.name}")
            else:
                self.stdout.write(f"   Skip: {user.email} (already has avatar)")

        # ─── 3. CATEGORY ICONS (public) ───

        self.stdout.write(self.style.MIGRATE_HEADING("3. Category icons (public bucket)"))
        categories = Category.objects.all()
        for cat in categories:
            if not cat.icon:
                cat.icon = _make_svg(cat.name[:10], color="#7C3AED", bg="#EDE9FE")
                cat.save(update_fields=["icon"])
                self.stdout.write(f"   Icon: {cat.name} -> {cat.icon.name}")

        # ─── 4. PRODUCT IMAGES (public) ───

        self.stdout.write(self.style.MIGRATE_HEADING("4. Product images (public bucket)"))
        products = Product.objects.all()
        for product in products:
            if not product.images.exists():
                img = ProductImage.objects.create(
                    product=product,
                    image=_make_svg(product.name[:15], color="#DC2626", bg="#FEE2E2"),
                    is_main=True,
                    alt_text=product.name,
                )
                self.stdout.write(f"   Image: {product.name} -> {img.image.name}")

                # Add a second image
                img2 = ProductImage.objects.create(
                    product=product,
                    image=_make_svg(f"{product.name[:10]} #2", color="#EA580C", bg="#FFF7ED"),
                    is_main=False,
                    alt_text=f"{product.name} - detail",
                    sort_order=1,
                )
                self.stdout.write(f"   Image: {product.name} (detail) -> {img2.image.name}")

        # ─── 5. PRODUCT DOCUMENTS (public) ───

        self.stdout.write(self.style.MIGRATE_HEADING("5. Product documents (public bucket)"))
        for product in products:
            if not product.documents.exists():
                doc = ProductDocument.objects.create(
                    product=product,
                    file=_make_pdf(f"passport_{product.sku}"),
                    name=f"Паспорт изделия {product.name}",
                )
                self.stdout.write(f"   Doc: {product.name} -> {doc.file.name}")

                doc2 = ProductDocument.objects.create(
                    product=product,
                    file=_make_pdf(f"gost_{product.sku}"),
                    name=f"Сертификат ГОСТ {product.name}",
                )
                self.stdout.write(f"   Doc: {product.name} (GOST) -> {doc2.file.name}")

        # ─── 6. KYC DOCUMENTS (private) ───

        self.stdout.write(self.style.MIGRATE_HEADING("6. KYC documents (private bucket)"))
        kyc_types = KYCDocType.objects.all()
        for company in companies:
            if not company.kyc_documents.exists() and kyc_types.exists():
                for doc_type in kyc_types[:3]:
                    kyc = KYCDocument.objects.create(
                        company=company,
                        doc_type=doc_type,
                        file=_make_pdf(f"kyc_{company.inn}_{doc_type.code}"),
                        original_filename=f"{doc_type.name}_{company.name}.pdf",
                    )
                    self.stdout.write(
                        f"   KYC: {company.name} / {doc_type.name} -> {kyc.file.name}"
                    )

        # ─── 7. DEAL ATTACHMENTS (private) ───

        self.stdout.write(self.style.MIGRATE_HEADING("7. Deal attachments (private bucket)"))
        deals = Deal.objects.all()
        for deal in deals:
            if not deal.attachments.exists():
                att = Attachment.objects.create(
                    file=_make_xlsx_stub(),
                    original_filename=f"Заявка_{deal.title or deal.pk}.xlsx",
                    uploaded_by=admin,
                    deal=deal,
                )
                self.stdout.write(f"   Attachment: Deal #{deal.pk} -> {att.file.name}")

                att2 = Attachment.objects.create(
                    file=_make_pdf(f"contract_deal_{deal.pk}"),
                    original_filename=f"Договор_{deal.title or deal.pk}.pdf",
                    uploaded_by=admin,
                    deal=deal,
                )
                self.stdout.write(f"   Attachment: Deal #{deal.pk} (contract) -> {att2.file.name}")

        # ─── 8. COMPANY ATTACHMENTS (private) ───

        self.stdout.write(self.style.MIGRATE_HEADING("8. Company attachments (private bucket)"))
        for company in companies:
            if not company.attachments.exists():
                att = Attachment.objects.create(
                    file=_make_pdf(f"nda_{company.inn}"),
                    original_filename=f"NDA_{company.name}.pdf",
                    uploaded_by=admin,
                    company=company,
                )
                self.stdout.write(f"   Attachment: {company.name} -> {att.file.name}")

        # ─── 9. QUOTE PDF (private) ───

        self.stdout.write(self.style.MIGRATE_HEADING("9. Quote PDFs (private bucket)"))
        # Create a quote if none exists
        if not Quote.objects.exists() and deals.exists():
            draft_status = QuoteStatus.objects.filter(code='DRAFT').first()
            deal = deals.first()
            if draft_status and deal:
                quote = Quote.objects.create(
                    deal=deal,
                    version=1,
                    status=draft_status,
                    prepared_by=admin,
                    vat_rate=12,
                )
                quote.pdf_file = _make_pdf(f"quote_v{quote.version}_{deal.pk}")
                quote.save(update_fields=["pdf_file"])
                self.stdout.write(
                    f"   Quote PDF: Deal #{deal.pk} v{quote.version} -> {quote.pdf_file.name}"
                )

        for quote in Quote.objects.filter(pdf_file=''):
            quote.pdf_file = _make_pdf(f"quote_v{quote.version}_{quote.deal_id}")
            quote.save(update_fields=["pdf_file"])
            self.stdout.write(
                f"   Quote PDF: Deal #{quote.deal_id} v{quote.version} -> {quote.pdf_file.name}"
            )

        # ─── SUMMARY ───

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("  S3 INTEGRATION SUMMARY"))
        self.stdout.write("=" * 60)

        # Count files in MinIO
        from core.storage import _minio_is_configured
        if _minio_is_configured():
            self.stdout.write(self.style.SUCCESS(f"  Storage: MinIO (S3)"))
        else:
            self.stdout.write(self.style.WARNING(f"  Storage: Local FileSystem (MinIO not configured)"))

        self.stdout.write(f"\n  PUBLIC BUCKET (railtech-public):")
        self.stdout.write(f"    Company logos:    {Company.objects.exclude(logo='').count()}")
        self.stdout.write(f"    User avatars:     {CustomUser.objects.exclude(avatar='').count()}")
        self.stdout.write(f"    Category icons:   {Category.objects.exclude(icon='').count()}")
        self.stdout.write(f"    Product images:   {ProductImage.objects.count()}")
        self.stdout.write(f"    Product docs:     {ProductDocument.objects.count()}")

        self.stdout.write(f"\n  PRIVATE BUCKET (railtech-private):")
        self.stdout.write(f"    KYC documents:    {KYCDocument.objects.count()}")
        self.stdout.write(f"    Deal attachments: {Attachment.objects.filter(deal__isnull=False).count()}")
        self.stdout.write(f"    Company docs:     {Attachment.objects.filter(company__isnull=False).count()}")
        self.stdout.write(f"    Quote PDFs:       {Quote.objects.exclude(pdf_file='').count()}")

        total = (
            Company.objects.exclude(logo='').count()
            + CustomUser.objects.exclude(avatar='').count()
            + Category.objects.exclude(icon='').count()
            + ProductImage.objects.count()
            + ProductDocument.objects.count()
            + KYCDocument.objects.count()
            + Attachment.objects.count()
            + Quote.objects.exclude(pdf_file='').count()
        )
        self.stdout.write(f"\n  TOTAL FILES: {total}")
        self.stdout.write("=" * 60 + "\n")
