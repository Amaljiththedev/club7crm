from rest_framework import serializers
from .models import Member


class MemberSerializer(serializers.ModelSerializer):
    # Read-only calculated fields
    age = serializers.SerializerMethodField(read_only=True)
    bmi = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Member
        fields = [
            'id',
            'full_name',
            'email',
            'phone_number',
            'alternate_phone',
            'gender',
            'dob',
            'age',
            'marital_status',
            'occupation',
            'profession',
            'referral_source',
            'firm_name',
            'area_or_locality',

            # Address
            'address_line_1',
            'address_line_2',
            'city',
            'district',
            'state',
            'pin_code',

            # Physical
            'height_cm',
            'weight_kg',
            'bmi',

            # Biometric & Photo
            'biometric_id',
            'profile_photo',

            # Timestamps
            'created_at',
            'updated_at',

            'is_active',
        ]
        read_only_fields = (
            'biometric_id',
            'created_at',
            'updated_at',
            'age',
            'bmi',
        )

    def get_age(self, obj):
        return obj.age

    def get_bmi(self, obj):
        return obj.bmi
