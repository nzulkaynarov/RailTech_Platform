import json
import os
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    KYCDocType,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.models import DomainType, ProductStatus, StockStatus
from crm.models import ChargeTemplate, ChargeType, DealStage, QuoteStatus
from master_data.models import Country, Currency, DeliveryBasis, UnitOfMeasure
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
    help = "Seeds the database with master data (all names in Russian)."

    def handle(self, *args, **options):
        self.stdout.write("Загрузка справочников...")

        seed_data = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))

        # ─── 1. Страны ───
        countries = [
            ("UZ", "Узбекистан", "UZ", 12.00),
            ("KZ", "Казахстан", "KZ", 12.00),
            ("RU", "Россия", "RU", 20.00),
            ("CN", "Китай", "CN", 13.00),
            ("DE", "Германия", "DE", 19.00),
            ("TR", "Турция", "TR", 20.00),
            ("IN", "Индия", "IN", 18.00),
        ]
        for code, name, alpha2, vat in countries:
            _seed(Country, code, name=name, alpha2=alpha2, vat_rate=vat)

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

        # ─── 4. Базис поставки (полный Incoterms 2020 — все 11 терминов) ───
        # Флаги = матрица ответственности по расходам (кто несёт слой затрат).
        # (code, name, freight, insurance, import, delivery)
        bases = [
            ("EXW", "Франко-завод", False, False, False, False),
            ("FCA", "Франко-перевозчик", False, False, False, False),
            ("FAS", "Свободно вдоль борта судна", False, False, False, False),
            ("FOB", "Свободно на борту", False, False, False, False),
            ("CFR", "Стоимость и фрахт", True, False, False, False),
            ("CIF", "Стоимость, страхование и фрахт", True, True, False, False),
            ("CPT", "Перевозка оплачена до", True, False, False, False),
            ("CIP", "Перевозка и страхование оплачены до", True, True, False, False),
            ("DAP", "Поставка в место назначения", True, True, False, True),
            ("DPU", "Поставка в месте выгрузки", True, True, False, True),
            ("DDP", "Поставка с оплатой пошлин", True, True, True, True),
        ]
        for code, name, freight, insurance, imp, delivery in bases:
            _seed(
                DeliveryBasis,
                code,
                name=name,
                seller_pays_freight=freight,
                seller_pays_insurance=insurance,
                seller_pays_import=imp,
                seller_pays_delivery=delivery,
            )

        # ─── 4b. Статьи расхода КП (UBL document-level AllowanceCharge) ───
        # Стартовый набор; овнер пополняет справочник через админку. Сравнение в
        # коде идёт по агрегату сумм (не по конкретному code), поэтому набор —
        # удобство, а не контракт hot-path (IRON RULE 1).
        charge_types = [
            ("FREIGHT", "Фрахт / логистика"),
            ("INSURANCE", "Страхование груза"),
            ("CUSTOMS", "Таможенное оформление"),
            ("CERTIFICATION", "Сертификация"),
            ("RENT", "Аренда (склад/площадка)"),
            ("PAYROLL", "Оплата труда проектной команды"),
            ("COMMISSION", "Комиссионные выплаты"),
            ("DISCOUNT", "Скидка клиенту"),
            ("OTHER", "Прочие расходы"),
        ]
        for code, name in charge_types:
            _seed(ChargeType, code, name=name)

        # ─── 4c. Шаблоны статей расхода по базисам (Incoterm cost profiles) ───
        # При выборе базиса на КП эти статьи авто-добавляются (продавец потом правит).
        # Зеркалит матрицу ответственности: продавец видит только свои слои затрат.
        # Овнер кастомизирует шаблоны в админке (Справочник: Шаблоны статей расхода).
        charge_templates = {
            "CFR": ["FREIGHT"],
            "CPT": ["FREIGHT"],
            "CIF": ["FREIGHT", "INSURANCE"],
            "CIP": ["FREIGHT", "INSURANCE"],
            "DAP": ["FREIGHT", "INSURANCE"],
            "DPU": ["FREIGHT", "INSURANCE"],
            "DDP": ["FREIGHT", "INSURANCE", "CUSTOMS", "CERTIFICATION"],
        }
        for basis_code, type_codes in charge_templates.items():
            basis = DeliveryBasis.objects.filter(code=basis_code).first()
            if not basis:
                continue
            for order, type_code in enumerate(type_codes):
                charge_type = ChargeType.objects.filter(code=type_code).first()
                if charge_type:
                    ChargeTemplate.objects.update_or_create(
                        delivery_basis=basis,
                        charge_type=charge_type,
                        defaults={"sort_order": order},
                    )

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
            ("OWNER", "Владелец", []),
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

        # ─── 8. Типы KYC документов ───
        kyc_doc_types = [
            ("CHARTER", "Устав"),
            ("LICENSE", "Лицензия"),
            ("PASSPORT", "Паспорт руководителя"),
            ("TAX_CERT", "Свидетельство ИНН"),
            ("BANK_REF", "Банковская справка"),
            ("OTHER", "Прочий документ"),
        ]
        for code, name in kyc_doc_types:
            _seed(KYCDocType, code, name=name)

        # ─── 9. Статусы верификации ───
        v_statuses = [
            ("L1_UNVERIFIED", "Не верифицирован"),
            ("PROFILE_SUBMITTED", "Профиль на проверке"),
            ("L2_VERIFIED", "KYC подтверждён"),
            ("L3_CONTRACTED", "Договор заключён"),
            ("REJECTED", "Отклонён"),
        ]
        for code, name in v_statuses:
            _seed(VerificationStatus, code, name=name)

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
        stages = [
            ("DRAFT", "Черновик", 0),
            ("KYC_PENDING", "Ожидание KYC", 1),
            ("SOURCING", "Подбор поставщиков", 2),
            ("CALCULATING", "Расчёт цен", 3),
            ("QUOTE_SENT", "КП отправлено", 4),
            ("CONTRACT_SIGNED", "Договор подписан", 5),
            ("CLOSED_WON", "Закрыта (выиграна)", 6),
            ("CLOSED_LOST", "Закрыта (проиграна)", 7),
        ]
        for code, name, order in stages:
            _seed(DealStage, code, name=name, sort_order=order)

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
        for company_data in seed_data.get("companies", []):
            vs = None
            if company_data.get("verification_status"):
                vs = VerificationStatus.objects.filter(code=company_data["verification_status"]).first()
            company_obj, _ = Company.objects.get_or_create(
                inn=company_data["inn"],
                defaults={
                    "name": company_data["name"],
                    "legal_address": company_data.get("legal_address", ""),
                    "contact_person": company_data.get("contact_person", ""),
                    "email": company_data.get("email", ""),
                    "verification_status": vs,
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
                    CompanyMember.objects.get_or_create(
                        user=user_obj,
                        company=company,
                        defaults={
                            "role": ws_role,
                            "is_primary": True,
                            "is_active": True,
                        },
                    )

        # ─── 19. Подписки продавцов ───
        # Sellers (SUPPLIER / MANUFACTURER) need an operational subscription or the
        # F0.2 gate (assert_seller_can_operate) blocks send-КП / contract / invoice.
        # Default ACTIVE PREMIUM; a company may override via a `subscription` block in
        # seed_data.json (e.g. {"status": "PAST_DUE"}) to exercise the gate realistically.
        seller_type_codes = {"SUPPLIER"}
        usd = Currency.objects.filter(code="USD").first()
        today = timezone.now().date()
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
