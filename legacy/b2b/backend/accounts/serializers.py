from rest_framework import serializers
from .models import Company, CustomUser, KYCDocument, CompanyMember


class KYCDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source='doc_type.name', read_only=True)

    class Meta:
        model = KYCDocument
        fields = ['id', 'doc_type', 'doc_type_display', 'file', 'original_filename', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at', 'original_filename', 'doc_type_display']


class CompanyMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = CompanyMember
        fields = [
            'id', 'user', 'user_email', 'company', 'company_name',
            'role', 'role_name', 'is_primary', 'is_active', 'joined_at'
        ]


class CompanySerializer(serializers.ModelSerializer):
    kyc_documents = KYCDocumentSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()
    verification_status_name = serializers.CharField(source='verification_status.name', read_only=True)
    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'inn', 'verification_status', 'verification_status_name',
            'bank_account', 'mfo', 'legal_address', 'phone',
            'contact_person', 'country', 'website', 'email', 'logo', 'kyc_notes',
            'created_at', 'kyc_documents', 'user_count', 'company_types'
        ]
        read_only_fields = ['verification_status', 'created_at']

    def get_user_count(self, obj):
        # Use len() to leverage prefetched members cache instead of extra COUNT query
        try:
            return len(obj.members.all())
        except AttributeError:
            return 0

    def get_company_types(self, obj):
        # Use Python list comprehension to leverage prefetched types cache
        return [t.code for t in obj.types.all()]


class UserSerializer(serializers.ModelSerializer):
    memberships = CompanyMemberSerializer(many=True, read_only=True)
    primary_company = CompanySerializer(read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    role_code = serializers.CharField(source='role.code', read_only=True)
    kyc_status = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'avatar', 'role', 'role_code', 'role_name', 'kyc_status',
            'is_active', 'memberships', 'primary_company', 'last_login', 'date_joined'
        ]
        read_only_fields = ['id', 'role', 'last_login', 'date_joined']

    def get_kyc_status(self, obj):
        if obj.primary_company and obj.primary_company.verification_status:
            return obj.primary_company.verification_status.code
        return None


class KYCVerificationSerializer(serializers.Serializer):
    status_code = serializers.CharField(help_text="Code from VerificationStatus (e.g. 'L2_VERIFIED')")
    comment = serializers.CharField(required=False, allow_blank=True)


class RegisterInterestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)


class SetupPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(min_length=8)


class SubmitProfileSerializer(serializers.Serializer):
    inn = serializers.CharField(max_length=20)
    companyName = serializers.CharField(max_length=255)
    role_code = serializers.CharField(max_length=50, help_text="WorkspaceRole code (e.g. 'OWNER')")
    company_type = serializers.CharField(max_length=50, required=False, default='CLIENT',
                                         help_text="CompanyType code (e.g. 'CLIENT', 'MANUFACTURER', 'SUPPLIER')")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
