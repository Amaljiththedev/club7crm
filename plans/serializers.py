from rest_framework import serializers
from .models import MembershipPlan, Feature, PlanFeature

class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            'id', 'name', 'description', 'feature_type',
            'price_per_session', 'is_active', 'created_at'
        ]

class PlanFeatureSerializer(serializers.ModelSerializer):
    feature = FeatureSerializer(read_only=True)
    class Meta:
        model = PlanFeature
        fields = ['feature', 'allowed_uses', 'is_unlimited']

class MembershipPlanSerializer(serializers.ModelSerializer):
    features = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = [
            'id', 'name', 'plan_type', 'duration_days', 'price',
            'description', 'includes_personal_training', 'is_active', 'created_at', 'features'
        ]

    def get_features(self, obj):
        plan_features = PlanFeature.objects.filter(plan=obj)
        return PlanFeatureSerializer(plan_features, many=True).data
