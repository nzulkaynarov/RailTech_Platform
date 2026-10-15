"""Согласование формата ответа API: только JSON, без 406 (M1-ERP-07).

API отдаёт один формат — JSON (`DEFAULT_RENDERER_CLASSES`): Browsable API DRF раскрывал
справочники в HTML-формах. Но браузер приходит с `Accept: text/html`, и стандартное согласование
DRF отвечало бы 406 ещё до вьюхи — а публичные страницы (КП и документы по токену) сами решают по
`Accept`, отдать ли HTML-страницу через `django.shortcuts.render`. Поэтому при неприемлемом `Accept`
выбираем JSON, а не отказ.
"""

from rest_framework.exceptions import NotAcceptable
from rest_framework.negotiation import DefaultContentNegotiation


class JSONFallbackContentNegotiation(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        try:
            return super().select_renderer(request, renderers, format_suffix)
        except NotAcceptable:
            renderer = renderers[0]
            return renderer, renderer.media_type
