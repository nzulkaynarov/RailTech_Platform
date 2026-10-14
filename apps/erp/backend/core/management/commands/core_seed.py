import json
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, SupplierSubscription, SystemRole, WorkspaceRole
from catalog.models import DomainType, ProductStatus, StockStatus
from crm.models import DealStage, QuoteStatus
from master_data.models import Currency
from notifications.models import NotificationType

User = get_user_model()
SEED_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "seed_data.json"

# Dev/demo default login for seeded test users (NOT production data — this command
# is dev/demo-only per IRON RULE 1). Override with the SEED_USER_PASSWORD env var.
# Superusers are exempt: their password comes from SUPERADMIN_PASSWORD / init_superadmin.
DEFAULT_SEED_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "Demo1234!")


def _seed(model, code, **defaults):
    """update_or_create by code — обновляет name и прочие поля если запись уже есть."""
    obj, _created = model.objects.update_or_create(code=code, defaults=defaults)
    return obj


class Command(BaseCommand):
    help = "Seeds the database with master data + DEMO users (dev/demo only, all names in Russian)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-prod",
            action="store_true",
            help="Override the DEBUG=False safety guard (dangerous — creates demo login "
            "accounts with a known password).",
        )

    def handle(self, *args, **options):
        # SEC-03: this command creates DEMO login accounts with DEFAULT_SEED_PASSWORD.
        # Business lookups on prod come from data migrations (Rule 1), not from here — so
        # refuse to run against a non-DEBUG environment unless explicitly forced.
        if not settings.DEBUG and not options.get("force_prod"):
            raise CommandError(
                "core_seed is a dev/demo seeder and creates accounts with a known password. "
                "Refusing to run with DEBUG=False. Prod lookups come from migrations. "
                "Pass --force-prod only if you truly intend to seed demo data in production."
            )
        self.stdout.write("Загрузка справочников...")

        seed_data = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))

        # ─── 1. Страны ───
        # Справочник стран целиком (ISO 3166-1) сеет миграция master_data/0015 — здесь его
        # больше нет намеренно: две копии перечня расходятся, а ставки НДС из дев-сида уже
        # однажды перетирали выверенные (миграция 0003).

        # ─── 2. Валюты ───
        currencies = [
            ("UZS", "Узбекский сўм", "сўм"),
            ("USD", "Доллар США", "$"),
            ("EUR", "Евро", "€"),
            ("RUB", "Российский рубль", "₽"),
            ("CNY", "Китайский юань", "¥"),
        ]
        for code, name, symbol in currencies:
            _seed(Currency, code, name=name, symbol=symbol)

        # ─── 3. Единицы измерения ───
        # Source of truth = master_data migration 0005_seed_uom_unece (UN/ECE Rec 20),
        # consolidated by 0006. core_seed no longer seeds a competing legacy set
        # (PCS/KG/M/T/L/HR с полными именами) — это и создавало «кашу» дублей
        # (кг=KG+KGM, м=M+MTR, …). UOM-справочник тут больше не трогаем.

        # ─── 4. Базис поставки + 4b/4c. Статьи и шаблоны расхода КП ───
        # MOVED OUT (B3 fix): the Incoterms 2020 DeliveryBasis rows + flags, the
        # ChargeType catalog, and the GLOBAL (company IS NULL) ChargeTemplate cost
        # profiles are now seeded by idempotent data migrations so a clean production
        # DB has a working basis/charge engine on day one (IRON RULE 1):
        #   - master_data/migrations/0008_seed_delivery_basis_incoterms.py
        #   - crm/migrations/0036_seed_charge_engine.py
        # core_seed (dev/demo-only) no longer owns these business lookups.

        # ─── 5. Системные роли ───
        # Только две: ADMIN (Platform Admin, владелец платформы) и USER.
        # Права внутри компаний регулируются WorkspaceRole.
        system_roles = [
            ("ADMIN", "Администратор платформы"),
            ("USER", "Пользователь"),
        ]
        for code, name in system_roles:
            _seed(SystemRole, code, name=name)

        # ─── 6. Роли в компании (типо-специфичные) ───
        workspace_roles = [
            # (code, name, applicable_company_type_codes)
            ("OWNER", "Администратор компании", []),
            ("PROCUREMENT_MANAGER", "Снабженец", ["CLIENT"]),
            ("BUYER_MANAGER", "Менеджер (Покупатель)", ["CLIENT"]),
            ("SALES_MANAGER", "Продавец", ["SUPPLIER"]),
            ("LOGIST", "Логист", ["SUPPLIER"]),
            ("CONTRACT_MANAGER", "Договорник", ["SUPPLIER"]),
            ("FOREIGN_TRADE_SPECIALIST", "Специалист ВЭД", ["SUPPLIER"]),
        ]
        for code, name, applicable_codes in workspace_roles:
            wr = _seed(WorkspaceRole, code, name=name)
            if applicable_codes:
                types = CompanyType.objects.filter(code__in=applicable_codes)
                wr.applicable_to_types.set(list(types))
            else:
                wr.applicable_to_types.clear()

        # ─── 7. Типы компаний ───
        # Roles consolidated to SELLER (SUPPLIER) + BUYER (CLIENT) on 2026-06-23;
        # MANUFACTURER retired as a participant type (now only catalog.Manufacturer brand).
        company_types = [
            ("CLIENT", "Клиент"),
            ("SUPPLIER", "Поставщик"),
            ("LOGISTICS_PROVIDER", "Логистический провайдер"),
        ]
        for code, name in company_types:
            _seed(CompanyType, code, name=name)

        # ─── 10. Типы доменов каталога ───
        domains = [
            ("RAILWAY_MACHINERY", "Ж/Д техника и запчасти", "ЖД"),
            ("GENERAL_GOODS", "Общие промышленные товары", "ОТ"),
            ("SERVICES", "Услуги (логистика, ремонт)", "УС"),
        ]
        for code, name, prefix in domains:
            _seed(DomainType, code, name=name, sku_prefix=prefix)

        # ─── 11. Статусы товаров ───
        p_statuses = [
            ("DRAFT", "Черновик"),
            ("PUBLISHED", "Опубликован"),
            ("ARCHIVED", "В архиве"),
        ]
        for code, name in p_statuses:
            _seed(ProductStatus, code, name=name)

        # ─── 12. Статусы наличия ───
        stock_statuses = [
            ("IN_STOCK", "В наличии"),
            ("ON_ORDER", "Под заказ"),
            ("EXPECTED", "Ожидается"),
            ("OUT_OF_STOCK", "Нет в наличии"),
        ]
        for code, name in stock_statuses:
            _seed(StockStatus, code, name=name)

        # ─── 13. Этапы сделок ───
        # Порядок — из ЕДИНОГО канона DEAL_STAGE_CANONICAL_ORDER (crm/constants): этот список
        # раньше жил своей жизнью (0-7, БЕЗ RFQ_OPEN) и при каждом `make seed` перетирал порядок,
        # ломая воронку («Заявка открыта» в хвосте) — ресерч 2026-07-28.
        from crm.constants import DEAL_STAGE_CANONICAL_ORDER

        stage_names = {
            "DRAFT": "Черновик",
            "KYC_PENDING": "Ожидание KYC",
            "RFQ_OPEN": "Заявка открыта",
            "SOURCING": "Подбор поставщиков",
            "CALCULATING": "Расчёт цен",
            "QUOTE_SENT": "КП отправлено",
            "CONTRACT_SIGNED": "Договор подписан",
            "CLOSED_WON": "Закрыта (выиграна)",
            "CLOSED_LOST": "Закрыта (проиграна)",
        }
        for code, order in DEAL_STAGE_CANONICAL_ORDER.items():
            # KYC_PENDING выведен из эксплуатации (28-07): строка живёт (история/FK),
            # но неактивна — активные списки этапов её не отдают.
            _seed(DealStage, code, name=stage_names[code], sort_order=order, is_active=(code != "KYC_PENDING"))

        # ─── 14. Статусы КП ───
        q_statuses = [
            ("DRAFT", "Черновик"),
            ("SENT", "Отправлено клиенту"),
            ("APPROVED", "Одобрено клиентом"),
            ("REJECTED", "Отклонено"),
            ("EXPIRED", "Срок истёк"),
        ]
        for code, name in q_statuses:
            _seed(QuoteStatus, code, name=name)

        # ─── 15. Типы уведомлений ───
        notif_types = [
            ("INFO", "Информация"),
            ("SUCCESS", "Успех"),
            ("WARNING", "Предупреждение"),
            ("ERROR", "Ошибка"),
            ("SYSTEM", "Системное"),
        ]
        for code, name in notif_types:
            _seed(NotificationType, code, name=name)

        # ─── 16. Ключевые слова Smart Match ───
        from sourcing.models import DomainKeyword

        keywords = {
            "RAILWAY_MACHINERY": [
                "тепловоз",
                "локомотив",
                "вагон",
                "двигатель",
                "колесная пара",
                "рельс",
                "шпала",
                "подшипник",
                "компрессор",
                "генератор",
                "тормоз",
            ],
            "SERVICES": [
                "доставка",
                "ремонт",
                "услуга",
                "аренда",
                "логистика",
                "перевозка",
                "монтаж",
                "диагностика",
            ],
        }
        for dom_code, kws in keywords.items():
            dom = DomainType.objects.get(code=dom_code)
            for kw in kws:
                DomainKeyword.objects.get_or_create(keyword=kw, defaults={"domain_type": dom})

        # ─── 17. Компании из seed_data.json ───
        # Статус верификации в seed_data.json — наследие KYC (удалён в M1-ERP-02 волна 1c),
        # игнорируется.
        for company_data in seed_data.get("companies", []):
            company_obj, _ = Company.objects.get_or_create(
                inn=company_data["inn"],
                defaults={
                    "name": company_data["name"],
                    "legal_address": company_data.get("legal_address", ""),
                    "contact_person": company_data.get("contact_person", ""),
                    "email": company_data.get("email", ""),
                },
            )
            # Assign CompanyType(s) — WITHOUT this a seeded company has empty types
            # and the frontend has no buyer/seller context (loadFromAuth → activeStatus).
            # Accepts a single `company_type` or a `company_types` list; codes from the DB.
            type_codes = company_data.get("company_types") or [company_data.get("company_type")]
            type_codes = [c for c in type_codes if c]
            if type_codes:
                company_obj.types.set(CompanyType.objects.filter(code__in=type_codes))

        # ─── 18. Тестовые пользователи из seed_data.json ───
        for user_data in seed_data.get("test_users", []):
            email_env = user_data.get("email_env")
            email = os.environ.get(email_env, user_data["email_default"]) if email_env else user_data["email_default"]
            password_env = user_data.get("password_env")
            # Resolve: explicit env → JSON default → dev fallback. Superusers get NO
            # dev fallback (their secret comes from SUPERADMIN_PASSWORD / init_superadmin).
            password = os.environ.get(password_env) if password_env else None
            if password is None:
                password = user_data.get("password_default")
            if password is None and not user_data.get("is_superuser"):
                password = DEFAULT_SEED_PASSWORD
            sys_role = SystemRole.objects.filter(code=user_data["role"]).first()

            user_obj, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email.split("@")[0],
                    "first_name": user_data.get("first_name", ""),
                    "last_name": user_data.get("last_name", ""),
                    "role": sys_role,
                    "is_staff": user_data.get("is_staff", False),
                    "is_superuser": user_data.get("is_superuser", False),
                    "is_active": True,
                },
            )
            # Set the password every run (idempotent) so a user created earlier without
            # one — e.g. auto-created by a deal/quote reference — becomes login-able.
            if password and not user_obj.check_password(password):
                user_obj.set_password(password)
                user_obj.save(update_fields=["password"])
            if created:
                self.stdout.write(f"  Пользователь создан: {email}")

            # Company membership
            # Platform Admin (SystemRole=ADMIN) cannot be a CompanyMember —
            # invariant enforced by accounts/migrations/0010_platform_admin_model.
            company_inn = user_data.get("company_inn")
            ws_role_code = user_data.get("workspace_role")
            if sys_role and sys_role.code == "ADMIN":
                continue
            if company_inn and ws_role_code:
                company = Company.objects.filter(inn=company_inn).first()
                ws_role = WorkspaceRole.objects.filter(code=ws_role_code).first()
                if company and ws_role:
                    member, _member_created = CompanyMember.objects.get_or_create(
                        user=user_obj,
                        company=company,
                        defaults={
                            "role": ws_role,
                            "is_primary": True,
                            "is_active": True,
                        },
                    )
                    # Роль КОМПАНИИ (не WorkspaceRole) — источник прав в `capabilities.permissions`,
                    # по которым строится меню (ADR-0005). Сид её не ставил, и свежий локальный
                    # стенд получался НЕПРИГОДНЫМ: у демо-продавца и демо-покупателя приходил
                    # пустой список прав, меню не рисовало ни одного пункта, и проверить роль
                    # глазами было нельзя вовсе. Боевые пути (саморегистрация `submit_profile`,
                    # приглашение `invite_workspace_member`) роль проставляют — расходился только
                    # dev-сид. Тот же сервис, что и на боевых путях, поэтому набор прав совпадает.
                    if member.company_role_id is None:
                        from accounts.services.roles import default_company_role_for

                        member.company_role = default_company_role_for(company, ws_role.code)
                        member.save(update_fields=["company_role"])

        # ─── 19. Подписки продавцов ───
        # Sellers (SUPPLIER / MANUFACTURER) need an operational subscription or the
        # F0.2 gate (assert_seller_can_operate) blocks send-КП / contract / invoice.
        # Default ACTIVE PREMIUM; a company may override via a `subscription` block in
        # seed_data.json (e.g. {"status": "PAST_DUE"}) to exercise the gate realistically.
        seller_type_codes = {"SUPPLIER"}
        usd = Currency.objects.filter(code="USD").first()
        today = timezone.localdate()
        plan_rates = {"BASIC": "150", "STANDARD": "400", "PREMIUM": "900"}
        for company_data in seed_data.get("companies", []):
            codes = set(company_data.get("company_types") or [company_data.get("company_type")])
            if not (codes & seller_type_codes):
                continue
            company = Company.objects.filter(inn=company_data["inn"]).first()
            if not company:
                continue
            sub_cfg = company_data.get("subscription") or {}
            plan = sub_cfg.get("plan", "PREMIUM")
            sub_status = sub_cfg.get("status", "ACTIVE")
            # PAST_DUE/SUSPENDED/CANCELLED → expired window so is_operational is False.
            valid_until = today - timedelta(days=1) if sub_status != "ACTIVE" else today + timedelta(days=365)
            SupplierSubscription.objects.update_or_create(
                company=company,
                defaults={
                    "plan": plan,
                    "status": sub_status,
                    "monthly_rate": plan_rates.get(plan, "0"),
                    "currency": usd,
                    "valid_from": today,
                    "valid_until": valid_until,
                },
            )

        self.stdout.write(self.style.SUCCESS("Справочники загружены!"))
