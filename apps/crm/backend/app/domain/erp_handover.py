"""Запрос менеджеру «ERP недоступен» (M3-CRM-07): текст-метка и окно дедупликации.

Пока ERP лежит, каждый вопрос клиента о счёте или поставке заводил бы свой запрос. Код заводит один
запрос на клиента за сутки: повторные вопросы получают его номер.
"""

from datetime import timedelta
from typing import Final

SOURCE: Final = "erp_unavailable"
SUMMARY_PREFIX: Final = "Бот не смог получить данные из ERP (сервис недоступен). Вопрос клиента: "
DEDUPE_WINDOW: Final = timedelta(days=1)
