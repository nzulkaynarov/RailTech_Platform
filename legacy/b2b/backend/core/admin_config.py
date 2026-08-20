"""Подмена сайта админки на инженерный (см. `core.admin_site`).

Django выбирает класс `admin.site` через `AppConfig.default_site` приложения, заменяющего
`django.contrib.admin` в `INSTALLED_APPS`. Так гейт входа применяется ко ВСЕМ вью админки
разом — включая стартовый экран с метриками платформы и поиск по админке, которые правами на
модели не закрываются.
"""

from django.contrib.admin.apps import AdminConfig


class EngineeringAdminConfig(AdminConfig):
    default_site = "core.admin_site.EngineeringAdminSite"
