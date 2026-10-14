"""Действия опубликованного слоя карточки (M1-ERP-07): видимость для клиента и публичность медиа.

Логика — в `catalog.publishing` (видимость) и здесь же тонкие обёртки над полем `is_public` медиа;
права — `required_permissions` вьюхи (`visibility` → `catalog.publish`, медиа → `catalog.manage`).
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import ProductDocument, ProductImage


def is_staff_viewer(user) -> bool:
    """Сотрудник бэк-офиса (своя компания) или администратор — видит внутренний слой карточки.
    Остальные (покупательский аккаунт до M2-ERP-01) — только опубликованный слой."""
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    if getattr(user, "is_superuser", False):
        return True
    from accounts.services.permissions import is_seller

    return is_seller(user)


def _flag(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("true", "1"):
        return True
    if str(value).lower() in ("false", "0"):
        return False
    return None


_VISIBILITY_REQUEST = {
    "application/json": {
        "type": "object",
        "required": ["visibility"],
        "properties": {"visibility": {"type": "string", "enum": ["cabinet", "on_request"]}},
    }
}
_PUBLIC_FLAG_REQUEST = {
    "application/json": {
        "type": "object",
        "required": ["is_public"],
        "properties": {"is_public": {"type": "boolean"}},
    }
}


class ProductLayerActionsMixin:
    """Миксин `ProductViewSet`: видимость карточки и отметка «видно клиенту» у фото и документов."""

    def layer_error_response(self, product, error: str, visibility=None) -> Response:
        """Код ошибки сервиса публикации → ответ API. Неполнота несёт список недостающего."""
        from catalog.publishing import PUBLISH_INCOMPLETE, publish_blockers

        if error == "PRODUCT_NOT_YOURS":
            return Response({"detail": error}, status=status.HTTP_403_FORBIDDEN)
        body = {"detail": error}
        if error == PUBLISH_INCOMPLETE:
            body["missing"] = publish_blockers(product, visibility)
        return Response(body, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Set what the client sees: price in Cabinet or «on request»",
        description=(
            "Видимость карточки для клиента: `cabinet` — цена, наличие и срок в кабинете; `on_request` — "
            "карточка видна, цена «по запросу». У опубликованной карточки новая видимость проходит порог "
            "публикации (`CATALOG_PUBLISH_INCOMPLETE` + `missing`). Право — `catalog.publish`."
        ),
        request=_VISIBILITY_REQUEST,
        responses={200: OpenApiResponse(description="Product"), 400: OpenApiResponse(description="Invalid")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def visibility(self, request, pk=None):
        from catalog.publishing import set_visibility

        product = self.get_object()
        target = request.data.get("visibility") if hasattr(request.data, "get") else None
        updated, error = set_visibility(product, request.user, target)
        if error:
            return self.layer_error_response(product, error, target)
        return Response(self.get_serializer(updated).data)

    def _set_media_public(self, request, model, media_id, not_found_code):
        product = self.get_object()
        media = model.objects.filter(pk=media_id, product=product).first()
        if media is None:
            return Response({"detail": not_found_code}, status=status.HTTP_404_NOT_FOUND)
        flag = _flag(request.data.get("is_public")) if hasattr(request.data, "get") else None
        if flag is None:
            return Response({"detail": "IS_PUBLIC_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        media.is_public = flag
        media.save(update_fields=["is_public"])
        return Response({"id": media.pk, "is_public": media.is_public})

    @extend_schema(
        summary="Show or hide a product image to clients",
        request=_PUBLIC_FLAG_REQUEST,
        responses={200: OpenApiResponse(description="{id, is_public}"), 404: OpenApiResponse(description="No image")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="image-visibility/(?P<image_id>[0-9]+)")
    def image_visibility(self, request, pk=None, image_id=None):
        return self._set_media_public(request, ProductImage, image_id, "IMAGE_NOT_FOUND")

    @extend_schema(
        summary="Show or hide a product document to clients",
        request=_PUBLIC_FLAG_REQUEST,
        responses={
            200: OpenApiResponse(description="{id, is_public}"),
            404: OpenApiResponse(description="No document"),
        },
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="document-visibility/(?P<doc_id>[0-9]+)")
    def document_visibility(self, request, pk=None, doc_id=None):
        return self._set_media_public(request, ProductDocument, doc_id, "DOCUMENT_NOT_FOUND")
