"""Проставить `L1_UNVERIFIED` компаниям, которые остались вообще без статуса KYC.

Поле nullable исторически, и часть путей создания его не заполняла (компания, заведённая
оператором из панели; оффлайн-клиент из адресной книги продавца). На дев-стенде так жили 15
компаний из 42: в реестре KYC они показывались с подстановочным бейджем, но не попадали ни в
одну вкладку — счётчики «На проверке» и «Не верифицированы» стояли на нуле при пятнадцати таких
строках. Оператор видел реестр, в котором сумма вкладок не сходится с итогом.

«Нет статуса» и «не верифицирован» различимы только для базы; для человека и для фильтра это
одно состояние — храним одно. Новые записи получают его в `Company.save`.

Откат — не возвращать NULL: восстанавливать состояние «ни в одной вкладке» бессмысленно.
"""

from django.db import migrations

L1_UNVERIFIED = "L1_UNVERIFIED"


def backfill(apps, schema_editor):
    Company = apps.get_model("accounts", "Company")
    VerificationStatus = apps.get_model("accounts", "VerificationStatus")

    unverified = VerificationStatus.objects.filter(code=L1_UNVERIFIED).first()
    if unverified is None:
        # Справочник сеется миграцией (Rule 1); если его тут нет — база собрана не по схеме,
        # и молча ставить «что-нибудь» хуже, чем не делать ничего.
        return
    Company.objects.filter(verification_status__isnull=True).update(verification_status=unverified)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0045_strip_staff_flag_from_non_engineers"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=migrations.RunPython.noop),
    ]
