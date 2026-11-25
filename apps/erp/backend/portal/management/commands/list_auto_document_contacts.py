"""Список контактов компаний, которые прежний выпуск ссылок документов завёл по адресу получателя (В-1, 2026-11-25).

Только чтение: ничего не удаляет и не меняет. Нужен владельцу, чтобы просмотреть адреса, у которых до поправки был
вход во весь кабинет компании, и убрать лишних в карточке компании.
"""

from django.core.management.base import BaseCommand
from portal.services.doc_links import auto_created_document_contacts


class Command(BaseCommand):
    help = "Показать контакты, заведённые ссылками документов автоматически (только чтение)."

    def handle(self, *args, **options):
        rows = auto_created_document_contacts()
        self.stdout.write(
            "contact_id\tcompany_id\tcompany\temail\tcreated_at\tinvited_at\tlast_login_at\tarchived\tlinks"
        )
        for row in rows:
            self.stdout.write(
                "\t".join(
                    str(row[key])
                    for key in (
                        "contact_id",
                        "company_id",
                        "company",
                        "email",
                        "created_at",
                        "invited_at",
                        "last_login_at",
                        "archived",
                        "links",
                    )
                )
            )
        self.stdout.write(f"всего: {len(rows)}")
