from rest_framework import serializers
from .models import MembershipPlan

class MembershipPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipPlan
        fields = ['id', 'name', 'duration_days', 'price', 'type']
