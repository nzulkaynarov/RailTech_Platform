"""«Ссылка клиента в Кабинете» у договора, счёта и акта (ДК-3б): список ссылок получателей и «Отозвать ссылку».

Право — то же, что на отправку документа (`required_permissions` вьюхи: `contract.manage`, `finance.invoice`,
`fulfillment.act`); документ берётся через `get_object()` вьюхи, то есть в пределах видимых вызывающему.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from crm.serializers.document_links import DocumentClientLinksSerializer


class DocumentLinksMixin:
    """Подмешивается во вьюху договора, счёта и акта; вид документа — `document_link_kind`."""

    document_link_kind: str

    def _require_send_right(self, request) -> None:
        """Чтение списка — тоже за правом отправки: гейт ролей безопасные методы не проверяет."""
        from accounts.services.permissions import is_seller, staff_has_permission
        from core.permissions import ROLE_NOT_PERMITTED

        user = request.user
        rule = self.required_permissions["revoke_client_links"]
        if user.is_superuser or (is_seller(user) and staff_has_permission(user, rule)):
            return
        raise PermissionDenied(detail=ROLE_NOT_PERMITTED, code=ROLE_NOT_PERMITTED)

    def _client_links(self, doc) -> dict:
        from portal.services.doc_links import document_link_rows

        links = document_link_rows(self.document_link_kind, doc)
        return {"links": links, "can_revoke": any(row["state"] == "active" for row in links)}

    @extend_schema(
        summary="Recipient links of the document in the Cabinet",
        description="Every personal link the document went out with: masked address, sent, opened, state "
        "(`active`, `revoked`, `expired`, `superseded`). Same right as sending the document; links of other "
        "documents are never listed.",
        responses=DocumentClientLinksSerializer,
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="client-links")
    def client_links(self, request, pk=None):
        self._require_send_right(request)
        return Response(self._client_links(self.get_object()))

    @extend_schema(
        summary="Revoke the Cabinet links of the document",
        description="Pulls every live link of THIS document (all recipients); idempotent, journal event "
        "`<kind>.link_revoked`. Further opens answer 410 `DOC_LINK_REVOKED`. Same right as sending the document. "
        "The response carries the refreshed list.",
        request=None,
        responses=DocumentClientLinksSerializer,
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="revoke-client-links")
    def revoke_client_links(self, request, pk=None):
        from portal.services.doc_links import revoke_document_links_logged

        doc = self.get_object()
        revoke_document_links_logged(self.document_link_kind, doc, request.user)
        return Response(self._client_links(doc))
