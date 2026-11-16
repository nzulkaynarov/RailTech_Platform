"""Письма компании в кабинете (ЛИД-8, ADR-0026): `GET /letters`, `GET /letters/{id}`, `GET /letters/{id}/file`.

Модуль `letters` — у обеих ролей и не выключается (`roles.ALWAYS_ON`). Компания — только из сессии: чужое письмо
отвечает 404. Файл есть только у нашего исходящего: ERP берёт его у EDS по сервисному токену и отдаёт кабинету;
EDS недоступен или токен не задан — 503 `LETTER_FILE_UNAVAILABLE`. Логика — `portal/services/letters.py`.
"""

import datetime
from urllib.parse import quote

from django.http import Http404, HttpResponse
from portal.exceptions import PortalUnavailable, PortalValidationError
from portal.models import LetterDirection
from portal.serializers import PortalLetterSerializer
from portal.services import letters as portal_letters
from portal.views import BasePortalView
from rest_framework.response import Response

MODULE = "letters"


def _date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise PortalValidationError("VALIDATION_ERROR") from None


class LetterListView(BasePortalView):
    """GET /letters — письма компании: `direction`, `deal_id`, `q`, `date_from`, `date_to`."""

    required_module = MODULE

    def get(self, request):
        params = request.query_params
        direction = params.get("direction")
        if direction is not None and direction not in LetterDirection.values:
            raise PortalValidationError("VALIDATION_ERROR")
        deal_id = params.get("deal_id")
        if deal_id is not None:
            try:
                deal_id = int(deal_id)
            except ValueError:
                raise PortalValidationError("VALIDATION_ERROR") from None
        q = (params.get("q") or "").strip()
        if len(q) > 200:
            raise PortalValidationError("VALIDATION_ERROR")
        letters = portal_letters.company_letters(
            request.portal_company,
            direction=direction,
            deal_id=deal_id,
            q=q,
            date_from=_date(params.get("date_from")),
            date_to=_date(params.get("date_to")),
        )
        return Response(PortalLetterSerializer(letters, many=True).data)


class LetterDetailView(BasePortalView):
    """GET /letters/{id} — письмо своей компании."""

    required_module = MODULE

    def get(self, request, pk):
        letter = portal_letters.find_company_letter(request.portal_company, pk)
        if letter is None:
            raise Http404
        return Response(PortalLetterSerializer(letter).data)


class LetterFileView(BasePortalView):
    """GET /letters/{id}/file — PDF нашего исходящего письма (поток от EDS через ERP)."""

    required_module = MODULE

    def get(self, request, pk):
        letter = portal_letters.find_company_letter(request.portal_company, pk)
        if letter is None or letter.direction != LetterDirection.OUT:
            raise Http404
        try:
            pdf = portal_letters.letter_pdf(letter)
        except portal_letters.LetterFileUnavailable:
            raise PortalUnavailable("LETTER_FILE_UNAVAILABLE") from None
        if pdf is None:
            raise Http404
        name = quote(f"{letter.number.replace('/', '-')}.pdf")
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f"inline; filename*=UTF-8''{name}"
        return response
