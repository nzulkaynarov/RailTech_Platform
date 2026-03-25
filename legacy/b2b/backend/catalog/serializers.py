from rest_framework import serializers
from master_data.models import (
    UnitOfMeasure, Currency, DeliveryBasis
)
from .models import (
    Product, EquipmentGroup, Category,
    SupplierOffer, ProductImage, ProductDocument
)
from accounts.serializers import CompanySerializer

# --- Simple Reference Serializers ---


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'parent', 'domain_type', 'icon']


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ['id', 'code', 'name']


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ['id', 'code', 'symbol']


class DeliveryBasisSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryBasis
        fields = ['id', 'code', 'name', 'description']


class EquipmentGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentGroup
        fields = ['id', 'name', 'full_path']

# --- Media Serializers ---


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'image_url', 'is_main', 'alt_text']


class ProductDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductDocument
        fields = ['id', 'file', 'file_url', 'name', 'uploaded_at']

# --- Supplier Offer Serializer ---


class SupplierOfferSerializer(serializers.ModelSerializer):
    supplier_data = CompanySerializer(source='supplier', read_only=True)
    currency_data = CurrencySerializer(source='currency', read_only=True)
    delivery_basis_data = DeliveryBasisSerializer(source='delivery_basis', read_only=True)

    class Meta:
        model = SupplierOffer
        fields = [
            'id', 'supplier', 'supplier_data', 'supplier_sku',
            'base_price', 'currency', 'currency_data',
            'delivery_basis', 'delivery_basis_data',
            'stock_status', 'delivery_lead_time',
            'min_order_qty', 'is_active'
        ]

# --- Main Product Serializer (PIM) ---


class ProductSerializer(serializers.ModelSerializer):
    # Readable Nested Objects (for GET)
    category_data = CategorySerializer(source='category', read_only=True)
    manufacturer_data = CompanySerializer(source='manufacturer', read_only=True)
    uom_data = UnitOfMeasureSerializer(source='uom', read_only=True)
    equipment_groups_data = EquipmentGroupSerializer(source='equipment_groups', many=True, read_only=True)

    offers = SupplierOfferSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    documents = ProductDocumentSerializer(many=True, read_only=True)

    main_image_url = serializers.SerializerMethodField()
    main_document_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'sku', 'name', 'description', 'status', 'domain_type',
            'category', 'category_data',
            'manufacturer', 'manufacturer_data',
            'uom', 'uom_data',
            'gost_drawing', 'specifications',
            'equipment_groups', 'equipment_groups_data',
            'offers', 'images', 'documents', 'main_image_url', 'main_document_url',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['sku', 'created_at', 'updated_at']

    def get_main_image_url(self, obj):
        main_img = obj.images.filter(is_main=True).first() or obj.images.first()
        if main_img:
            url = main_img.image.url if main_img.image else main_img.image_url
            if url:
                request = self.context.get('request')
                if request and not url.startswith('http'):
                    return request.build_absolute_uri(url)
                return url
        return None

    def get_main_document_url(self, obj):
        doc = obj.documents.first()
        if doc:
            url = doc.file.url if doc.file else doc.file_url
            if url:
                request = self.context.get('request')
                if request and not url.startswith('http'):
                    return request.build_absolute_uri(url)
                return url
        return None
