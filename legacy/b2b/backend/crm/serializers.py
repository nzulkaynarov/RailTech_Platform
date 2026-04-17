from rest_framework import serializers
from .models import Deal, Quote, QuoteItem, Message, ActivityLog, Lead


class QuoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_domain = serializers.CharField(source='product.domain_type.code', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    product_gost = serializers.CharField(source='product.gost_drawing', read_only=True)
    offer_supplier_name = serializers.CharField(source='offer.supplier.name', read_only=True)

    class Meta:
        model = QuoteItem
        fields = [
            'id', 'quote', 'product', 'product_name', 'product_domain',
            'product_sku', 'product_gost', 'offer', 'offer_supplier_name',
            'imported_raw_name', 'quantity', 'assigned_at',
            'frozen_base_price', 'frozen_currency', 'logistics_cost',
            'customs_duty', 'margin_percent', 'landed_cost', 'final_price_excl_vat'
        ]
        read_only_fields = ['landed_cost', 'final_price_excl_vat']


class QuoteSerializer(serializers.ModelSerializer):
    items = QuoteItemSerializer(many=True, read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    status_code = serializers.CharField(source='status.code', read_only=True)

    class Meta:
        model = Quote
        fields = [
            'id', 'deal', 'version', 'status', 'status_code', 'status_name',
            'prepared_by', 'tax_country', 'vat_rate',
            'subtotal_excl_vat', 'vat_amount', 'total_incl_vat',
            'valid_until', 'notes', 'pdf_file', 'frozen_at',
            'approved_by', 'approved_at',
            'items', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'subtotal_excl_vat', 'vat_amount', 'total_incl_vat',
            'approved_by', 'approved_at', 'created_at',
        ]


class DealListSerializer(serializers.ModelSerializer):
    """MED-3: Optimized list serializer with human-readable names."""
    stage_name = serializers.CharField(source='stage.name', read_only=True)
    stage_code = serializers.CharField(source='stage.code', read_only=True)
    company_name = serializers.CharField(source='company.name', read_only=True)
    active_quote = QuoteSerializer(read_only=True)

    class Meta:
        model = Deal
        fields = [
            "id", "title", "company", "company_name",
            "stage", "stage_code", "stage_name", "total_value",
            "manager", "active_quote", "created_at",
        ]


class DealDetailSerializer(serializers.ModelSerializer):
    """MED-3: Full detail serializer with quotes."""
    quotes = QuoteSerializer(many=True, read_only=True)
    active_quote = QuoteSerializer(read_only=True)
    stage_name = serializers.CharField(source='stage.name', read_only=True)
    company_name = serializers.CharField(source='company.name', read_only=True)
    client_name = serializers.CharField(source='client.get_full_name', read_only=True)

    class Meta:
        model = Deal
        fields = [
            'id', 'company', 'company_name', 'client', 'client_name',
            'manager', 'stage', 'stage_name', 'title', 'notes',
            'active_quote', 'quotes', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'company': {'required': False},
            'client': {'required': False},
        }


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    is_me = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'deal', 'sender', 'sender_name', 'text',
            'message_type', 'timestamp', 'is_me',
        ]
        read_only_fields = ['sender', 'timestamp']

    def get_is_me(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.sender == request.user
        return False


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = ['id', 'name', 'company', 'phone', 'email', 'message', 'is_processed', 'created_at']
        read_only_fields = ['created_at', 'is_processed']


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = ActivityLog
        fields = ['id', 'action', 'detail', 'user_name', 'level', 'timestamp']
