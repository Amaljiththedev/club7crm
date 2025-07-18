from rest_framework import serializers
from .models import Member


class MemberSerializer(serializers.ModelSerializer):
    # Read-only calculated fields
    age = serializers.SerializerMethodField(read_only=True)
    bmi = serializers.SerializerMethodField(read_only=True)
    profile_photo = serializers.SerializerMethodField(read_only=True)  # Changed to method field

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

    def get_profile_photo(self, obj):
        request = self.context.get('request', None)
        if obj.profile_photo:
            try:
                import os
                file_path = obj.profile_photo.path
                if os.path.exists(file_path):
                    url = obj.profile_photo.url
                    if request is not None:
                        return request.build_absolute_uri(url)
                    else:
                        return url
            except Exception:
                pass
        return None
