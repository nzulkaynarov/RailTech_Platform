"""Counterparty relationship book API (CRM Phase B, spec-remaining-2026-07-07 §2.2).

Read surface of the two-sided book: an owner company's edges («мои клиенты» for a seller,
«мои поставщики» for a buyer) with denormalized rollups; PATCH is limited to the two
human-managed fields (stage verdict, account owner). Thin views — scoping only.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from crm.models import CounterpartyRelationship, RelationshipDirection


class RelationshipCounterpartySerializer(serializers.Serializer):
    """Account summary embedded in an edge (nested read, flat write pattern)."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    inn = serializers.CharField(read_only=True, allow_null=True)
    stated_inn = serializers.CharField(read_only=True)
    is_registered = serializers.BooleanField(read_only=True)
    primary_contact_id = serializers.SerializerMethodField()

    def get_primary_contact_id(self, company):
        """The counterparty's primary contact — the target for a CB-invite (Phase D). Only
        meaningful for an offline company; a registered one has real members instead."""
        contact = company.contacts.order_by("-is_primary", "id").first()
        return contact.id if contact else None


class RelationshipSerializer(serializers.ModelSerializer):
    counterparty = RelationshipCounterpartySerializer(source="counterparty_company", read_only=True)
    owner_member_name = serializers.CharField(source="owner_member.user.get_full_name", read_only=True, default="")
    contacts_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CounterpartyRelationship
        fields = [
            "id",
            "direction",
            "stage",
            "source",
            "counterparty",
            "owner_member",
            "owner_member_name",
            "contacts_count",
            "first_interaction_at",
            "last_interaction_at",
            "deals_count",
            "won_count",
            "gmv",
            "created_at",
        ]
        read_only_fields = [field for field in fields if field not in ("stage", "owner_member")]

    def validate_owner_member(self, member):
        """The account owner must belong to the edge's own company — never a foreign member."""
        if member is not None and self.instance and member.company_id != self.instance.owner_company_id:
            raise serializers.ValidationError("OWNER_MEMBER_NOT_IN_COMPANY")
        return member


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="direction",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=[RelationshipDirection.CLIENT, RelationshipDirection.SUPPLIER],
            description="CLIENT → книга клиентов (seller context), SUPPLIER → книга поставщиков (buyer context)",
        ),
    ],
    tags=["CRM Counterparties"],
)
class RelationshipViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """The counterparty book of the user's own companies. No create/delete over the API —
    edges are born from real interactions (routing, offline clients, lead conversion)."""

    serializer_class = RelationshipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Count

        user = self.request.user
        queryset = (
            CounterpartyRelationship.objects.select_related("counterparty_company", "owner_member__user")
            .prefetch_related("counterparty_company__contacts")
            .annotate(contacts_count=Count("counterparty_company__contacts", distinct=True))
        )
        if not (getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False)):
            my_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
            queryset = queryset.filter(owner_company_id__in=my_company_ids)
        direction = self.request.query_params.get("direction")
        if direction in RelationshipDirection.values:
            queryset = queryset.filter(direction=direction)
        return queryset
