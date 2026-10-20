"""Сохранение отрендеренного PDF в документ (FIX-2xa).

Рендер идёт долго (WeasyPrint, Celery), а объект прочитан ДО него. Полный ``save()`` после рендера
записал бы поверх БД устаревшие статус, даты и прочие поля — например, ``SENT`` поверх ``APPROVED``,
если клиент принял КП, пока шёл рендер. Поэтому рендер пишет ТОЛЬКО поле файла.
"""

from django.core.files.base import ContentFile


def save_rendered_pdf(instance, filename: str, content: ContentFile, field: str = "pdf_file") -> None:
    """Записать файл в ``field`` и обновить в БД только это поле (``update_fields``)."""
    getattr(instance, field).save(filename, content, save=False)
    instance.save(update_fields=[field])
