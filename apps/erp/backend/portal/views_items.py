"""Миниатюра позиции каталога в Cabinet (план ЕД-4): та же 96×96 WebP, что у сотрудников, но по правилу видимости портала.

Сессия видит фото позиции, если позиция видна ей и без фото:
- опубликована — витрина каталога (модуль `catalog_requests`);
- стоит в КП, которое видит клиент (`quotes`), или в строке его поставки (`deliveries`);
- карточка партнёра своя или опубликованная (`my_products`); сопоставленная чужая черновая — нет (как и её название).
Иначе — 404 без различия «нет фото» и «не видно»: перебором id чужой каталог не узнать.
"""

from django.db.models import Q
from django.http import Http404, HttpResponse
from portal.projections import client_quotes_q
from portal.services import partner_products
from portal.views import BasePortalView
from sales.models import DeliveryLine, Quote, QuoteItem

from catalog.desk import images
from catalog.models import Product

PARTNER_MODULE = "my_products"


def _visible(request) -> Q:
    company, modules = request.portal_company, set(getattr(request, "portal_modules", ()))
    rule = Q(pk__in=[])
    if "catalog_requests" in modules:
        rule |= Q(status__code="PUBLISHED")
    if "quotes" in modules:
        quotes = Quote.objects.filter(client_quotes_q(), deal__company=company)
        rule |= Q(pk__in=QuoteItem.objects.filter(quote__in=quotes).values("product_id"))
    if "deliveries" in modules:
        delivered = DeliveryLine.objects.filter(deal__company=company, quote_item__product__isnull=False)
        rule |= Q(pk__in=delivered.values("quote_item__product_id"))
    if PARTNER_MODULE in modules:
        cards = partner_products.partner_cards(company).filter(partner_products._visible_q(company))
        rule |= Q(pk__in=cards.values("pk"))
    return rule


class ItemThumbnailView(BasePortalView):
    """GET /items/{id}/thumbnail — миниатюра главного фото позиции, видимой сессии; иначе 404."""

    required_module = ("catalog_requests", "quotes", "deliveries", PARTNER_MODULE)

    def get(self, request, pk):
        product = Product.objects.filter(_visible(request), pk=pk).exclude(status__code="ARCHIVED").first()
        image = images.main_image(product) if product is not None else None
        if image is None:
            raise Http404
        try:
            data = images.thumbnail(image)
        except (OSError, ValueError):  # файла нет в хранилище или он не картинка
            raise Http404 from None
        return HttpResponse(data, content_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})
