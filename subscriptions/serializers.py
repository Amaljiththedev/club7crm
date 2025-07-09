# subscriptions/serializers.py
from rest_framework import serializers
from django.db import transaction
from subscriptions.models import Subscription, SubscriptionHistory
from members.models import Member
from plans.models import MembershipPlan
from members.serializers import MemberSerializer
from plans.serializers import MembershipPlanSerializer


class SubscriptionSerializer(serializers.ModelSerializer):
    member = MemberSerializer(read_only=True)
    plan = MembershipPlanSerializer(read_only=True)
    grace_period_days = serializers.ReadOnlyField()
    is_in_grace_period = serializers.ReadOnlyField()
    can_change_plan = serializers.ReadOnlyField()
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'member', 'plan', 'start_date', 'end_date', 
            'status', 'is_renewal', 'signed_by_member', 'signature_file',
            'member_snapshot', 'created_at', 'updated_at',
            'grace_period_days', 'is_in_grace_period', 'can_change_plan'
        ]


class EnrollSubscriptionSerializer(serializers.ModelSerializer):
    member_id = serializers.IntegerField(write_only=True)  # Changed to IntegerField
    plan_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = Subscription
        fields = [
            'member_id', 'plan_id', 'start_date', 'status', 
            'is_renewal', 'signed_by_member', 'signature_file'
        ]
        extra_kwargs = {
            'status': {'default': 'pending'},
            'is_renewal': {'default': False},
            'signed_by_member': {'default': False}
        }

    def validate_member_id(self, value):
        try:
            member = Member.objects.get(id=value)  # value is already int
            if not member.is_active:
                raise serializers.ValidationError("Member is not active")
            return value
        except Member.DoesNotExist:
            raise serializers.ValidationError("Member not found")

    def validate_plan_id(self, value):
        try:
            MembershipPlan.objects.get(id=value)
            return value
        except MembershipPlan.DoesNotExist:
            raise serializers.ValidationError("Plan not found")

    def validate(self, attrs):
        member_id = attrs.get('member_id')
        
        # Check if member already has an active subscription
        if Subscription.objects.filter(member_id=member_id, status='active').exists():
            raise serializers.ValidationError("Member already has an active subscription")
        
        return attrs

    def create(self, validated_data):
        member_id = validated_data.pop('member_id')
        plan_id = validated_data.pop('plan_id')
        
        member = Member.objects.get(id=member_id)
        plan = MembershipPlan.objects.get(id=plan_id)
        
        # Store member snapshot
        member_snapshot = MemberSerializer(member).data
        
        subscription = Subscription.objects.create(
            member=member,
            plan=plan,
            member_snapshot=member_snapshot,
            **validated_data
        )
        
        return subscription


class PlanChangeSerializer(serializers.Serializer):
    new_plan_id = serializers.UUIDField()
    
    def validate_new_plan_id(self, value):
        try:
            MembershipPlan.objects.get(id=value)
            return value
        except MembershipPlan.DoesNotExist:
            raise serializers.ValidationError("Plan not found")
    
    def validate(self, attrs):
        subscription = self.context.get('subscription')
        new_plan_id = attrs.get('new_plan_id')
        
        if not subscription:
            raise serializers.ValidationError("Subscription context required")
        
        if not subscription.can_change_plan():
            raise serializers.ValidationError("Plan change not allowed. Grace period expired or subscription not active.")
        
        if str(subscription.plan.id) == str(new_plan_id):
            raise serializers.ValidationError("New plan is same as current plan")
        
        return attrs


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    changed_by_username = serializers.SerializerMethodField()
    
    class Meta:
        model = SubscriptionHistory
        fields = [
            'id', 'subscription', 'snapshot', 'member_snapshot', 
            'note', 'created_at', 'changed_by', 'changed_by_username'
        ]
    
    def get_changed_by_username(self, obj):
        return obj.changed_by.username if obj.changed_by else None


class SubscriptionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing subscriptions"""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_phone = serializers.CharField(source='member.phone_number', read_only=True)
    member_biometric_id = serializers.CharField(source='member.biometric_id', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_duration = serializers.IntegerField(source='plan.duration_days', read_only=True)
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'member_name', 'member_phone', 'member_biometric_id',
            'plan_name', 'plan_duration', 'start_date', 'end_date', 
            'status', 'is_renewal', 'created_at'
        ]