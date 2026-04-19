import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from master_data.models import Country, Currency, UnitOfMeasure, DeliveryBasis
from accounts.models import (
    SystemRole, WorkspaceRole, VerificationStatus,
    Company, CompanyMember, CompanyType, KYCDocType,
)
from catalog.models import ProductStatus, StockStatus, DomainType
from crm.models import DealStage, QuoteStatus
from notifications.models import NotificationType

User = get_user_model()
SEED_DATA_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'seed_data.json'


def _seed(model, code, **defaults):
    """update_or_create by code — обновляет name и прочие поля если запись уже есть."""
    obj, _created = model.objects.update_or_create(code=code, defaults=defaults)
    return obj


class Command(BaseCommand):
    help = 'Seeds the database with master data (all names in Russian).'

    def handle(self, *args, **options):
        self.stdout.write("Загрузка справочников...")

        seed_data = json.loads(SEED_DATA_PATH.read_text(encoding='utf-8'))

        # ─── 1. Страны ───
        countries = [
            ('UZ', 'Узбекистан', 'UZ', 12.00),
            ('KZ', 'Казахстан', 'KZ', 12.00),
            ('RU', 'Россия', 'RU', 20.00),
            ('CN', 'Китай', 'CN', 13.00),
            ('DE', 'Германия', 'DE', 19.00),
            ('TR', 'Турция', 'TR', 20.00),
            ('IN', 'Индия', 'IN', 18.00),
        ]
        for code, name, alpha2, vat in countries:
            _seed(Country, code, name=name, alpha2=alpha2, vat_rate=vat)

        # ─── 2. Валюты ───
        currencies = [
            ('UZS', 'Узбекский сўм', 'сўм'),
            ('USD', 'Доллар США', '$'),
            ('EUR', 'Евро', '€'),
            ('RUB', 'Российский рубль', '₽'),
            ('CNY', 'Китайский юань', '¥'),
        ]
        for code, name, symbol in currencies:
            _seed(Currency, code, name=name, symbol=symbol)

        # ─── 3. Единицы измерения ───
        uoms = [
            ('PCS', 'Штука'),
            ('KG', 'Килограмм'),
            ('M', 'Метр'),
            ('T', 'Тонна'),
            ('SET', 'Комплект'),
            ('L', 'Литр'),
            ('HR', 'Час'),
        ]
        for code, name in uoms:
            _seed(UnitOfMeasure, code, name=name)

        # ─── 4. Базис поставки (Incoterms) ───
        bases = [
            ('FCA', 'Франко-перевозчик'),
            ('DAP', 'Поставка в место назначения'),
            ('CPT', 'Перевозка оплачена до'),
            ('EXW', 'Франко-завод'),
            ('CIP', 'Перевозка и страхование оплачены до'),
        ]
        for code, name in bases:
            _seed(DeliveryBasis, code, name=name)

        # ─── 5. Системные роли ───
        # Только две: ADMIN (Platform Admin, владелец платформы) и USER.
        # Права внутри компаний регулируются WorkspaceRole.
        system_roles = [
            ('ADMIN', 'Администратор платформы'),
            ('USER', 'Пользователь'),
        ]
        for code, name in system_roles:
            _seed(SystemRole, code, name=name)

        # ─── 6. Роли в компании (типо-специфичные) ───
        from accounts.models import CompanyType
        workspace_roles = [
            # (code, name, applicable_company_type_codes)
            ('OWNER', 'Владелец', []),
            ('PROCUREMENT_MANAGER', 'Снабженец', ['CLIENT']),
            ('BUYER_MANAGER', 'Менеджер (Покупатель)', ['CLIENT']),
            ('SALES_MANAGER', 'Продавец', ['SUPPLIER']),
            ('LOGIST', 'Логист', ['SUPPLIER']),
            ('CONTRACT_MANAGER', 'Договорник', ['MANUFACTURER']),
            ('FOREIGN_TRADE_SPECIALIST', 'Специалист ВЭД', ['MANUFACTURER']),
        ]
        for code, name, applicable_codes in workspace_roles:
            wr = _seed(WorkspaceRole, code, name=name)
            if applicable_codes:
                types = CompanyType.objects.filter(code__in=applicable_codes)
                wr.applicable_to_types.set(list(types))
            else:
                wr.applicable_to_types.clear()

        # ─── 7. Типы компаний ───
        company_types = [
            ('CLIENT', 'Клиент'),
            ('SUPPLIER', 'Поставщик'),
            ('MANUFACTURER', 'Производитель'),
            ('LOGISTICS_PROVIDER', 'Логистический провайдер'),
        ]
        for code, name in company_types:
            _seed(CompanyType, code, name=name)

        # ─── 8. Типы KYC документов ───
        kyc_doc_types = [
            ('CHARTER', 'Устав'),
            ('LICENSE', 'Лицензия'),
            ('PASSPORT', 'Паспорт руководителя'),
            ('TAX_CERT', 'Свидетельство ИНН'),
            ('BANK_REF', 'Банковская справка'),
            ('OTHER', 'Прочий документ'),
        ]
        for code, name in kyc_doc_types:
            _seed(KYCDocType, code, name=name)

        # ─── 9. Статусы верификации ───
        v_statuses = [
            ('L1_UNVERIFIED', 'Не верифицирован'),
            ('PROFILE_SUBMITTED', 'Профиль на проверке'),
            ('L2_VERIFIED', 'KYC подтверждён'),
            ('L3_CONTRACTED', 'Договор заключён'),
            ('REJECTED', 'Отклонён'),
        ]
        for code, name in v_statuses:
            _seed(VerificationStatus, code, name=name)

        # ─── 10. Типы доменов каталога ───
        domains = [
            ('RAILWAY_MACHINERY', 'Ж/Д техника и запчасти', 'ЖД'),
            ('GENERAL_GOODS', 'Общие промышленные товары', 'ОТ'),
            ('SERVICES', 'Услуги (логистика, ремонт)', 'УС'),
        ]
        for code, name, prefix in domains:
            _seed(DomainType, code, name=name, sku_prefix=prefix)

        # ─── 11. Статусы товаров ───
        p_statuses = [
            ('DRAFT', 'Черновик'),
            ('PUBLISHED', 'Опубликован'),
            ('ARCHIVED', 'В архиве'),
        ]
        for code, name in p_statuses:
            _seed(ProductStatus, code, name=name)

        # ─── 12. Статусы наличия ───
        stock_statuses = [
            ('IN_STOCK', 'В наличии'),
            ('ON_ORDER', 'Под заказ'),
            ('EXPECTED', 'Ожидается'),
            ('OUT_OF_STOCK', 'Нет в наличии'),
        ]
        for code, name in stock_statuses:
            _seed(StockStatus, code, name=name)

        # ─── 13. Этапы сделок ───
        stages = [
            ('DRAFT', 'Черновик', 0),
            ('KYC_PENDING', 'Ожидание KYC', 1),
            ('SOURCING', 'Подбор поставщиков', 2),
            ('CALCULATING', 'Расчёт цен', 3),
            ('QUOTE_SENT', 'КП отправлено', 4),
            ('CONTRACT_SIGNED', 'Договор подписан', 5),
            ('CLOSED_WON', 'Закрыта (выиграна)', 6),
            ('CLOSED_LOST', 'Закрыта (проиграна)', 7),
        ]
        for code, name, order in stages:
            _seed(DealStage, code, name=name, sort_order=order)

        # ─── 14. Статусы КП ───
        q_statuses = [
            ('DRAFT', 'Черновик'),
            ('SENT', 'Отправлено клиенту'),
            ('APPROVED', 'Одобрено клиентом'),
            ('REJECTED', 'Отклонено'),
            ('EXPIRED', 'Срок истёк'),
        ]
        for code, name in q_statuses:
            _seed(QuoteStatus, code, name=name)

        # ─── 15. Типы уведомлений ───
        notif_types = [
            ('INFO', 'Информация'),
            ('SUCCESS', 'Успех'),
            ('WARNING', 'Предупреждение'),
            ('ERROR', 'Ошибка'),
            ('SYSTEM', 'Системное'),
        ]
        for code, name in notif_types:
            _seed(NotificationType, code, name=name)

        # ─── 16. Ключевые слова Smart Match ───
        from sourcing.models import DomainKeyword
        keywords = {
            'RAILWAY_MACHINERY': [
                'тепловоз', 'локомотив', 'вагон', 'двигатель',
                'колесная пара', 'рельс', 'шпала', 'подшипник',
                'компрессор', 'генератор', 'тормоз',
            ],
            'SERVICES': [
                'доставка', 'ремонт', 'услуга', 'аренда',
                'логистика', 'перевозка', 'монтаж', 'диагностика',
            ],
        }
        for dom_code, kws in keywords.items():
            dom = DomainType.objects.get(code=dom_code)
            for kw in kws:
                DomainKeyword.objects.get_or_create(keyword=kw, defaults={'domain_type': dom})

        # ─── 17. Компании из seed_data.json ───
        for company_data in seed_data.get('companies', []):
            vs = None
            if company_data.get('verification_status'):
                vs = VerificationStatus.objects.filter(code=company_data['verification_status']).first()
            Company.objects.get_or_create(
                inn=company_data['inn'],
                defaults={
                    'name': company_data['name'],
                    'legal_address': company_data.get('legal_address', ''),
                    'contact_person': company_data.get('contact_person', ''),
                    'email': company_data.get('email', ''),
                    'verification_status': vs,
                },
            )

        # ─── 18. Тестовые пользователи из seed_data.json ───
        for user_data in seed_data.get('test_users', []):
            email_env = user_data.get('email_env')
            email = os.environ.get(email_env, user_data['email_default']) if email_env else user_data['email_default']
            password_env = user_data.get('password_env')
            password = os.environ.get(password_env, user_data['password_default']) if password_env else user_data['password_default']
            sys_role = SystemRole.objects.filter(code=user_data['role']).first()

            user_obj, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email.split('@')[0],
                    'first_name': user_data.get('first_name', ''),
                    'last_name': user_data.get('last_name', ''),
                    'role': sys_role,
                    'is_staff': user_data.get('is_staff', False),
                    'is_superuser': user_data.get('is_superuser', False),
                    'is_active': True,
                },
            )
            if created:
                user_obj.set_password(password)
                user_obj.save()
                self.stdout.write(f"  Пользователь создан: {email}")

            # Company membership
            company_inn = user_data.get('company_inn')
            ws_role_code = user_data.get('workspace_role')
            if company_inn and ws_role_code:
                company = Company.objects.filter(inn=company_inn).first()
                ws_role = WorkspaceRole.objects.filter(code=ws_role_code).first()
                if company and ws_role:
                    CompanyMember.objects.get_or_create(
                        user=user_obj,
                        company=company,
                        defaults={
                            'role': ws_role,
                            'is_primary': True,
                            'is_active': True,
                        },
                    )

        self.stdout.write(self.style.SUCCESS("Справочники загружены!"))
